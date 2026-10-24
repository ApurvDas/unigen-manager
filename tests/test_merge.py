import asyncio, concurrent.futures, socket, threading, time

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
    monkeypatch.setattr(merge, "adapters", lambda: [])
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


@pytest.mark.parametrize("ip", ["127.0.0.1", "192.168.1.1", "10.0.0.5", "172.16.3.4", "169.254.1.1", "198.18.0.7"])
def test_dial_local_destinations_go_out_unbound(monkeypatch, ip):
    """Loopback, LAN and fake-IP answers aren't reached through a pooled link: a bound socket fails on them and would sideline it."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))])
    monkeypatch.setattr(merge, "open_on", lambda *a, **k: pytest.fail("a pooled link was used"))
    s, seen = FakeSock(), []
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout=None: seen.append((addr, timeout)) or s)
    p = pool("a", "b")
    sock, link = asyncio.run(merge.dial(p, "nas.local", 80))
    assert sock is s and not s.blocking and seen == [((ip, 80), 10.0)]
    assert link.key == "direct" and link not in p.links()
    assert all(l.active == 0 and l.until == 0 and l.opened == 0 for l in p.links())
    p.release(link)  # what _tunnel does at the end: harmless for a link that isn't pooled
    assert link.active == 0


@pytest.mark.parametrize("err, code", [(OSError(10061, "refused"), 5), (OSError(10065, "no route"), 4), (socket.timeout(), 4)])
def test_dial_local_failure_never_sidelines(monkeypatch, err, code):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 80))])
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout=None: (_ for _ in ()).throw(err))
    p = pool("a", "b")
    with pytest.raises(merge.DialError) as e:
        asyncio.run(merge.dial(p, "router", 80))
    assert e.value.code == code and all(l.until == 0 and l.active == 0 for l in p.links())


def test_dial_global_destination_still_uses_a_link(monkeypatch, resolve):
    used = []
    monkeypatch.setattr(merge, "open_on", lambda link, addr, timeout=10.0: used.append(link.key) or FakeSock())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("a global address went out unbound"))
    sock, link = asyncio.run(merge.dial(pool("a"), "example.com", 443))
    assert used == ["a"] and link.key == "a"


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


# ---- Ethernet and USB tethering are links too ----
def adapter(guid, desc, name="Ethernet", ip="192.168.0.10", up=True, type_=6, index=20):
    return {"guid": guid, "index": index, "type": type_, "up": up, "desc": desc, "name": name, "ip": ip}


@pytest.mark.parametrize("desc, name, type_, want", [
    ("Realtek PCIe GbE Family Controller", "Ethernet", 6, "ethernet"),
    ("Intel(R) Ethernet Connection (7) I219-V", "Ethernet 2", 6, "ethernet"),
    ("Realtek USB GbE Family Controller", "Ethernet 3", 6, "ethernet"),  # a USB network card is wired Ethernet, not a phone
    ("Remote NDIS based Internet Sharing Device", "Ethernet 4", 6, "tether"),  # Android, USB tethering
    ("Samsung Mobile USB Remote NDIS Network Device", "Ethernet 5", 6, "tether"),
    ("USB Ethernet/RNDIS Gadget", "Ethernet 6", 6, "tether"),
    ("Generic USB NCM Network Adapter", "Ethernet 7", 6, "tether"),
    ("Apple Mobile Device Ethernet", "Ethernet 8", 6, "tether"),  # iPhone, Personal Hotspot over USB
    ("iPhone USB Ethernet", "Ethernet 9", 6, "tether"),
    ("Hyper-V Virtual Ethernet Adapter", "vEthernet (Default Switch)", 6, None),
    ("Hyper-V Virtual Ethernet Adapter #2", "vEthernet (WSL)", 6, None),
    ("VirtualBox Host-Only Ethernet Adapter", "Ethernet 10", 6, None),
    ("VMware Virtual Ethernet Adapter for VMnet8", "VMware Network Adapter VMnet8", 6, None),
    ("TAP-Windows Adapter V9", "Ethernet 11", 6, None),
    ("Wintun Userspace Tunnel", "Wintun", 6, None),
    ("Cloudflare WARP Interface Tunnel", "CloudflareWARP", 6, None),
    ("Meta Tunnel", "Meta", 6, None),  # Clash Verge's TUN adapters
    ("Clash Tunnel", "Clash", 6, None),
    ("sing-box", "Ethernet 13", 6, None),
    ("Mihomo", "Mihomo", 6, None),
    ("WireGuard Tunnel", "wg0", 6, None),
    ("OpenVPN Data Channel Offload", "OpenVPN", 6, None),
    ("Bluetooth Device (Personal Area Network)", "Bluetooth Network Connection", 6, None),
    ("Microsoft Kernel Debug Network Adapter", "Ethernet 12", 6, None),
    ("Software Loopback Interface 1", "Loopback Pseudo-Interface 1", 24, None),
    ("Intel(R) Wi-Fi 6 AX201 160MHz", "Wi-Fi", 71, None),  # Wi-Fi links come from the WLAN API
    ("WAN Miniport (PPPOE)", "Broadband", 23, None),
])
def test_classify(desc, name, type_, want):
    assert merge.classify(adapter("g", desc, name, type_=type_)) == want


def wifi_world(monkeypatch, wired, radios=None):
    monkeypatch.setattr(wifi, "radios", lambda: radios if radios is not None else {"unigen": {"guid": "u", "on": True}, "builtin": {"guid": "b", "on": True}})
    monkeypatch.setattr(traffic, "if_index", lambda guid: {"u": 5, "b": 7}[guid])
    monkeypatch.setattr(merge, "ipv4_by_index", lambda: {5: "192.168.1.5", 7: "10.0.0.7"})
    monkeypatch.setattr(merge, "adapters", lambda: wired)


def test_scan_links_lists_wifi_ethernet_and_tethering(monkeypatch):
    wifi_world(monkeypatch, [
        adapter("AAAA-1", "Realtek PCIe GbE Family Controller", index=20, ip="192.168.0.10"),
        adapter("BBBB-2", "Remote NDIS based Internet Sharing Device", "Ethernet 3", index=21, ip="192.168.42.129"),
        adapter("CCCC-3", "Hyper-V Virtual Ethernet Adapter", "vEthernet (WSL)", index=22, ip="172.20.0.1"),
        adapter("DDDD-4", "Intel(R) Ethernet", "Ethernet 2", index=23, ip=None, up=False),  # no cable
        adapter("EEEE-5", "Intel(R) Ethernet", "Ethernet 4", index=24, ip=None),  # up, but only a link-local address (adapters() drops it)
    ])
    got = {l["key"]: l for l in merge.scan_links()}
    assert list(got) == ["unigen", "builtin", "ethernet:aaaa-1", "tether:bbbb-2"]
    assert [(l["kind"], l["name"], l["index"], l["ip"], l["up"]) for l in got.values()] == [
        ("wifi", "Unigen dongle", 5, "192.168.1.5", True), ("wifi", "Built-in MediaTek", 7, "10.0.0.7", True),
        ("ethernet", "Ethernet", 20, "192.168.0.10", True), ("tether", "USB tethering (phone)", 21, "192.168.42.129", True)]
    assert got["tether:bbbb-2"]["detail"] == "Remote NDIS based Internet Sharing Device"


def test_scan_links_keeps_a_wifi_radio_that_is_off(monkeypatch):
    wifi_world(monkeypatch, [], radios={"unigen": {"guid": "u", "on": True}, "builtin": {"guid": "b", "on": False}})
    got = {l["key"]: l["up"] for l in merge.scan_links()}
    assert got == {"unigen": True, "builtin": False}  # still listed: the user can include it again


def test_scan_links_two_of_a_kind_get_told_apart(monkeypatch):
    wifi_world(monkeypatch, [adapter("a", "Realtek PCIe GbE", "Ethernet"), adapter("b", "Realtek USB GbE", "Ethernet 2")], radios={})
    assert [l["name"] for l in merge.scan_links()] == ["Ethernet · Ethernet", "Ethernet · Ethernet 2"]


def test_find_links_defaults_wifi_and_ethernet_in_tethering_out(monkeypatch):
    wifi_world(monkeypatch, [adapter("aaaa", "Realtek PCIe GbE"), adapter("bbbb", "Remote NDIS based Internet Sharing Device", index=21, ip="192.168.42.129")])
    assert sorted(merge.find_links()) == ["builtin", "ethernet:aaaa", "unigen"]  # tethering uses the phone's data: opt in
    assert sorted(merge.find_links({"tether:bbbb": True})) == ["builtin", "ethernet:aaaa", "tether:bbbb", "unigen"]
    assert sorted(merge.find_links({"builtin": False, "ethernet:aaaa": False})) == ["unigen"]
    assert merge.find_links({})["ethernet:aaaa"] == (20, "192.168.0.10")


def test_find_links_skips_links_that_are_down(monkeypatch):
    wifi_world(monkeypatch, [adapter("aaaa", "Realtek PCIe GbE", ip=None, up=False)], radios={"unigen": {"guid": "u", "on": False}})
    assert merge.find_links() == {}


def test_wired_links_for_the_sampler(monkeypatch):
    monkeypatch.setattr(merge, "adapters", lambda: [adapter("AAAA", "Realtek PCIe GbE"), adapter("BBBB", "Apple Mobile Device Ethernet", "Ethernet 2", ip="172.20.10.2")])
    assert merge.wired_links() == {"ethernet:aaaa": {"guid": "AAAA", "on": True, "name": "Ethernet", "kind": "ethernet"},
                                   "tether:bbbb": {"guid": "BBBB", "on": True, "name": "USB tethering (phone)", "kind": "tether"}}


def test_adapters_struct_layout():
    """iphlpapi.h IP_ADAPTER_ADDRESSES_LH on x64: the fields merge reads sit where Windows puts them."""
    off = lambda f: getattr(merge._ADAPTER, f).offset
    assert (off("Next"), off("AdapterName"), off("FirstUnicastAddress"), off("Description"), off("FriendlyName")) == (8, 16, 24, 64, 72)
    assert (off("IfType"), off("OperStatus"), off("FirstPrefix"), off("Luid")) == (100, 104, 176, 224)


def test_adapters_reads_this_pc():
    """A read-only call: every adapter Windows lists has the fields the links need."""
    rows = merge.adapters()
    assert rows and all(set(r) == {"guid", "index", "type", "up", "desc", "name", "ip"} and isinstance(r["index"], int) for r in rows)


def test_four_links_share_connections():
    p = pool("unigen", "builtin", "ethernet:x", "tether:y")
    assert sorted(p.pick().key for _ in range(8)) == ["builtin", "builtin", "ethernet:x", "ethernet:x", "tether:y", "tether:y", "unigen", "unigen"]
    p.sideline("tether:y")
    for l in p.links():
        l.active = 0
    assert {p.pick().key for _ in range(6)} == {"unigen", "builtin", "ethernet:x"}


def test_dial_fails_over_through_three_links(monkeypatch, resolve):
    p = pool("a", "b", "c")
    s = FakeSock()

    def open_on(link, addr, timeout=10.0):
        if link.key != "c":
            raise OSError(10051, "unreachable")
        return s
    monkeypatch.setattr(merge, "open_on", open_on)
    sock, link = asyncio.run(merge.dial(p, "example.com", 443))
    assert sock is s and link.key == "c" and [l.active for l in p.links()] == [0, 0, 1]


def test_usable_ipv4():
    assert [merge._usable(a) for a in ("192.168.1.5", "0.0.0.0", "127.0.0.1", "169.254.7.7", "10.0.0.1", "198.18.0.1", "198.19.255.1", "198.20.0.1")] == [
        True, False, False, False, True, False, False, True]  # 198.18.0.0/15 is where TUN VPNs put their fake addresses


def test_scan_links_skips_a_wired_adapter_with_a_fake_ip(monkeypatch):
    wifi_world(monkeypatch, [adapter("tun", "Realtek PCIe GbE", ip="198.18.0.1"), adapter("real", "Realtek PCIe GbE", "Ethernet 2", ip="192.168.0.10", index=21)], radios={})
    assert [l["key"] for l in merge.scan_links()] == ["ethernet:real"]


# ---- the Merger: pool upkeep, probes, status, the proxy thread ----
def lk(key, kind="wifi", up=True, ip=None, index=1, name=None):
    return {"key": key, "kind": kind, "name": name or key, "detail": "", "guid": key, "index": index, "ip": ip or f"10.0.0.{index}" if up else None, "up": up}


class Rig:
    """A Merger on fake scans, rates and probes; choices is the saved merge_links, change it between calls."""

    def __init__(self, monkeypatch, links, rates=None):
        self.links, self.choices, self.rates, self.verdict, self.now = links, {}, rates or {}, {}, 100.0
        monkeypatch.setattr(merge, "scan_links", lambda: self.links)
        monkeypatch.setattr(merge, "probe", lambda link: self.verdict.get(link.key, True))
        self.m = merge.Merger(rate=lambda k: self.rates.get(k), choices=lambda: self.choices, clock=lambda: self.now)

    def probe_all(self):
        self.m._probe_due(lambda f, *a: f(*a))  # in this thread


def test_merger_status_after_refresh(monkeypatch):
    r = Rig(monkeypatch, [lk("a", index=1), lk("b", index=2)], rates={"a": (4e6, 1e5), "b": (2e6, 1e5)})
    r.m.refresh()
    for l in r.m.pool.links():
        l.active = 1  # busy links follow the peaks exactly
    r.m.refresh()
    assert {l.key: l.weight for l in r.m.pool.links()} == {"a": 1.0, "b": 0.5}


def test_refresh_follows_the_choices_and_the_adapters(monkeypatch):
    r = Rig(monkeypatch, [lk("unigen", index=1), lk("builtin", index=2), lk("ethernet:x", "ethernet", index=3), lk("tether:y", "tether", index=4),
                          lk("gone", up=False, index=5)])
    r.m.refresh()
    assert sorted(l.key for l in r.m.pool.links()) == ["builtin", "ethernet:x", "unigen"]  # tethering is out until included, a down link never in
    r.choices.update({"tether:y": True, "builtin": False})
    r.m.refresh()
    assert sorted(l.key for l in r.m.pool.links()) == ["ethernet:x", "tether:y", "unigen"]
    r.links = [lk("unigen", index=1)]  # the cable is pulled, the phone unplugged, the card gone
    r.m.refresh()
    assert [l.key for l in r.m.pool.links()] == ["unigen"]


def test_probes_mark_links_and_come_round_again(monkeypatch):
    r = Rig(monkeypatch, [lk("a", index=1), lk("b", index=2)])
    r.verdict["a"] = False
    r.m.refresh()
    r.probe_all()
    assert {l.key: l.state for l in r.m.pool.links()} == {"a": "down", "b": "up"}
    r.verdict["a"] = True
    r.now += merge.PROBE_DOWN - 0.5
    r.probe_all()
    assert r.m.pool.links()[0].state == "down"  # not due yet
    r.now += 1.0
    r.probe_all()
    assert r.m.pool.links()[0].state == "up"  # a down link is looked at again after 4 s
    r.verdict["b"] = False
    r.now += merge.PROBE_UP - 5.0
    r.probe_all()
    assert r.m.pool.links()[1].state == "up"  # an up one only after 15 s from its last probe
    r.now += 5.0
    r.probe_all()
    assert r.m.pool.links()[1].state == "down"


def test_status_lists_every_link_with_what_the_card_needs(monkeypatch):
    r = Rig(monkeypatch, [lk("unigen", index=1, name="Unigen dongle"), lk("builtin", index=2, up=False), lk("ethernet:x", "ethernet", index=3),
                          lk("tether:y", "tether", index=4)], rates={"unigen": (3e6, 2e5), "ethernet:x": (1e6, 1e4)})
    r.m.refresh()
    r.probe_all()
    r.m.pool.links()[0].active = 2
    got = {s["key"]: s for s in r.m.status()}
    assert list(got) == ["unigen", "builtin", "ethernet:x", "tether:y"]
    u = got["unigen"]
    assert (u["kind"], u["name"], u["ip"], u["online"], u["included"], u["state"], u["active"]) == ("wifi", "Unigen dongle", "10.0.0.1", True, True, "up", 2)
    assert (u["down"], u["up"]) == (3e6, 2e5) and got["builtin"]["down"] is None
    assert (got["builtin"]["online"], got["builtin"]["state"]) == (False, "down")  # included, no address
    assert (got["tether:y"]["included"], got["tether:y"]["state"], got["tether:y"]["online"]) == (False, "off", True)
    r.choices["ethernet:x"] = False
    assert {s["key"]: s["state"] for s in r.m.status()}["ethernet:x"] == "off"


def test_status_when_stopped_still_lists_the_links(monkeypatch):
    r = Rig(monkeypatch, [lk("unigen", index=1), lk("tether:y", "tether", index=4)])
    assert r.m.port is None
    got = {s["key"]: s["state"] for s in r.m.status()}
    assert got == {"unigen": "checking", "tether:y": "off"}  # nothing is measured while merge is off
    r.links = []
    assert r.m.status() == []
    monkeypatch.setattr(merge, "scan_links", lambda: (_ for _ in ()).throw(OSError("no")))
    r.m._links = [lk("unigen")]
    assert [s["key"] for s in r.m.status()] == ["unigen"]  # a failing look keeps the last list


def test_start_serves_a_port_and_stop_is_idempotent(monkeypatch):
    r = Rig(monkeypatch, [lk("a", index=1)])
    port = r.m.start()
    try:
        assert isinstance(port, int) and port > 0 and r.m.port == port and r.m.start() == port
        assert [l.key for l in r.m.pool.links()] == ["a"]  # the first look is taken before start returns
        with socket.create_connection(("127.0.0.1", port), 2) as c:
            c.sendall(b"GET /proxy.pac HTTP/1.1\r\nHost: x\r\n\r\n")
            assert f"127.0.0.1:{port}".encode() in c.recv(4096)
    finally:
        r.m.stop()
    r.m.stop()
    assert r.m.port is None
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), 1).close()
    assert isinstance(r.m.start(), int)  # and again
    r.m.stop()


def test_start_survives_a_failing_first_look(monkeypatch):
    r = Rig(monkeypatch, [])
    monkeypatch.setattr(merge, "scan_links", lambda: (_ for _ in ()).throw(wifi.WifiError("Couldn't list the Wi-Fi adapters.")))
    assert isinstance(r.m.start(), int)  # the next refresh tries again
    r.m.stop()


def test_loop_uses_a_64_thread_pool_and_stop_shuts_it_down(monkeypatch):
    """Each connection's connect and DNS lookup holds a thread while it waits: the default pool is too small for a browser."""
    r = Rig(monkeypatch, [lk("a", index=1)])
    r.m.start()
    ex = r.m._loop._default_executor
    try:
        assert isinstance(ex, concurrent.futures.ThreadPoolExecutor) and ex._max_workers == 64 and ex._thread_name_prefix == "merge"
    finally:
        r.m.stop()
    assert ex._shutdown


def test_second_start_while_running_makes_no_second_loop(monkeypatch):
    r = Rig(monkeypatch, [lk("a", index=1)])
    real = merge.scan_links
    monkeypatch.setattr(merge, "scan_links", lambda: time.sleep(0.2) or real())  # so the starts overlap
    threads = lambda: [t for t in threading.enumerate() if t.name == "merge"]
    results = []
    ts = [threading.Thread(target=lambda: results.append(r.m.start())) for _ in range(4)]
    try:
        [t.start() for t in ts]
        [t.join(10) for t in ts]
        assert len(results) == 4 and len(set(results)) == 1 and results[0] == r.m.port
        assert len(threads()) == 1
    finally:
        r.m.stop()


def test_stop_during_start_leaves_it_stopped(monkeypatch):
    r = Rig(monkeypatch, [lk("a", index=1)])
    inside, go = threading.Event(), threading.Event()
    real = merge.scan_links

    def slow():
        inside.set()
        go.wait(5)
        return real()
    monkeypatch.setattr(merge, "scan_links", slow)
    errs = []

    def starter():
        try:
            r.m.start()
        except OSError as e:
            errs.append(e)
    a = threading.Thread(target=starter)
    a.start()
    assert inside.wait(5)
    b = threading.Thread(target=r.m.stop)
    b.start()
    while not r.m._stopping:  # stop() has been asked for; start() is still looking at the adapters
        time.sleep(0.01)
    go.set()
    a.join(10), b.join(10)
    assert r.m.port is None and r.m._thread is None and errs
    assert not [t for t in threading.enumerate() if t.name == "merge"]
