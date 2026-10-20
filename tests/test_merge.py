import pytest

import merge


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
    p.observe("a", 10e6); p.observe("b", 5e6)
    a, b = p.links()
    assert (a.weight, b.weight) == (1.0, 0.5)
    p.observe("b", 0)
    assert b.peak == pytest.approx(5e6 * 0.97)
    for _ in range(500):
        p.observe("b", 0)
    assert b.weight == 0.05
    q = pool("a", "b")
    q.observe("a", 0)
    assert [l.weight for l in q.links()] == [1.0, 1.0]
