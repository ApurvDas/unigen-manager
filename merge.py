"""Merge connections: new connections are spread across the Wi-Fi adapters that have an address. This is the pool of links
and the scheduler that picks one for each new connection (the dialer and the proxy build on it)."""
import asyncio, ctypes, random, socket, struct, threading, time
from ctypes import wintypes
from dataclasses import dataclass

import traffic, wifi

COOLDOWN = 15.0     # seconds a link that just failed to connect is left out
PEAK_DECAY = 0.97   # a link's remembered peak rate shrinks by this each tick without traffic
WEIGHT_FLOOR = 0.05  # a slow link still gets a trickle, never zero
DRIFT = 0.1         # an idle link's weight climbs this much per tick, so a link at the floor gets picked and measured again
IP_UNICAST_IF = 31  # winsock option: send out of this interface index (IPv4 wants it in network byte order)
PROBE_TARGETS = (("1.1.1.1", 443), ("8.8.8.8", 443))  # a link is up when it can open a connection to one of these
PROBE_UP = 15.0     # seconds between probes of a link that was last up
PROBE_DOWN = 4.0    # ... and of one that was last down, so it comes back quickly
REFRESH = 3.0       # seconds between re-reads of which adapters have an address
FAILOVER = {10049, 10050, 10051, 10060, 10065}  # winsock: bad address, net down, net unreachable, timed out, host unreachable
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
        """One tick of traffic for a link (0 when idle): its peak decays, then every weight is its peak over the best peak.
        A link with nothing open never loses weight, and gains DRIFT on its own tick (up to 1.0)."""
        with self._lock:
            if key not in self._links:
                return
            l = self._links[key]
            l.peak = max(bytes_per_s, l.peak * PEAK_DECAY)
            top = max(x.peak for x in self._links.values())
            for x in self._links.values():
                w = max(WEIGHT_FLOOR, x.peak / top) if top else 1.0
                if x.active == 0:  # ponytail: idle weights only ever rise; a real slow link is re-measured as soon as it is picked
                    w = max(w, min(1.0, x.weight + DRIFT) if x is l else x.weight)
                x.weight = w

    def links(self):
        with self._lock:
            return list(self._links.values())


class DialError(Exception):
    """code is the SOCKS5 reply code to send back: 3 network unreachable, 4 host unreachable, 5 refused."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _ADDRROW(ctypes.Structure):  # MIB_IPADDRROW
    _fields_ = [("dwAddr", wintypes.DWORD), ("dwIndex", wintypes.DWORD), ("dwMask", wintypes.DWORD),
                ("dwBCastAddr", wintypes.DWORD), ("dwReasmSize", wintypes.DWORD), ("unused1", wintypes.WORD), ("wType", wintypes.WORD)]


def ipv4_by_index():
    """{interface index: IPv4 address} from Windows' address table; 0.0.0.0, loopback and link-local (169.254) are left out."""
    ip = ctypes.WinDLL("iphlpapi")
    ip.GetIpAddrTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG), wintypes.BOOL]
    size = wintypes.ULONG(0)
    ip.GetIpAddrTable(None, ctypes.byref(size), False)  # the first call only says how big the table is
    buf = ctypes.create_string_buffer(size.value)
    if ip.GetIpAddrTable(buf, ctypes.byref(size), False):
        raise OSError("GetIpAddrTable failed")
    n = wintypes.DWORD.from_buffer(buf).value
    out = {}
    for r in (_ADDRROW * n).from_buffer(buf, 4):
        a = socket.inet_ntoa(struct.pack("<I", r.dwAddr))  # dwAddr is network byte order, read here as a little-endian int
        if a != "0.0.0.0" and not a.startswith(("127.", "169.254.")):
            out.setdefault(r.dwIndex, a)
    return out


def find_links():
    """{key: (interface index, IPv4)} for each Wi-Fi radio that is on and has an address. Raises wifi.WifiError / OSError."""
    addrs, found = ipv4_by_index(), {}
    for key, r in wifi.radios().items():
        if not r["on"]:
            continue
        try:
            i = traffic.if_index(r["guid"])
        except OSError:
            continue
        if i in addrs:
            found[key] = (i, addrs[i])
    return found


def open_on(link, addr, timeout=10.0):
    """A connected, blocking socket to addr that leaves through this link's adapter: pinned to its interface and its address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack(">I", link.index))
        s.bind((link.ip, 0))
        s.settimeout(timeout)
        s.connect(addr)
        s.settimeout(None)
        return s
    except BaseException:
        s.close()
        raise


def probe(link):
    """True when the link can open a connection to a probe target (3 s each, first success wins)."""
    for addr in PROBE_TARGETS:
        try:
            open_on(link, addr, 3.0).close()
            return True
        except OSError:
            pass
    return False


def _failover(e):
    return isinstance(e, (TimeoutError, socket.timeout)) or (getattr(e, "winerror", None) or e.errno) in FAILOVER


async def dial(pool, host, port):
    """(connected non-blocking socket, its link), with the link's `active` still counted: the caller releases it when the
    connection ends. Tries links best first; one that fails to connect is sidelined and the next is tried."""
    loop = asyncio.get_running_loop()
    try:
        addr = (await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM))[0][4]
    except (socket.gaierror, IndexError):
        raise DialError(4) from None
    tried = set()
    for _ in pool.links():
        link = pool.pick(exclude=tried)
        if link is None:
            break
        tried.add(link.key)
        try:
            sock = await loop.run_in_executor(None, open_on, link, addr)
        except OSError as e:
            pool.release(link)
            if not _failover(e):
                raise DialError(5) from None
            pool.sideline(link.key)
            continue
        except BaseException:  # cancelled while connecting: don't leave it counted
            pool.release(link)
            raise
        sock.setblocking(False)
        return sock, link
    raise DialError(3)
