import asyncio, socket

import pytest

import merge, traffic, wifi


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def pool(*keys, clock=None, up=True):
    """A pool of links on fake IPs, rand fixed so ties start at the first link."""
    p = merge.Pool(clock=clock or Clock(), rand=lambda: 0.0)
    p.update({k: (i, f"10.0.0.{i + 1}") for i, k in enumerate(keys)})
    for k in keys:
        if up:
            p.mark(k, True)
    return p


def test_pick_least_active():
    p = pool("a", "b")
    a = p.pick()
    assert a.key == "a" and a.active == 1
    b = p.pick()
    assert b.key == "b"
    assert p.pick().key == "a"
    assert a.active == 2
    p.release(a); p.release(a); p.release(a)
    assert a.active == 0  # never below 0


def test_weight_scales_share():
    p = pool("a", "b")
    p.links()[0].weight = 2.0
    got = [p.pick().key for _ in range(6)]
    assert got.count("a") == 4 and got.count("b") == 2


def test_best_tier_only():
    p = pool("a", "b", up=False)
    p.mark("a", True)
    assert {p.pick().key for _ in range(4)} == {"a"}
    p.mark("a", False)
    assert {p.pick().key for _ in range(4)} == {"b"}


def test_sidelined_skipped_then_back():
    c = Clock()
    p = pool("a", "b", clock=c)
    p.sideline("a")
    assert [p.pick().key for _ in range(3)] == ["b", "b", "b"]
    c.t = 15.0
    assert "a" in {p.pick().key for _ in range(2)}
    p.sideline("a"); p.sideline("b")  # all sidelined: still hands out the least active
    least = min(p.links(), key=lambda l: l.active)
    assert p.pick().key == least.key


def test_exclude_and_empty():
    p = pool("a", "b")
    assert p.pick({"a"}).key == "b"
    assert p.pick({"a", "b"}) is None
    assert merge.Pool().pick() is None


def test_update_replaces_address_keeps_counts():
    p = pool("a", "b")
    a = p.links()[0]
    a.active = 2
    p.update({"a": (7, "192.168.1.9")})
    assert [(l.key, l.ip, l.index, l.active, l.state) for l in p.links()] == [("a", "192.168.1.9", 7, 2, "up")]
    p.update({})
    assert p.pick() is None


def test_observe_sets_weight_from_peak():
    p = pool("a", "b")
    a, b = p.links()
    a.active = b.active = 1  # busy links follow the peaks exactly; idle ones drift (next test)
    p.observe("a", 10e6); p.observe("b", 5e6)
    assert (a.weight, b.weight) == (1.0, 0.5)
    p.observe("b", 0)
    assert b.peak == pytest.approx(5e6 * 0.97)
    for _ in range(500):
        p.observe("b", 0)
    assert b.weight == 0.05
    q = pool("a", "b")
    q.observe("a", 0)
    assert [l.weight for l in q.links()] == [1.0, 1.0]


def test_idle_link_drifts_back_up():
    p = pool("a", "b")
    a, b = p.links()
    b.active = 1
    p.observe("a", 10e6); p.observe("b", 0)
    assert b.weight == 0.05
    b.active = 0
    def tick():
        p.observe("a", 10e6); p.observe("b", 0)
    tick()
    assert b.weight == pytest.approx(0.15)
    for _ in range(9):
        tick()
    assert b.weight == 1.0
    for _ in range(5):
        tick()
    assert b.weight == 1.0  # capped
    b.weight, b.active = 0.05, 1  # busy: no drift
    for _ in range(5):
        tick()
    assert b.weight == 0.05


# ---- finding the links, probing, dialling ----
def test_find_links_skips_off_and_unaddressed(monkeypatch):
    monkeypatch.setattr(wifi, "radios", lambda: {k: {"guid": k, "on": k != "off"} for k in ("unigen", "builtin", "off", "noip", "bad")})

    def idx(guid):
        if guid == "bad":
            raise OSError("no row")
        return {"unigen": 5, "builtin": 7, "off": 9, "noip": 11}[guid]
    monkeypatch.setattr(traffic, "if_index", idx)
    monkeypatch.setattr(merge, "ipv4_by_index", lambda: {5: "192.168.1.5", 7: "192.168.1.7", 9: "10.0.0.9"})
    assert merge.find_links() == {"unigen": (5, "192.168.1.5"), "builtin": (7, "192.168.1.7")}


def test_probe_true_when_second_target_answers(monkeypatch):
    seen = []

    def open_on(link, addr, timeout=10.0):
        seen.append((addr, timeout))
        if addr == merge.PROBE_TARGETS[0]:
            raise OSError(10060, "timed out")
        return socket.socket()
    monkeypatch.setattr(merge, "open_on", open_on)
    assert merge.probe(merge.Link("a", 1, "10.0.0.1")) is True
    assert [a for a, _ in seen] == list(merge.PROBE_TARGETS) and all(t == 3.0 for _, t in seen)
    monkeypatch.setattr(merge, "open_on", lambda link, addr, timeout=10.0: (_ for _ in ()).throw(OSError(10060, "t")))
    assert merge.probe(merge.Link("a", 1, "10.0.0.1")) is False


class FakeSock:
    def __init__(self):
        self.blocking = True

    def setblocking(self, flag):
        self.blocking = flag


@pytest.fixture
def resolve(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


def test_dial_fails_over_on_unreachable(monkeypatch, resolve):
    p = pool("a", "b")
    s = FakeSock()

    def open_on(link, addr, timeout=10.0):
        if link.key == "a":
            raise OSError(10051, "unreachable")
        return s
    monkeypatch.setattr(merge, "open_on", open_on)
    sock, link = asyncio.run(merge.dial(p, "example.com", 443))
    a, b = p.links()
    assert sock is s and link is b and not s.blocking
    assert a.active == 0 and b.active == 1 and a.until > 0


def test_dial_refused_is_not_failover(monkeypatch, resolve):
    p = pool("a", "b")
    monkeypatch.setattr(merge, "open_on", lambda link, addr, timeout=10.0: (_ for _ in ()).throw(OSError(10061, "refused")))
    with pytest.raises(merge.DialError) as e:
        asyncio.run(merge.dial(p, "example.com", 443))
    assert e.value.code == 5
    assert all(l.until == 0 and l.active == 0 for l in p.links())


def test_dial_all_links_failing_over_is_network_unreachable(monkeypatch, resolve):
    p = pool("a", "b")
    monkeypatch.setattr(merge, "open_on", lambda link, addr, timeout=10.0: (_ for _ in ()).throw(socket.timeout()))
    with pytest.raises(merge.DialError) as e:
        asyncio.run(merge.dial(p, "example.com", 443))
    assert e.value.code == 3 and all(l.active == 0 and l.until > 0 for l in p.links())


def test_dial_no_links(resolve):
    with pytest.raises(merge.DialError) as e:
        asyncio.run(merge.dial(merge.Pool(), "example.com", 443))
    assert e.value.code == 3


def test_dial_no_links_does_not_resolve(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: calls.append(a) or [])
    with pytest.raises(merge.DialError) as e:
        asyncio.run(asyncio.wait_for(merge.dial(merge.Pool(), "example.com", 443), 1))
    assert e.value.code == 3 and calls == []


def test_dial_ipv6_only_host_errors(monkeypatch):
    def gai(*a, **k):
        assert k.get("family") == socket.AF_INET or socket.AF_INET in a
        raise socket.gaierror(11001, "no address")
    monkeypatch.setattr(socket, "getaddrinfo", gai)
    with pytest.raises(merge.DialError) as e:
        asyncio.run(merge.dial(pool("a"), "v6.example", 443))
    assert e.value.code == 4
