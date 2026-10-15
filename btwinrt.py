"""Bluetooth through Windows' device APIs (WinRT): paired devices, live search, pairing with PIN prompts,
unpairing and the radio's on/off switch. bt.py is the only caller. The pure helpers at the top test without hardware."""
import asyncio, logging, re, threading

from winrt.windows.devices.enumeration import (DeviceInformation, DeviceInformationKind, DevicePairingKinds,
                                               DevicePairingProtectionLevel)
from winrt.windows.devices.bluetooth import BluetoothAdapter, BluetoothDevice, BluetoothLEDevice
from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioKind, RadioState
from winrt.windows.foundation import IPropertyValue, PropertyType

log =logging.getLogger("unigen")


class BtError(Exception):
    pass


def kind(major, minor):
    """Classic Bluetooth class of device -> what the row says."""
    minor = minor or 0
    if major == 4:
        if minor in (14, 15):
            return "TV"
        return "Headphones" if minor in (1, 2, 6) else "Speaker" if minor in (5, 7, 8, 10) else "Audio"
    if major == 5:
        if (minor & 0x0F) in (1, 2):
            return "Controller"
        return {0x10: "Keyboard", 0x20: "Mouse", 0x30: "Keyboard"}.get(minor & 0x30, "Input device")
    return {1: "Computer", 2: "Phone", 7: "Wearable"}.get(major, "Device")


def le_kind(appearance):
    """Bluetooth LE GAP appearance -> what the row says (category = top 10 bits, subcategory = low 6)."""
    if not appearance:
        return "Device"
    cat, sub = appearance >> 6, appearance & 0x3F
    if cat == 15:
        return {1: "Keyboard", 2: "Mouse", 3: "Controller", 4: "Controller"}.get(sub, "Input device")
    return {1: "Phone", 2: "Computer", 3: "Wearable", 5: "TV", 10: "Audio", 33: "Speaker", 37: "Headphones"}.get(cat, "Device")


def record_kind(r):
    return kind(r["major"], r["minor"]) if r["major"] is not None else le_kind(r["appearance"])


def radio_of(dev_id):
    """The address (12 lowercase hex) of the PC's radio a paired device's id belongs to, or None.
    Ids look like Bluetooth#Bluetooth<radio>-<device> and BluetoothLE#BluetoothLE<radio>-<device>."""
    m = re.match(r"Bluetooth(?:LE)?#Bluetooth(?:LE)?([0-9A-Fa-f:]{17})-", dev_id)
    return m.group(1).replace(":", "").lower() if m else None


def merge(records, local=None):
    """One row per device. A device's classic and LE records (same name) become one row that keeps every id;
    the classic record leads (audio and re-pairing need its address), the one on the radio in use (local) first,
    then the connected one.
    A row is "here" when audio can work on local: its classic record is on local, or, for an LE-only device, any record
    is. Earbuds whose LE record is on local but classic record on the other radio are not here: they need a re-pair.
    With no local radio every row is here.
    ponytail: matching by name merges two different devices that share a name; random LE addresses leave nothing better."""
    rows, on_local = {}, {}  # on_local[key] = {False: classic on local, True: LE on local} as seen so far
    for r in sorted(records, key=lambda r: (r["le"], local is not None and r["radio"] != local, not r["connected"])):
        key = r["name"] or r["id"]
        k = record_kind(r)
        row = rows.get(key)
        if row is None:
            row = rows[key] = {"id": r["id"], "ids": [r["id"]], "name": r["name"] or f"Unknown device {r['address'][-4:]}",
                               "kind": k, "connected": r["connected"], "address": r["address"], "classic": not r["le"]}
        else:
            row["ids"].append(r["id"])
            row["connected"] = row["connected"] or r["connected"]
            if row["kind"] == "Device":
                row["kind"] = k
        seen = on_local.setdefault(key, {False: False, True: False})
        seen[r["le"]] = seen[r["le"]] or r["radio"] == local
    for key, row in rows.items():
        seen, classic = on_local[key], row.pop("classic")
        row["here"] = local is None or (seen[False] if classic else seen[True])
    return sorted(rows.values(), key=lambda row: row["name"].lower())


def nearby_rows(records):
    """Search results: devices really in range, with a name (Windows Settings hides nameless beacons too)."""
    return merge([r for r in records if r["present"] and r["name"]])


_REFUSED = "The device refused. Put it in pairing mode, and disconnect it from your phone first."
_NO_ANSWER = "The device didn't answer. Bring it closer and make sure it's in pairing mode."
_CANCELLED = "Pairing cancelled."
_MESSAGES = {
    "AUTHENTICATION_FAILURE": _REFUSED, "CONNECTION_REJECTED": _REFUSED, "REMOTE_DEVICE_HAS_ASSOCIATION": _REFUSED,
    "NOT_READY_TO_PAIR": _REFUSED,
    "AUTHENTICATION_TIMEOUT": _NO_ANSWER, "HARDWARE_FAILURE": _NO_ANSWER, "FAILED": _NO_ANSWER,
    "NO_SUPPORTED_PROFILES": _NO_ANSWER, "NOT_PAIRED": _NO_ANSWER,
    "REJECTED_BY_HANDLER": _CANCELLED, "PAIRING_CANCELED": _CANCELLED,
    "AUTHENTICATION_NOT_ALLOWED": "Wrong PIN. Try again.", "INVALID_CEREMONY_DATA": "Wrong PIN. Try again.",
    "OPERATION_ALREADY_IN_PROGRESS": "Windows is already pairing a device. Wait a moment and try again.",
    "TOO_MANY_CONNECTIONS": "Too many devices are connected. Disconnect one and try again.",
    "ACCESS_DENIED": "Windows didn't allow the pairing.",
}


def pair_message(status):
    return _MESSAGES.get(status, f"Pairing failed ({status.replace('_', ' ').lower()}).")


def answer(kind, pin, ask):
    """What to tell Windows for one pairing request: (accept, pin_to_send).
    kind None = confirm only (the Pair click was the consent); ask(kind, pin) -> (accepted, typed) shows the page prompt."""
    if kind is None:
        return True, None
    ok, typed = ask(kind, pin)
    if not ok:
        return False, None
    if kind == "provide":
        typed = (typed or "").strip()
        return (True, typed) if typed else (False, None)
    return True, None


# ---- Windows calls ----
_CLASSIC, _LE = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}", "{bb7bb05e-5972-42b5-94fc-76eaa7084d49}"
_P = "System.Devices.Aep."
PROPS = [_P + n for n in ("IsPresent", "IsConnected", "DeviceAddress", "Bluetooth.Cod.Major", "Bluetooth.Cod.Minor",
                          "Bluetooth.Le.Appearance")]
_AEP = DeviceInformationKind.ASSOCIATION_ENDPOINT
_GET = {PropertyType.BOOLEAN: "get_boolean", PropertyType.STRING: "get_string", PropertyType.UINT8: "get_uint8",
        PropertyType.UINT16: "get_uint16", PropertyType.UINT32: "get_uint32", PropertyType.INT16: "get_int16",
        PropertyType.INT32: "get_int32"}
_KINDS = {DevicePairingKinds.CONFIRM_PIN_MATCH: "confirm", DevicePairingKinds.DISPLAY_PIN: "display",
          DevicePairingKinds.PROVIDE_PIN: "provide"}
_ALL_KINDS = (DevicePairingKinds.CONFIRM_ONLY | DevicePairingKinds.CONFIRM_PIN_MATCH | DevicePairingKinds.DISPLAY_PIN
              | DevicePairingKinds.PROVIDE_PIN)
_pair_lock, _search_lock, _search = threading.Lock(), threading.Lock(), None


def aqs(paired):
    """Bluetooth and Bluetooth LE association endpoints, paired or not."""
    return (f'(System.Devices.Aep.ProtocolId:="{_CLASSIC}" OR System.Devices.Aep.ProtocolId:="{_LE}") AND '
            f'System.Devices.Aep.IsPaired:=System.StructuredQueryType.Boolean#{"True" if paired else "False"}')


def _value(obj):
    if obj is None:
        return None
    p = obj.as_(IPropertyValue)
    get = _GET.get(p.type)
    return getattr(p, get)() if get else None


def record(di):
    """A DeviceInformation as a plain dict; everything after this point tests without Bluetooth."""
    props = di.properties
    v = lambda n: _value(props.lookup(_P + n)) if props.has_key(_P + n) else None
    return {"id": di.id, "name": (di.name or "").strip(), "le": di.id.startswith("BluetoothLE#"),
            "present": bool(v("IsPresent")), "connected": bool(v("IsConnected")),
            "address": (v("DeviceAddress") or "").replace(":", "").upper(), "radio": radio_of(di.id),
            "major": v("Bluetooth.Cod.Major"), "minor": v("Bluetooth.Cod.Minor"), "appearance": v("Bluetooth.Le.Appearance")}


def local_address():
    """The radio in use, as 12 lowercase hex digits (None when there is none)."""
    async def go():
        a = await BluetoothAdapter.get_default_async()
        return a and format(a.bluetooth_address, "012x")
    try:
        return asyncio.run(go())
    except OSError:
        return None


def here_id(address_hex):
    """The id of a device as the radio in use sees it: what pair() needs to pair it with this radio."""
    async def go():
        d = await BluetoothDevice.from_bluetooth_address_async(int(address_hex, 16))
        return d and d.device_information.id
    try:
        dev_id = asyncio.run(go())
    except OSError:
        dev_id = None
    if not dev_id:
        raise BtError("Windows can't find that device on this radio.")
    return dev_id


def paired():
    async def go():
        # the device selectors, not aqs(True) with an explicit kind: that query waits ~30 s before it returns
        out = []
        for cls in (BluetoothDevice, BluetoothLEDevice):
            sel = cls.get_device_selector_from_pairing_state(True)
            out += [record(d) for d in await DeviceInformation.find_all_async_aqs_filter_and_additional_properties(sel, PROPS)]
        return out
    try:
        return merge(asyncio.run(go()), local_address())
    except OSError as e:
        log.warning("paired list failed: %s", e)
        raise BtError("Couldn't read the paired devices. Is Bluetooth on?")


def unpair(dev_id):
    async def go():
        di = await DeviceInformation.create_from_id_async(dev_id)
        return (await di.pairing.unpair_async()).status.name
    try:
        status = asyncio.run(go())
    except OSError:
        status = "FAILED"
    if status not in ("UNPAIRED", "ALREADY_UNPAIRED"):
        raise BtError(f"Couldn't remove the device ({status.replace('_', ' ').lower()}).")


async def _radio():
    if await Radio.request_access_async() != RadioAccessStatus.ALLOWED:
        raise BtError("Windows didn't let the app control Bluetooth.")
    return next((r for r in await Radio.get_radios_async() if r.kind == RadioKind.BLUETOOTH), None)


def power():
    try:
        r = asyncio.run(_radio())
    except (OSError, BtError):
        return "unknown"
    return {RadioState.ON: "on", RadioState.OFF: "off"}.get(r.state, "unknown") if r else "unknown"


def set_power(on):
    word = "on" if on else "off"
    async def go():
        r = await _radio()
        if r is None:
            raise BtError("No Bluetooth radio found. Plug in the dongle or switch radios.")
        return await r.set_state_async(RadioState.ON if on else RadioState.OFF)
    try:
        ok = asyncio.run(go()) == RadioAccessStatus.ALLOWED
    except OSError:
        ok = False
    if not ok:
        raise BtError(f"Windows didn't let the app turn Bluetooth {word}.")


class Search:
    """Live search: Windows looks for unpaired devices in range; on_change(rows, done) gets the whole current list."""
    def __init__(self, on_change, seconds, watcher=None):
        self._on_change, self._dis, self._sent, self._done = on_change, {}, None, False
        self._lock = threading.Lock()
        self._w = watcher or DeviceInformation.create_watcher_with_kind_aqs_filter_and_additional_properties(
            aqs(False), PROPS, _AEP)
        self._w.add_added(self._added)
        self._w.add_updated(self._updated)   # Windows only fires Added when Updated and Removed have handlers
        self._w.add_removed(self._removed)
        self._w.add_stopped(lambda s, e: self.stop())
        self._timer = threading.Timer(seconds, self.stop)
        self._timer.daemon = True

    def start(self):
        self._w.start()
        self._timer.start()

    def _added(self, sender, di):
        with self._lock:
            self._dis[di.id] = di
        self._emit()

    def _updated(self, sender, upd):
        with self._lock:
            di = self._dis.get(upd.id)
            if di is None:
                return
            di.update(upd)
        self._emit()

    def _removed(self, sender, upd):
        with self._lock:
            self._dis.pop(upd.id, None)
        self._emit()

    def _emit(self, done=False):
        with self._lock:
            if self._done and not done:
                return
            rows = nearby_rows([record(d) for d in self._dis.values()])
            if rows == self._sent and not done:
                return
            self._sent = rows
        self._on_change(rows, done)

    def stop(self):
        with self._lock:
            if self._done:
                return
            self._done = True
        self._timer.cancel()
        try:
            self._w.stop()
        except OSError:
            pass  # already stopped by Windows
        self._emit(done=True)


def search_start(on_change, seconds=30):
    global _search
    with _search_lock:
        if _search:
            _search.stop()
        _search = Search(on_change, seconds)
        _search.start()


def search_stop():
    with _search_lock:
        if _search:
            _search.stop()


def _on_request(ask):
    """PairingRequested handler. The deferral keeps Windows waiting while the page asks the user on another thread."""
    def handler(sender, args):
        kind, pin, deferral = _KINDS.get(args.pairing_kind), args.pin, args.get_deferral()
        def finish():
            try:
                ok, typed = answer(kind, pin, ask)
                if ok:
                    args.accept_with_pin(typed) if typed else args.accept()
            except Exception:
                log.exception("pairing prompt failed")
            finally:
                deferral.complete()
        threading.Thread(target=finish, daemon=True).start()
    return handler


async def _pair(dev_id, ask):
    di = await DeviceInformation.create_from_id_async(dev_id)
    if di.pairing.is_paired:
        return "ALREADY_PAIRED"
    custom = di.pairing.custom
    token = custom.add_pairing_requested(_on_request(ask))
    try:
        result = await custom.pair_with_protection_level_async(_ALL_KINDS, DevicePairingProtectionLevel.DEFAULT)
    finally:
        custom.remove_pairing_requested(token)
    return result.status.name


def pair(dev_id, ask):
    """ask(kind, pin) -> (accepted, typed) is called for PIN ceremonies ('confirm', 'display', 'provide')."""
    if not _pair_lock.acquire(blocking=False):
        raise BtError("Already pairing a device.")
    try:
        search_stop()  # searching while pairing makes some devices fail
        try:
            status = asyncio.run(_pair(dev_id, ask))
        except OSError as e:
            log.warning("pairing failed: %s", e)
            status = "FAILED"
    finally:
        _pair_lock.release()
    if status not in ("PAIRED", "ALREADY_PAIRED"):
        raise BtError(pair_message(status))
