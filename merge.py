"""Merge connections: new connections are spread across the Wi-Fi adapters that have an address. This is the pool of links
and the scheduler that picks one for each new connection (the dialer and the proxy build on it)."""
import random, threading, time
from dataclasses import dataclass

COOLDOWN = 15.0     # seconds a link that just failed to connect is left out
PEAK_DECAY = 0.97   # a link's remembered peak rate shrinks by this each tick without traffic
WEIGHT_FLOOR = 0.05  # a slow link still gets a trickle, never zero
_TIERS = {"up": 0, "unknown": 1, "down": 2}


@dataclass
class Link:
    key: str
    index: int            # the adapter's interface index (what IP_UNICAST_IF takes)
    ip: str
    active: int = 0       # connections open on it now
    state: str = "unknown"  # "up", "unknown" or "down": the last probe's verdict
    until: float = 0.0    # sidelined until this clock time
    peak: float = 0.0     # best recent bytes/s
    weight: float = 1.0   # share of new connections, from peak / the best peak
    opened: int = 0       # connections opened on it, ever


class Pool:
    """Every call takes one lock: the asyncio thread and the probe thread both come in."""

    def __init__(self, clock=time.monotonic, rand=random.random):
        self._clock, self._rand, self._lock, self._links = clock, rand, threading.Lock(), {}

    def update(self, found):
        """found: {key: (index, ip)}. New keys are added, known ones get the new address (counts kept), missing ones go."""
        with self._lock:
            self._links = {k: self._links[k] if k in self._links else Link(k, i, ip) for k, (i, ip) in found.items()}
            for k, (i, ip) in found.items():
                self._links[k].index, self._links[k].ip = i, ip

    def pick(self, exclude=frozenset()):
        """The link for a new connection (its `active` already counts it), or None when none is left to try.
        Best state first, sidelined links skipped unless all are, then the lowest (active + 1) / weight."""
        with self._lock:
            now, cands = self._clock(), [l for l in self._links.values() if l.key not in exclude]
            cands = [l for l in cands if l.until <= now] or cands  # never refuses while a link exists
            if not cands:
                return None
            best = min(_TIERS[l.state] for l in cands)
            cands = [l for l in cands if _TIERS[l.state] == best]
            start = int(self._rand() * len(cands)) % len(cands)  # ties: the first minimum after a random start
            link = min(cands[start:] + cands[:start], key=lambda l: (l.active + 1) / max(l.weight, WEIGHT_FLOOR))
            link.active += 1
            link.opened += 1
            return link

    def release(self, link):
        with self._lock:
            link.active = max(0, link.active - 1)

    def sideline(self, key):
        with self._lock:
            if key in self._links:
                self._links[key].until = self._clock() + COOLDOWN

    def mark(self, key, ok):
        with self._lock:
            if key in self._links:
                self._links[key].state = "up" if ok else "down"

    def observe(self, key, bytes_per_s):
        """One tick of traffic for a link (0 when idle): its peak decays, then every weight is its peak over the best peak."""
        with self._lock:
            if key not in self._links:
                return
            l = self._links[key]
            l.peak = max(bytes_per_s, l.peak * PEAK_DECAY)
            top = max(x.peak for x in self._links.values())
            for x in self._links.values():
                x.weight = max(WEIGHT_FLOOR, x.peak / top) if top else 1.0

    def links(self):
        with self._lock:
            return list(self._links.values())
