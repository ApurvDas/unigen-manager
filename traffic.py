"""Live traffic of the Wi-Fi adapters, Ethernet and a phone tethered over USB: Windows' own byte counters per adapter (iphlpapi, milliseconds, no netsh), sampled once a second.
The sampler keeps each adapter's rate, the last minute and today's totals (saved per day in traffic.json, 30 days)."""
import ctypes, datetime, json, logging, os, threading, time, uuid
from collections import deque
from ctypes import wintypes
from pathlib import Path

import wifi

log = logging.getLogger("unigen")
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "UnigenManager"
TICK = 1.0         # seconds between samples
HISTORY = 60       # samples kept per adapter: the chart's last minute
KEEP_DAYS = 30     # days of totals kept in traffic.json
SAVE_EVERY = 30.0  # seconds between writes of traffic.json (and one on exit)
MAP_EVERY = 10.0   # seconds between re-reads of the adapter GUIDs, so a dongle or a cable plugged or pulled is followed
UNITS = ("bytes", "bits")
_ORDER = ["unigen", "builtin"]


# ---- Windows' counters ----
_IF_MAX_STRING = 257  # IF_MAX_STRING_SIZE + 1
_IF_MAX_PHYS = 32     # IF_MAX_PHYS_ADDRESS_LENGTH


class MIB_IF_ROW2(ctypes.Structure):
    """netioapi.h, field for field (1352 bytes on x64: tests/test_traffic.py checks the size and the offsets)."""
    _fields_ = [
        ("InterfaceLuid", ctypes.c_uint64), ("InterfaceIndex", wintypes.ULONG), ("InterfaceGuid", ctypes.c_ubyte * 16),
        ("Alias", ctypes.c_wchar * _IF_MAX_STRING), ("Description", ctypes.c_wchar * _IF_MAX_STRING),
        ("PhysicalAddressLength", wintypes.ULONG), ("PhysicalAddress", ctypes.c_ubyte * _IF_MAX_PHYS),
        ("PermanentPhysicalAddress", ctypes.c_ubyte * _IF_MAX_PHYS),
        ("Mtu", wintypes.ULONG), ("Type", wintypes.ULONG), ("TunnelType", wintypes.ULONG), ("MediaType", wintypes.ULONG),
        ("PhysicalMediumType", wintypes.ULONG), ("AccessType", wintypes.ULONG), ("DirectionType", wintypes.ULONG),
        ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),  # eight 1-bit BOOLEANs: one byte
        ("OperStatus", wintypes.ULONG), ("AdminStatus", wintypes.ULONG), ("MediaConnectState", wintypes.ULONG),
        ("NetworkGuid", ctypes.c_ubyte * 16), ("ConnectionType", wintypes.ULONG),
        ("TransmitLinkSpeed", ctypes.c_uint64), ("ReceiveLinkSpeed", ctypes.c_uint64),
        ("InOctets", ctypes.c_uint64), ("InUcastPkts", ctypes.c_uint64), ("InNUcastPkts", ctypes.c_uint64),
        ("InDiscards", ctypes.c_uint64), ("InErrors", ctypes.c_uint64), ("InUnknownProtos", ctypes.c_uint64),
        ("InUcastOctets", ctypes.c_uint64), ("InMulticastOctets", ctypes.c_uint64), ("InBroadcastOctets", ctypes.c_uint64),
        ("OutOctets", ctypes.c_uint64), ("OutUcastPkts", ctypes.c_uint64), ("OutNUcastPkts", ctypes.c_uint64),
        ("OutDiscards", ctypes.c_uint64), ("OutErrors", ctypes.c_uint64), ("OutUcastOctets", ctypes.c_uint64),
        ("OutMulticastOctets", ctypes.c_uint64), ("OutBroadcastOctets", ctypes.c_uint64), ("OutQLen", ctypes.c_uint64),
    ]


_ip = None


def _iphlpapi():
    global _ip
    if _ip is None:
        _ip = ctypes.WinDLL("iphlpapi")
        _ip.ConvertInterfaceGuidToLuid.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]
        _ip.GetIfEntry2.argtypes = [ctypes.POINTER(MIB_IF_ROW2)]
        _ip.ConvertInterfaceGuidToLuid.restype = _ip.GetIfEntry2.restype = wintypes.ULONG
    return _ip


def _row(guid):
    """The adapter's MIB_IF_ROW2 (GUID -> LUID -> GetIfEntry2). Raises OSError when Windows can't answer."""
    try:
        g = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
    except (ValueError, AttributeError, TypeError) as e:
        raise OSError(f"bad adapter GUID {guid!r}") from e
    ip, row, luid = _iphlpapi(), MIB_IF_ROW2(), ctypes.c_uint64()
    rc = ip.ConvertInterfaceGuidToLuid(ctypes.byref(g), ctypes.byref(luid))
    if rc:
        raise OSError(f"ConvertInterfaceGuidToLuid failed (error {rc})")
    row.InterfaceLuid = luid.value  # GetIfEntry2 finds the row by its LUID (or its index)
    rc = ip.GetIfEntry2(ctypes.byref(row))
    if rc:
        raise OSError(f"GetIfEntry2 failed (error {rc})")
    return row


def counters(guid):
    """(bytes received, bytes sent) since the adapter came up. Raises OSError when Windows can't answer; tests replace this."""
    row = _row(guid)
    return row.InOctets, row.OutOctets


def if_index(guid):
    """The adapter's interface index (what IP_UNICAST_IF and GetIpAddrTable use). Raises OSError like counters."""
    return _row(guid).InterfaceIndex


# ---- showing a rate (the page has the same in shared.js: fmtRate) ----
def rate_parts(bytes_per_s, unit):
    """("4.2", "MB/s"): KB or MB picked by size, decimal (1 MB/s = 8 Mbps); KB/Kbps whole, MB/Mbps one decimal."""
    v, (small, big) = bytes_per_s * (8 if unit == "bits" else 1), ("Kbps", "Mbps") if unit == "bits" else ("KB/s", "MB/s")
    return (str(round(v / 1e3)), small) if v < 999_500 else (f"{v / 1e6:.1f}", big)


def fmt_rate(bytes_per_s, unit):
    return " ".join(rate_parts(bytes_per_s, unit))


# ---- the saved totals ----
def _today():
    return datetime.date.today().isoformat()


def _now():
    return time.monotonic()


def _prune(days):
    for d in sorted(days)[:-KEEP_DAYS]:
        del days[d]


def _count(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def _load(path):
    """{"YYYY-MM-DD": {key: {"down", "up"}}} from traffic.json; anything unreadable or malformed is dropped, never raised."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    days = {}
    for day, per in (raw.items() if isinstance(raw, dict) else ()):
        try:
            datetime.date.fromisoformat(day)
        except (TypeError, ValueError):
            continue
        for key, t in (per.items() if isinstance(per, dict) else ()):
            down, up = (_count(t.get(k)) for k in ("down", "up")) if isinstance(t, dict) else (None, None)
            if down is not None and up is not None:
                days.setdefault(day, {})[key] = {"down": down, "up": up}
    _prune(days)
    return days


class Sampler:
    """One daemon thread, one tick a second while the app runs (windows open or not), because the tray tooltip and the totals
    need it. Never raises into the app and never calls netsh: wifi.radios() is the WLAN API."""

    def __init__(self, path=None, extra=None):
        """extra: a callable like merge.wired_links, {key: {"guid", "on", "name", "kind"}} for the links beyond Wi-Fi."""
        self._path, self._extra = Path(path or DATA_DIR / "traffic.json"), extra or (lambda: {})
        self._lock, self._stop, self._thread = threading.Lock(), threading.Event(), None
        self._map, self._map_at = {}, None   # key -> {"guid", "on"} (and "name", "kind" beyond Wi-Fi), and when it was read
        self._ad = {}                        # key -> {"prev": (in, out, t) | None, "rate": (down, up) | None, "hist": deque}
        self._days, self._day = _load(self._path), _today()
        self._saved_at, self._dirty, self._failing, self._ticks = _now(), False, False, 0

    # -- one sample --
    def _refresh_map(self, now):
        if self._map_at is not None and now - self._map_at < MAP_EVERY:
            return
        self._map_at = now
        old = self._map
        try:
            new = {k: {"guid": r["guid"], "on": r["on"]} for k, r in wifi.radios().items()}
        except (wifi.WifiError, OSError) as e:
            log.debug("traffic: couldn't list the Wi-Fi adapters (%s); keeping the last list", e)
            new = {k: v for k, v in old.items() if "kind" not in v}
        try:
            new.update(self._extra())
        except (wifi.WifiError, OSError) as e:
            log.debug("traffic: couldn't list Ethernet and tethering (%s); keeping the last list", e)
            new.update({k: v for k, v in old.items() if "kind" in v})
        self._map = new

    def tick(self):
        now, day = _now(), _today()
        self._refresh_map(now)
        with self._lock:
            keys = dict(self._map)
            if day != self._day:  # local midnight: a new day starts counting from zero
                self._day = day
                self._days.setdefault(day, {})
                _prune(self._days)
                self._dirty = True
        reads = {}
        for key, info in keys.items():
            try:
                reads[key] = counters(info["guid"])
            except OSError as e:  # unplugged between two ticks, or Windows has no counters for it right now
                log.debug("traffic: no counters for %s (%s)", key, e)
        with self._lock:
            self._ticks += 1
            for key in [k for k in self._ad if k not in reads]:
                del self._ad[key]  # gone: it starts again from nothing, without a rate, when it is back
            for key, cur in reads.items():
                self._add(key, cur, now, day)
        if now - self._saved_at >= SAVE_EVERY:
            self.save()

    def _add(self, key, cur, now, day):
        a = self._ad.setdefault(key, {"prev": None, "rate": None, "hist": deque(maxlen=HISTORY)})
        prev, a["prev"] = a["prev"], (cur[0], cur[1], now)
        if prev is None or now <= prev[2]:
            return  # the first sample has no rate
        down, up = max(0, cur[0] - prev[0]), max(0, cur[1] - prev[1])  # a counter that went back (reset, re-plug) counts as 0
        dt = now - prev[2]
        a["rate"] = (down / dt, up / dt)
        a["hist"].append([round(down / dt), round(up / dt)])
        t = self._days.setdefault(day, {}).setdefault(key, {"down": 0, "up": 0})
        t["down"] += down
        t["up"] += up
        self._dirty = True

    # -- reading it --
    def rate(self, key):
        """(down, up) bytes per second, or None while the adapter is absent or still being measured."""
        with self._lock:
            a = self._ad.get(key)
            return a["rate"] if a else None

    def radios(self):
        """{key: radio is on} for every adapter in the map (a wired link is on while it is up)."""
        with self._lock:
            return {k: v["on"] for k, v in self._map.items()}

    def snapshot(self):
        with self._lock:
            keys = sorted(self._map, key=lambda k: (_ORDER.index(k) if k in _ORDER else len(_ORDER), k))
            adapters = [{"key": k, "name": self._map[k].get("name") or wifi.ADAPTER_NAMES.get(k, k), "kind": self._map[k].get("kind", "wifi"),
                         "down": None if not self._ad.get(k, {}).get("rate") else round(self._ad[k]["rate"][0]),
                         "up": None if not self._ad.get(k, {}).get("rate") else round(self._ad[k]["rate"][1]),
                         "history": [list(h) for h in self._ad[k]["hist"]] if k in self._ad else []} for k in keys]
            today = {k: {"down": 0, "up": 0} for k in keys}
            today.update({k: dict(t) for k, t in self._days.get(self._day, {}).items()})
            return {"adapters": adapters, "today": today, "tick": self._ticks}

    # -- keeping it --
    def save(self):
        with self._lock:
            if not self._dirty:
                return
            data, self._dirty, self._saved_at = json.dumps(self._days), False, _now()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.warning("traffic: couldn't save %s: %s", self._path, e)
            self._dirty = True

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="traffic")
        self._thread.start()

    def _run(self):
        while True:
            try:
                self.tick()
                self._failing = False
            except Exception:  # the sampler must never take the app down: log the first failure of a run, keep going
                if not self._failing:
                    log.exception("traffic: a sample failed")
                self._failing = True
            if self._stop.wait(TICK):
                return

    def stop(self):
        """Stop the thread and write the totals. Safe to call more than once."""
        self._stop.set()
        t = self._thread
        if t and t is not threading.current_thread():
            t.join(2)
        self.save()
