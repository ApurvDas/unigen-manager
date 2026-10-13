# Bluetooth as a primary app: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pair, connect and switch every common Bluetooth device inside Unigen Manager (live search, PIN prompts, on/off, reliable audio connect) and ship it as 1.0.2.

**Architecture:**
- **New `btwinrt.py`:** does all Windows Runtime work in Python through the `winrt` packages. Its pure helpers (kinds, twin merge, messages, ceremony answers) test without hardware.
- **`bt.py`:** stays the only Bluetooth module `api.py` calls. It keeps PnP radio switching (PowerShell) and audio connect, which gains the KS "one-shot reconnect" method.
- **`api.py`:** pushes search results and PIN prompts to the page with `evaluate_js`, and receives answers through `bt_pair_answer`.

**Tech Stack:** Python 3.10, winrt 3.2.1 (`winrt-runtime`, `Windows.Foundation`, `Windows.Foundation.Collections`, `Windows.Devices.Enumeration`, `Windows.Devices.Bluetooth`, `Windows.Devices.Radios`), ctypes (SetupAPI, cfgmgr32, KS IOCTL), pywebview 6.2.1, anime.js 4.5.0, pytest + Playwright (msedge), PyInstaller 6.22.3.

**Spec:** `docs/superpowers/specs/2026-10-13-bluetooth-primary-design.md`

## Global Constraints

- **Python:** run it as `py -3.10`. The MSYS2 `python` has no pip.
- **Test data:** never commit real device names, addresses or SSIDs. Fixtures use made-up values (addresses `02:00:00:00:00:xx`, names like "Galaxy Buds2 Pro", "Pixel 8").
- **Process control:** never `taskkill /IM`. Stop only processes you started, by PID.
- **Errors:** every user-facing error is a plain sentence with a next step. Unexpected exceptions go to `app.log` through `_envelope`.
- **Mock parity:** `ui/mock-api.js` defines exactly the public `Api` methods (`test_mock_api_matches_python_api`).
- **UI style:** dark only. Motion uses anime.js helpers from `ui/shared.js` (`addEl`, `removeEl`, `swap`, `busy`, `arrive`, `setMsg`), and `reduce` turns motion into fades.
- **Device names:** always shown with `esc()` / `textContent`, never as markup.
- **Pairing timing:** search runs 30 s, and a pairing prompt waits 60 s.

## Review Focus

1. **Bluetooth turns off, or the dongle is unplugged, during a search:** the watcher's Stopped event must end the search with `done: true` and no crash. Test in Task 2 `test_search_stopped_by_windows_ends_search`.
2. **The user walks away from a PIN prompt:** `_ask` must decline after 60 s so pairing never hangs. Test in Task 4 `test_pair_prompt_times_out_and_declines`.
3. **A device paired through its LE twin:** Remove must unpair every id of the row, and Connect must use the classic address. Test in Task 4 `test_bt_remove_unpairs_every_twin`.
4. **A second Pair click while a pairing runs:** it returns "Already pairing a device." Test in Task 2 `test_second_pairing_is_refused`. The UI also ignores it (`pairingRow`).
5. **A nearby device named like an HTML tag:** it renders as text in the row and the prompt. Test in Task 5 `test_hostile_nearby_name_is_text`.

---

### Task 1: Dependencies and `btwinrt` pure helpers

**Files:**
- Modify: `requirements.txt`
- Create: `btwinrt.py`
- Test: `tests/test_btwinrt.py`

**Interfaces:**
- Produces:
  - `btwinrt.BtError(Exception)`
  - `kind(major:int|None, minor:int|None) -> str`
  - `le_kind(appearance:int|None) -> str`
  - `record_kind(rec:dict) -> str`
  - `merge(records:list[dict]) -> list[row]`, where `row = {"id","ids","name","kind","connected","address"}`
  - `nearby_rows(records) -> list[row]`, keeping only present, named records
  - `pair_message(status_name:str) -> str`
  - `answer(kind:str|None, pin:str, ask) -> (bool, str|None)`
- Record dicts look like `{"id","name","le":bool,"present":bool,"connected":bool,"address":"HEX12","major","minor","appearance"}`.

- [ ] **Step 1: Write failing tests** (`tests/test_btwinrt.py`)

```python
import pytest
import btwinrt as w


def rec(id, name, le=False, present=True, connected=False, address="020000000010", major=None, minor=None, appearance=None):
    return {"id": id, "name": name, "le": le, "present": present, "connected": connected, "address": address,
            "major": major, "minor": minor, "appearance": appearance}


def test_classic_kinds():
    assert w.kind(4, 5) == "Speaker" and w.kind(4, 6) == "Headphones" and w.kind(4, 1) == "Headphones"
    assert w.kind(4, 15) == "TV" and w.kind(4, 0) == "Audio"
    assert w.kind(5, 2) == "Controller" and w.kind(5, 0x10) == "Keyboard" and w.kind(5, 0x20) == "Mouse"
    assert w.kind(2, 3) == "Phone" and w.kind(1, 3) == "Computer" and w.kind(0, 0) == "Device" and w.kind(None, None) == "Device"


def test_le_kinds_from_appearance():
    assert w.le_kind(0x03C1) == "Keyboard" and w.le_kind(0x03C2) == "Mouse" and w.le_kind(0x03C4) == "Controller"
    assert w.le_kind(0x0941) == "Headphones" and w.le_kind(0x0841) == "Speaker" and w.le_kind(0x0040) == "Phone"
    assert w.le_kind(0) == "Device" and w.le_kind(None) == "Device"


def test_merge_twins_keeps_classic_id_and_every_id():
    rows = w.merge([rec("BluetoothLE#le-1", "Galaxy Buds2 Pro", le=True, appearance=0x0941, address="7A0000000001"),
                    rec("Bluetooth#c-1", "Galaxy Buds2 Pro", major=4, minor=6, address="020000000011")])
    assert rows == [{"id": "Bluetooth#c-1", "ids": ["Bluetooth#c-1", "BluetoothLE#le-1"], "name": "Galaxy Buds2 Pro",
                     "kind": "Headphones", "connected": False, "address": "020000000011"}]


def test_merge_prefers_connected_record_and_sorts_by_name():
    rows = w.merge([rec("Bluetooth#b", "Den Beats Pill", major=4, minor=5, address="020000000012"),
                    rec("Bluetooth#a", "Den Beats Pill", major=4, minor=5, connected=True, address="020000000013"),
                    rec("Bluetooth#j", "armband", major=7, minor=1)])
    assert [r["name"] for r in rows] == ["armband", "Den Beats Pill"]
    assert rows[1]["id"] == "Bluetooth#a" and rows[1]["connected"] and rows[1]["address"] == "020000000013"


def test_le_only_row_and_unnamed_label():
    (row,) = w.merge([rec("BluetoothLE#m", "", le=True, appearance=0x03C2, address="7A0000006A44")])
    assert row["kind"] == "Mouse" and row["name"] == "Unknown device 6A44"


def test_nearby_rows_drop_absent_and_unnamed():
    rows = w.nearby_rows([rec("Bluetooth#1", "Pixel 8", major=2, minor=3), rec("Bluetooth#2", "Gone", present=False),
                          rec("BluetoothLE#3", "", le=True)])
    assert [r["name"] for r in rows] == ["Pixel 8"]


@pytest.mark.parametrize("status, text", [
    ("AUTHENTICATION_FAILURE", "The device refused. Put it in pairing mode, and disconnect it from your phone first."),
    ("CONNECTION_REJECTED", "The device refused."),
    ("AUTHENTICATION_TIMEOUT", "The device didn't answer. Bring it closer and make sure it's in pairing mode."),
    ("FAILED", "The device didn't answer."),
    ("REJECTED_BY_HANDLER", "Pairing cancelled."),
    ("PAIRING_CANCELED", "Pairing cancelled."),
    ("AUTHENTICATION_NOT_ALLOWED", "Wrong PIN. Try again."),
    ("TOO_MANY_CONNECTIONS", "Too many devices are connected."),
    ("PROTECTION_LEVEL_COULD_NOT_BE_MET", "Pairing failed (protection level could not be met)."),
])
def test_pair_messages(status, text):
    assert w.pair_message(status).startswith(text)


def test_answer_for_each_ceremony():
    asked = []
    def ask(kind, pin, reply=(True, None)):
        asked.append((kind, pin)); return reply
    assert w.answer(None, "", ask) == (True, None) and asked == []          # confirm only: no prompt
    assert w.answer("confirm", "482913", ask) == (True, None)
    assert w.answer("confirm", "482913", lambda k, p: (False, None)) == (False, None)
    assert w.answer("display", "482913", ask) == (True, None)
    assert w.answer("provide", "", lambda k, p: (True, " 0000 ")) == (True, "0000")
    assert w.answer("provide", "", lambda k, p: (True, "  ")) == (False, None)  # blank PIN declines
    assert w.answer("provide", "", lambda k, p: (False, "0000")) == (False, None)
    assert asked == [("confirm", "482913"), ("display", "482913")]
```

- [ ] **Step 2: Run, expect import failure**

Run `py -3.10 -m pytest tests/test_btwinrt.py -q`. It fails with `ModuleNotFoundError: btwinrt`.

- [ ] **Step 3: Add dependencies and write `btwinrt.py` (pure part)**

Append to `requirements.txt`:

```
winrt-runtime==3.2.1
winrt-Windows.Foundation==3.2.1
winrt-Windows.Foundation.Collections==3.2.1
winrt-Windows.Devices.Enumeration==3.2.1
winrt-Windows.Devices.Bluetooth==3.2.1
winrt-Windows.Devices.Radios==3.2.1
```

`btwinrt.py`:

```python
"""Bluetooth through Windows' device APIs (WinRT): paired devices, live search, pairing with PIN prompts,
unpairing and the radio's on/off switch. bt.py is the only caller. The pure helpers at the top test without hardware."""
import logging

log = logging.getLogger("unigen")


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


def merge(records):
    """One row per device. A device's classic and LE records (same name) become one row that keeps every id;
    the classic, connected record leads, because pairing and audio go through it.
    ponytail: matching by name merges two different devices that share a name; random LE addresses leave nothing better."""
    rows = {}
    for r in sorted(records, key=lambda r: (r["le"], not r["connected"])):
        key = r["name"] or r["id"]
        k = record_kind(r)
        row = rows.get(key)
        if row is None:
            rows[key] = {"id": r["id"], "ids": [r["id"]], "name": r["name"] or f"Unknown device {r['address'][-4:]}",
                         "kind": k, "connected": r["connected"], "address": r["address"]}
        else:
            row["ids"].append(r["id"])
            row["connected"] = row["connected"] or r["connected"]
            if row["kind"] == "Device":
                row["kind"] = k
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
```

- [ ] **Step 4: Install and run**

Run `py -3.10 -m pip install -r requirements.txt`, then `py -3.10 -m pytest tests/test_btwinrt.py -q`. All tests pass.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt btwinrt.py tests/test_btwinrt.py
git commit -m "feat(bt): WinRT Bluetooth helpers: device kinds, twin merge, pairing messages and ceremony answers"
```

---

### Task 2: `btwinrt` Windows calls (paired list, search, pairing, unpair, power)

**Files:**
- Modify: `btwinrt.py` (append)
- Test: `tests/test_btwinrt.py` (append), `tests/hardware/test_readonly.py` (append)

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces:
  - `paired() -> list[row]`
  - `unpair(dev_id:str) -> None`
  - `power() -> "on"|"off"|"unknown"`
  - `set_power(on:bool) -> None`
  - `search_start(on_change, seconds=30) -> None` and `search_stop() -> None`, where `on_change(rows:list[row], done:bool)` runs on a WinRT thread
  - `pair(dev_id:str, ask) -> None`, which raises `BtError(pair_message(...))`
  - `class Search(on_change, seconds, watcher=None)`, for tests

Key facts from the 2026-10-13 spike:
- Static methods live on the metaclass, so `dir(DeviceInformation)` doesn't list them.
- Calls are `find_all_async_with_kind_aqs_filter_and_additional_properties(aqs, props, kind)` and `create_watcher_with_kind_aqs_filter_and_additional_properties(aqs, props, kind)`.
- `System.Devices.Aep.Bluetooth.Cod` is not a valid key. Use `.Cod.Major` and `.Cod.Minor`.
- Property values are boxed. Unbox them with `obj.as_(IPropertyValue)` and `get_<type>()`.
- A watcher only fires Added when Updated and Removed handlers are also attached.
- `Radio.request_access_async()` returns ALLOWED for desktop apps.
- `pair_with_protection_level_async` against buds that aren't in pairing mode returns AUTHENTICATION_TIMEOUT after about 64 s.

- [ ] **Step 1: Write failing tests** (append to `tests/test_btwinrt.py`)

```python
import asyncio, threading


class FakeWatcher:
    def __init__(self):
        self.cb, self.started, self.stopped = {}, False, 0
    def add_added(self, f): self.cb["added"] = f
    def add_updated(self, f): self.cb["updated"] = f
    def add_removed(self, f): self.cb["removed"] = f
    def add_stopped(self, f): self.cb["stopped"] = f
    def start(self): self.started = True
    def stop(self): self.stopped += 1


class Upd:
    def __init__(self, id): self.id = id


def make_search(monkeypatch, seconds=60):
    monkeypatch.setattr(w, "record", lambda di: di)  # fake DeviceInformation = already a record dict
    seen, fw = [], FakeWatcher()
    s = w.Search(lambda rows, done: seen.append(([r["name"] for r in rows], done)), seconds, watcher=fw)
    s.start()
    return s, fw, seen


def test_search_pushes_rows_as_devices_come_and_go(monkeypatch):
    s, fw, seen = make_search(monkeypatch)
    assert fw.started
    fw.cb["added"](None, rec("Bluetooth#1", "Pixel 8", major=2, minor=3))
    fw.cb["added"](None, rec("BluetoothLE#2", "", le=True))               # nameless: no change, no push
    fw.cb["added"](None, rec("Bluetooth#3", "Galaxy Buds2 Pro", major=4, minor=6))
    fw.cb["removed"](None, Upd("Bluetooth#1"))
    s.stop(); s.stop()                                                     # second stop is a no-op
    assert seen == [(["Pixel 8"], False), (["Galaxy Buds2 Pro", "Pixel 8"], False), (["Galaxy Buds2 Pro"], False),
                    (["Galaxy Buds2 Pro"], True)]
    assert fw.stopped == 1


def test_search_stopped_by_windows_ends_search(monkeypatch):
    s, fw, seen = make_search(monkeypatch)
    fw.cb["stopped"](None, None)  # radio turned off or dongle unplugged
    assert seen == [([], True)]


def test_search_times_out(monkeypatch):
    s, fw, seen = make_search(monkeypatch, seconds=0.01)
    for _ in range(100):
        if seen: break
        threading.Event().wait(0.01)
    assert seen == [([], True)] and fw.stopped == 1


def test_pair_maps_status_and_stops_search(monkeypatch):
    stops = []
    monkeypatch.setattr(w, "search_stop", lambda: stops.append(1))
    async def fake(dev_id, ask): return "PAIRED"
    monkeypatch.setattr(w, "_pair", fake)
    w.pair("Bluetooth#1", None)
    async def refused(dev_id, ask): return "AUTHENTICATION_FAILURE"
    monkeypatch.setattr(w, "_pair", refused)
    with pytest.raises(w.BtError, match="The device refused"):
        w.pair("Bluetooth#1", None)
    assert stops == [1, 1]


def test_pair_turns_windows_errors_into_a_sentence(monkeypatch):
    monkeypatch.setattr(w, "search_stop", lambda: None)
    async def gone(dev_id, ask): raise OSError("element not found")
    monkeypatch.setattr(w, "_pair", gone)
    with pytest.raises(w.BtError, match="didn't answer"):
        w.pair("Bluetooth#1", None)


def test_second_pairing_is_refused(monkeypatch):
    w._pair_lock.acquire()
    try:
        with pytest.raises(w.BtError, match="Already pairing a device."):
            w.pair("Bluetooth#2", None)
    finally:
        w._pair_lock.release()
```

Append to `tests/hardware/test_readonly.py`:

```python
def test_winrt_bluetooth_reads():
    import btwinrt
    assert btwinrt.power() in ("on", "off")
    rows = btwinrt.paired()
    assert all({"id", "ids", "name", "kind", "connected", "address"} <= set(r) for r in rows)
```

- [ ] **Step 2: Run, expect failures**

Run `py -3.10 -m pytest tests/test_btwinrt.py -q`. It fails with `AttributeError: Search`, `_pair` and `_pair_lock`.

- [ ] **Step 3: Implement** (append to `btwinrt.py`, and add these imports at the top)

```python
import asyncio, logging, threading

from winrt.windows.devices.enumeration import (DeviceInformation, DeviceInformationKind, DevicePairingKinds,
                                               DevicePairingProtectionLevel)
from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioKind, RadioState
from winrt.windows.foundation import IPropertyValue, PropertyType
```

```python
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
            "address": (v("DeviceAddress") or "").replace(":", "").upper(),
            "major": v("Bluetooth.Cod.Major"), "minor": v("Bluetooth.Cod.Minor"), "appearance": v("Bluetooth.Le.Appearance")}


def paired():
    async def go():
        return [record(d) for d in await DeviceInformation.find_all_async_with_kind_aqs_filter_and_additional_properties(
            aqs(True), PROPS, _AEP)]
    try:
        return merge(asyncio.run(go()))
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
    except OSError:
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
```

- [ ] **Step 4: Run tests**

Run `py -3.10 -m pytest tests/test_btwinrt.py -q`, then `py -3.10 -m pytest -m hardware tests/hardware -q -k winrt`. Both pass.

- [ ] **Step 5: Commit**

```bash
git add btwinrt.py tests/test_btwinrt.py tests/hardware/test_readonly.py
git commit -m "feat(bt): WinRT paired list, live search, pairing with PIN prompts, unpair and radio power"
```

---

### Task 3: `bt.py` delegates to `btwinrt`; KS audio connect; smaller `bt.ps1`

**Files:**
- Modify: `bt.py`, `bt.ps1`
- Test: `tests/test_bt.py`

**Interfaces:**
- Consumes: `btwinrt.*` from Task 2.
- Produces:
  - `bt.BtError` (the same class as `btwinrt.BtError`)
  - `bt.devices() -> list[row]`
  - `bt.pair(dev_id, ask)`
  - `bt.remove(ids:list[str])`
  - `bt.power()` and `bt.set_power(on)`
  - `bt.search_start(on_change)` and `bt.search_stop()`
  - `bt.connect(address_hex, name, *, open_settings=os.startfile)` and `bt.disconnect(...)`. Passing `open_settings=None` means "don't open Settings, just raise".
  - `bt._ks_match(path, parent_id, address_hex) -> bool` and `bt._ks_oneshot(address_hex, connect:bool)`

- [ ] **Step 1: Update tests** in `tests/test_bt.py`
  - Delete `test_devices_map_kind_and_keep_ids_as_params`, `test_pair_statuses` and `test_remove`.
  - In `test_versions_and_kinds`, replace the `bt.kind` asserts with `import btwinrt` and `btwinrt.kind`, using the same values.
  - Replace the connect tests (`test_connect_falls_back_to_settings`, `test_connect_uses_service_toggle`, `test_connect_disabled_by_spike`, `test_toggle_failure_is_logged`) with:

```python
def test_remove_unpairs_every_id(monkeypatch):
    done = []
    monkeypatch.setattr(bt.btwinrt, "unpair", done.append)
    bt.remove(["Bluetooth#c", "BluetoothLE#l"])
    assert done == ["Bluetooth#c", "BluetoothLE#l"]


def test_ks_match_by_path_or_parent():
    a2dp = r"\\?\bthenum#{0000110b-0000-1000-8000-00805f9b34fb}_vid&0001004c#8&1&0&020000000013_c00000000#{6994ad04}\src"
    hfp = r"\\?\bthhfenum#bthhfpaudio#9&2&0&97#{6994ad04}\wave"
    assert bt._ks_match(a2dp, "", "020000000013")
    assert bt._ks_match(hfp, r"BTHENUM\{0000111e-0000-1000-8000-00805f9b34fb}_VID&0001004c\8&1&0&020000000013_C00000000", "020000000013")
    assert not bt._ks_match(hfp, r"BTHENUM\{0000111e}\8&1&0&020000000099_C0", "020000000013")


def test_connect_tries_ks_then_services_then_settings(monkeypatch, caplog):
    order, opened = [], []
    def ks(addr, on): order.append(("ks", on)); raise bt.BtError("no filter")
    def svc(addr, flags): order.append(("svc", flags)); raise bt.BtError("refused")
    monkeypatch.setattr(bt, "_ks_oneshot", ks)
    monkeypatch.setattr(bt, "_set_audio", svc)
    with pytest.raises(bt.BtError, match="Bluetooth settings are open"):
        bt.connect("020000000013", "JBL Go 3", open_settings=opened.append)
    assert order == [("ks", True), ("svc", [0, 1])] and opened == ["ms-settings:bluetooth"]
    assert "audio connect failed" in caplog.text


def test_connect_stops_at_first_method_that_works(monkeypatch):
    order = []
    monkeypatch.setattr(bt, "_ks_oneshot", lambda addr, on: order.append(("ks", on)))
    monkeypatch.setattr(bt, "_set_audio", lambda addr, flags: order.append("svc"))
    bt.disconnect("020000000013", "JBL Go 3", open_settings=None)
    assert order == [("ks", False)]


def test_connect_without_settings_fallback_just_raises(monkeypatch):
    monkeypatch.setattr(bt, "_ks_oneshot", lambda a, on: (_ for _ in ()).throw(bt.BtError("x")))
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", False)
    with pytest.raises(bt.BtError, match="Windows didn't let the app connect JBL Go 3."):
        bt.connect("020000000013", "JBL Go 3", open_settings=None)
```

- [ ] **Step 2: Run, expect failures**

Run `py -3.10 -m pytest tests/test_bt.py -q`. It fails: `_ks_match`, `_ks_oneshot` and `bt.btwinrt` are missing.

- [ ] **Step 3: Implement**

In `bt.py`:
- Make `import btwinrt` and `from btwinrt import BtError` replace the local `class BtError`.
- Delete `_PAIR_ERRORS`, `kind`, `devices`, `pair` and `remove`, then add:

```python
devices, pair, power, set_power = btwinrt.paired, btwinrt.pair, btwinrt.power, btwinrt.set_power
search_start, search_stop = btwinrt.search_start, btwinrt.search_stop


def remove(ids):
    for i in ids:  # a device's classic and LE records are both paired
        btwinrt.unpair(i)
```

Replace `_toggle`, `connect` and `disconnect` with the chain below, and add the KS section above it:

```python
# ---- audio connect, way 1: the one-shot reconnect Windows Settings uses (KS property on the device's audio filters) ----
_KSCATEGORY_AUDIO = "6994AD04-93EF-11D0-A3CC-00A0C9223196"
_KSPROPSETID_BTAUDIO = "7FA06C40-B8F6-4C7E-8556-E8C33A12E54D"
_IOCTL_KS_PROPERTY = 0x2F0003  # CTL_CODE(FILE_DEVICE_KS, 0, METHOD_NEITHER, FILE_ANY_ACCESS)


class _GUID(ctypes.Structure):
    _fields_ = [("b", ctypes.c_ubyte * 16)]


def _guid(text):
    return _GUID((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le))


class _IFACE(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("guid", _GUID), ("flags", wintypes.DWORD), ("reserved", ctypes.c_void_p)]


class _DEVINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("guid", _GUID), ("devinst", wintypes.DWORD), ("reserved", ctypes.c_void_p)]


class _KSPROPERTY(ctypes.Structure):
    _fields_ = [("set", _GUID), ("id", wintypes.ULONG), ("flags", wintypes.ULONG)]


def _ks_match(path, parent_id, address_hex):
    """A2DP filter paths carry the address; hands-free ones only through their parent device."""
    a = address_hex.lower()
    return a in path.lower() or a in (parent_id or "").lower()


def _ks_filters(address_hex):
    sa, cm = ctypes.WinDLL("setupapi", use_last_error=True), ctypes.WinDLL("cfgmgr32")
    sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    sa.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    sa.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_GUID), wintypes.DWORD,
                                               ctypes.POINTER(_IFACE)]
    sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IFACE), ctypes.c_void_p, wintypes.DWORD,
                                                    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_DEVINFO)]
    sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    cat = _guid(_KSCATEGORY_AUDIO)
    h = sa.SetupDiGetClassDevsW(ctypes.byref(cat), None, None, 0x2 | 0x10)  # DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    out, i = [], 0
    try:
        while True:
            iface = _IFACE(cbSize=ctypes.sizeof(_IFACE))
            if not sa.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(cat), i, ctypes.byref(iface)):
                break
            i += 1
            need, dev = wintypes.DWORD(), _DEVINFO(cbSize=ctypes.sizeof(_DEVINFO))
            sa.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(iface), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not sa.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(iface), buf, need, None, ctypes.byref(dev)):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            if "bth" not in path.lower():
                continue
            parent, pid = wintypes.DWORD(), ctypes.create_unicode_buffer(512)
            if cm.CM_Get_Parent(ctypes.byref(parent), dev.devinst, 0) == 0:
                cm.CM_Get_Device_IDW(parent, pid, 512, 0)
            if _ks_match(path, pid.value, address_hex):
                out.append(path)
    finally:
        sa.SetupDiDestroyDeviceInfoList(h)
    return out


def _ks_oneshot(address_hex, connect):
    """KSPROPERTY_ONESHOT_RECONNECT (0) / _DISCONNECT (1) on every audio filter of the device."""
    paths = _ks_filters(address_hex)
    if not paths:
        raise BtError("That device has no Bluetooth audio driver on this radio.")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    prop = _KSPROPERTY(_guid(_KSPROPSETID_BTAUDIO), 0 if connect else 1, 1)  # KSPROPERTY_TYPE_GET
    ok, err = False, 0
    for p in paths:
        h = k32.CreateFileW(p, 0xC0000000, 3, None, 3, 0, None)  # read/write, shared, OPEN_EXISTING
        if h in (None, wintypes.HANDLE(-1).value):
            err = ctypes.get_last_error()
            continue
        try:
            ret = wintypes.DWORD()
            if k32.DeviceIoControl(h, _IOCTL_KS_PROPERTY, ctypes.byref(prop), ctypes.sizeof(prop), None, 0,
                                   ctypes.byref(ret), None):
                ok = True
            else:
                err = ctypes.get_last_error()
        finally:
            k32.CloseHandle(h)
    if not ok:
        raise BtError(f"The audio driver refused (error {err}).")


# ---- audio connect: way 1, then way 2 (service toggle), then Windows settings ----
def _toggle(address_hex, name, connect, open_settings):
    ways = [lambda: _ks_oneshot(address_hex, connect)]
    if SERVICE_TOGGLE:
        ways.append(lambda: _set_audio(address_hex, [0, 1] if connect else [0]))
    for way in ways:
        try:
            way()
            return
        except (BtError, OSError, ValueError, ctypes.ArgumentError, AttributeError) as e:
            logging.getLogger("unigen").warning("audio connect failed: %s: %s", type(e).__name__, e)
    verb = "connect" if connect else "disconnect"
    if open_settings is None:
        raise BtError(f"Windows didn't let the app {verb} {name}.")
    open_settings("ms-settings:bluetooth")
    raise BtError(f"Windows didn't let the app {verb} {name}. Bluetooth settings are open so you can do it there.")


def connect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, True, open_settings)


def disconnect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, False, open_settings)
```

Update the `SERVICE_TOGGLE` comment to say: "Way 2 of audio connect; the hardware check in Task 7 decides whether it stays."

In `bt.ps1`:
- Delete the `Winrt`, `Await`, `List` and `Pairing` functions, and the `paired`, `nearby`, `pair` and `unpair` switch arms.
- Change line 2 to `# $p.action: radios | enable | disable. Output: one JSON document.`

- [ ] **Step 4: Run tests**

Run `py -3.10 -m pytest tests/test_bt.py tests/test_btwinrt.py -q`. Both pass.

- [ ] **Step 5: Commit**

```bash
git add bt.py bt.ps1 tests/test_bt.py
git commit -m "feat(bt): devices and pairing through WinRT; audio connect tries the KS one-shot reconnect first"
```

---

### Task 4: API methods, pairing prompt round trip, mock parity

**Files:**
- Modify: `api.py`, `ui/mock-api.js`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: the Task 3 `bt.*` functions.
- Produces (`Api` methods; JS pushes):
  - `bt_radio()`: adds `"power"`.
  - `bt_power(on) -> {"power"}`
  - `bt_paired() -> list[row]`
  - `bt_search_start()` pushes `window.onBtNearby({devices, done})`.
  - `bt_search_stop()`
  - `bt_pair(id) -> row|None` pushes `window.onPairPrompt({kind, pin})`.
  - `bt_pair_answer(accept, pin=None)`
  - `bt_remove(id)`
  - `bt_connect(id)` and `bt_disconnect(id)`
  - `bt_nearby` is removed.
  - Module constant `api.PAIR_WAIT = 60`.
- Mock test hooks:
  - `MOCK_SEARCH_HOLD`: the search never finishes.
  - `MOCK_BT_OFF`: start with Bluetooth off.
  - Mock nearby devices carry `ceremony: null | "confirm" | "display" | "provide"`. The PIN shown is always `482913`, and the correct provide PIN is `0000`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_api.py`)

```python
ROWS = [{"id": "Bluetooth#c", "ids": ["Bluetooth#c", "BluetoothLE#l"], "name": "Galaxy Buds2 Pro", "kind": "Headphones",
         "connected": False, "address": "020000000011"}]


class Win:
    def __init__(self, on_script=None): self.scripts, self.on_script = [], on_script
    def evaluate_js(self, s):
        self.scripts.append(s)
        if self.on_script: self.on_script(s)


def test_bt_pair_prompts_page_and_uses_answer(monkeypatch):
    a, got = api.Api(), []
    a._window = Win(lambda s: a.bt_pair_answer(True, "0000") if "onPairPrompt" in s else None)
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: got.append(ask("provide", "")))
    monkeypatch.setattr(bt, "devices", lambda: ROWS)
    monkeypatch.setattr(bt, "connect", lambda *a, **k: None)
    r = a.bt_pair("BluetoothLE#l")
    assert got == [(True, "0000")] and '"kind": "provide"' in a._window.scripts[0]
    assert r == {"ok": True, "data": dict(ROWS[0], connected=True)}  # audio device connected right away


def test_bt_pair_display_pin_does_not_wait(monkeypatch):
    a, got = api.Api(), []
    a._window = Win()
    monkeypatch.setattr(api, "PAIR_WAIT", 5)
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: got.append(ask("display", "482913")))
    monkeypatch.setattr(bt, "devices", lambda: [])
    assert a.bt_pair("Bluetooth#k") == {"ok": True, "data": None} and got == [(True, None)]


def test_pair_prompt_times_out_and_declines(monkeypatch):
    a, got = api.Api(), []
    a._window = Win()
    monkeypatch.setattr(api, "PAIR_WAIT", 0.01)
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: got.append(ask("confirm", "482913")))
    monkeypatch.setattr(bt, "devices", lambda: [])
    a.bt_pair("Bluetooth#p")
    assert got == [(False, None)]


def test_bt_pair_audio_connect_failure_is_not_an_error(monkeypatch):
    a = api.Api()
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: None)
    monkeypatch.setattr(bt, "devices", lambda: ROWS)
    def nope(*a, **k): raise bt.BtError("refused")
    monkeypatch.setattr(bt, "connect", nope)
    assert a.bt_pair("Bluetooth#c")["data"]["connected"] is False


def test_bt_remove_unpairs_every_twin(monkeypatch):
    removed = []
    monkeypatch.setattr(bt, "devices", lambda: ROWS)
    monkeypatch.setattr(bt, "remove", removed.append)
    api.Api().bt_remove("BluetoothLE#l")
    assert removed == [["Bluetooth#c", "BluetoothLE#l"]]


def test_bt_connect_uses_classic_address_of_twin(monkeypatch):
    seen = []
    monkeypatch.setattr(bt, "devices", lambda: ROWS)
    monkeypatch.setattr(bt, "connect", lambda addr, name: seen.append((addr, name)))
    api.Api().bt_connect("BluetoothLE#l")
    assert seen == [("020000000011", "Galaxy Buds2 Pro")]


def test_bt_search_pushes_rows_to_main_window(monkeypatch):
    a = api.Api()
    a._window = Win()
    monkeypatch.setattr(bt, "search_start", lambda on_change: on_change(ROWS, True))
    assert a.bt_search_start() == {"ok": True, "data": None}
    assert a._window.scripts[0].startswith("window.onBtNearby && window.onBtNearby(") and '"done": true' in a._window.scripts[0]


def test_bt_radio_power_and_switch(hw, monkeypatch):
    monkeypatch.setattr(bt, "power", lambda: "off")
    assert api.Api().bt_radio()["data"]["power"] == "off"
    calls = []
    monkeypatch.setattr(bt, "set_power", calls.append)
    assert api.Api().bt_power(1) == {"ok": True, "data": {"power": "off"}} and calls == [True]
```

The existing `test_bt_connect_looks_up_address` patches `bt.devices` with a `paired=` keyword. Update its fake to `lambda: [...]` and give its row `"ids": [<its id>]`.

- [ ] **Step 2: Run, expect failures**

Run `py -3.10 -m pytest tests/test_api.py -q`.

- [ ] **Step 3: Implement**

In `api.py`, add the module constant `PAIR_WAIT = 60  # seconds a pairing prompt waits for the user`. In `__init__`, add `self._pair_evt, self._pair_answer = threading.Event(), (False, None)`. Replace the Bluetooth block:

```python
    # ---- Bluetooth ----
    def _eval_main(self, script):
        if self._window is not None:
            self._window.evaluate_js(script)

    def _row(self, dev_id):
        return next((d for d in bt.devices() if dev_id in d["ids"]), None)

    def _device(self, dev_id):
        d = self._row(dev_id)
        if d is None:
            raise bt.BtError("That device isn't paired any more.")
        return d

    @_envelope
    def bt_radio(self):
        rs = bt.radios()
        return {"active": next((r["key"] for r in rs if r["ok"]), None), "can_switch": self._admin, "power": bt.power(),
                "radios": [{"key": r["key"], "name": self._name(r["key"], r["name"]), "ok": r["ok"],
                            "disabled": r["disabled"], "version": r["version"]} for r in rs]}

    @_envelope
    def bt_power(self, on):
        bt.set_power(bool(on))
        return {"power": bt.power()}

    @_envelope
    def bt_switch(self, key):  # unchanged
        ...

    @_envelope
    def bt_paired(self):
        return bt.devices()

    def _push_nearby(self, rows, done):
        self._eval_main("window.onBtNearby && window.onBtNearby(" + json.dumps({"devices": rows, "done": done}) + ")")

    @_envelope
    def bt_search_start(self):
        bt.search_start(self._push_nearby)

    @_envelope
    def bt_search_stop(self):
        bt.search_stop()

    def _ask(self, kind, pin):
        """Runs on a pairing thread: show the prompt in the page, then wait for bt_pair_answer (not for 'display')."""
        self._pair_evt.clear()
        self._pair_answer = (False, None)
        self._eval_main("window.onPairPrompt && window.onPairPrompt(" + json.dumps({"kind": kind, "pin": pin}) + ")")
        if kind == "display":
            return True, None
        if not self._pair_evt.wait(PAIR_WAIT):
            return False, None
        return self._pair_answer

    @_envelope
    def bt_pair_answer(self, accept, pin=None):
        self._pair_answer = (bool(accept), pin if isinstance(pin, str) else None)
        self._pair_evt.set()

    @_envelope
    def bt_pair(self, dev_id):
        bt.pair(dev_id, self._ask)
        d = self._row(dev_id)
        if d and d["kind"] in ("Headphones", "Speaker", "Audio") and not d["connected"]:
            try:  # ready to play: Windows doesn't always connect audio after pairing
                bt.connect(d["address"], d["name"], open_settings=None)
                d["connected"] = True
            except bt.BtError:
                pass  # bt logged it; the row's Connect button is still there
        return d

    @_envelope
    def bt_remove(self, dev_id):
        d = self._row(dev_id)
        bt.remove(d["ids"] if d else [dev_id])

    @_envelope
    def bt_connect(self, dev_id):
        d = self._device(dev_id)
        bt.connect(d["address"], d["name"])

    @_envelope
    def bt_disconnect(self, dev_id):
        d = self._device(dev_id)
        bt.disconnect(d["address"], d["name"])
```

Delete `bt_nearby` and the old `_device` helper near the top.

Make these changes in `ui/mock-api.js`:
- Add `let POWER = window.MOCK_BT_OFF ? "off" : "on", searchTimers = [], answer = null;`.
- Give every `PAIRED` entry `ids: [id]`.
- Replace `NEARBY` with:

```js
  const NEARBY = [
    { id: "BT-buds2", name: "Galaxy Buds2 Pro", kind: "Headphones", address: "B1B2C3D4E5F1", ceremony: null },
    { id: "BT-boat", name: "boAt Stone 350", kind: "Speaker", address: "B1B2C3D4E5F2", ceremony: null },
    { id: "BT-mi", name: "Mi Portable Speaker", kind: "Speaker", address: "B1B2C3D4E5F3", ceremony: null },
    { id: "BT-pixel", name: "Pixel 8", kind: "Phone", address: "B1B2C3D4E5F4", ceremony: "confirm" },
    { id: "BT-k380", name: "Keys-To-Go K3", kind: "Keyboard", address: "B1B2C3D4E5F5", ceremony: "display" },
    { id: "BT-car", name: "Car Kit 2", kind: "Audio", address: "B1B2C3D4E5F6", ceremony: "provide" },
  ];
  if (window.MOCK_HOSTILE) NEARBY.push({ id: "BT-evil2", name: "<img src=x onerror=alert(2)>", kind: "Device", address: "B1B2C3D4E5F7", ceremony: "confirm" });
```

Then replace the `bt_radio`, `bt_paired`, `bt_nearby` and `bt_pair` definitions with:

```js
  const row = d => ({ id: d.id, ids: [d.id], name: d.name, kind: d.kind, connected: !!d.connected, address: d.address });
  const push = (devices, done) => window.onBtNearby && window.onBtNearby({ devices: devices.map(row), done });
  def("bt_radio", 100, () => ({ active: (RADIOS.find(r => r.ok) || {}).key ?? null, can_switch: window.MOCK_ADMIN !== false,
    power: POWER, radios: RADIOS.map(r => ({ ...r })) }));
  def("bt_power", 600, on => { POWER = on ? "on" : "off"; return { power: POWER }; });
  def("bt_paired", 200, () => PAIRED.map(d => ({ ...d, ids: [d.id] })));
  def("bt_search_start", 100, () => {
    if (POWER === "off") throw new Error("Bluetooth is off. Turn it on first.");
    searchTimers.forEach(clearTimeout); searchTimers = [];
    const todo = NEARBY.filter(d => !PAIRED.some(p => p.id === d.id)), step = window.MOCK_FAST ? 0 : 400;
    todo.forEach((d, i) => searchTimers.push(setTimeout(() => push(todo.slice(0, i + 1), false), step * (i + 1))));
    if (!window.MOCK_SEARCH_HOLD) searchTimers.push(setTimeout(() => push(todo, true), step * (todo.length + 1)));
  });
  def("bt_search_stop", 0, () => { searchTimers.forEach(clearTimeout); searchTimers = []; });
  def("bt_pair_answer", 0, (accept, pin) => { if (answer) answer({ accept, pin }); });
  def("bt_pair", 1400, async id => {
    const d = NEARBY.find(x => x.id === id);
    if (!d) throw new Error("The device didn't answer. Bring it closer and make sure it's in pairing mode.");
    if (d.ceremony) {
      const reply = new Promise(r => { answer = r; });
      window.onPairPrompt && window.onPairPrompt({ kind: d.ceremony, pin: d.ceremony === "provide" ? "" : "482913" });
      if (d.ceremony !== "display") {
        const { accept, pin } = await reply; answer = null;
        if (!accept) throw new Error("Pairing cancelled.");
        if (d.ceremony === "provide" && pin !== "0000") throw new Error("Wrong PIN. Try again.");
      } else { answer = null; await wait(300); }
    }
    const p = { ...row(d), connected: ["Headphones", "Speaker", "Audio"].includes(d.kind) };
    PAIRED.push(p);
    return p;
  });
```

Make sure `bt_remove`, `bt_connect` and `bt_disconnect` keep working with `ids`.

- [ ] **Step 4: Run tests**

Run `py -3.10 -m pytest tests/test_api.py tests/test_bt.py tests/test_btwinrt.py -q`. They pass, including `test_mock_api_matches_python_api`.

- [ ] **Step 5: Commit**

```bash
git add api.py ui/mock-api.js tests/test_api.py
git commit -m "feat(api): Bluetooth power, live search and pairing prompts with answers from the page"
```

---

### Task 5: Main window: power switch, live search, pairing panel

**Files:**
- Modify: `ui/index.html`, `ui/shared.css`
- Test: `tests/ui/test_ui.py`

**Interfaces:**
- Consumes: the Task 4 API and mock hooks.
- Produces: element ids `#btPower` (role=switch), `#btOnNote`, `#btOn`, `#btRunNote` and `.pairbox` (with `.yes`, `.no`, `#pinIn`). Section `#bt` gets class `off` when Bluetooth is off.

- [ ] **Step 1: Write failing UI tests** (in `tests/ui/test_ui.py`, replace `test_bt_search_pair_remove` and append)

```python
def bt_page(open_page, hooks=""):
    pg = open_page(hooks)
    pg.keyboard.press("Control+2")
    expect(pg.locator("#paired .row")).to_have_count(6)
    return pg


def nearby(pg, name):
    return pg.locator("#nearby .row").filter(has=pg.get_by_text(name, exact=True))


def test_bt_search_pair_remove(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    expect(pg.locator("#nearby .row")).to_have_count(6)
    expect(pg.locator("#btSearch .label")).to_have_text("Search again")
    nearby(pg, "Galaxy Buds2 Pro").locator(".pair").click()
    expect(pg.locator("#paired .row")).to_have_count(7)
    expect(pg.locator("#pairedCount")).to_have_text("7")
    expect(pg.locator("#btMsg")).to_have_text("Paired with Galaxy Buds2 Pro.")
    hold(pg, pg.locator("#paired .row").nth(1).locator(".hold"))
    expect(pg.locator("#paired .row")).to_have_count(6)


def test_bt_pair_confirm_pin(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Pixel 8").locator(".pair").click()
    expect(pg.locator(".pairbox")).to_contain_text("Does the device show 482 913?")
    pg.locator(".pairbox .yes").click()
    expect(pg.locator(".pairbox")).to_have_count(0)
    expect(pg.locator("#paired .row")).to_have_count(7)


def test_bt_pair_cancel(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Pixel 8").locator(".pair").click()
    pg.locator(".pairbox .no").click()
    expect(pg.locator("#btMsg")).to_have_text("Pairing cancelled.")
    expect(nearby(pg, "Pixel 8")).to_have_count(1)
    expect(pg.locator("#paired .row")).to_have_count(6)


def test_bt_pair_display_pin(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Keys-To-Go K3").locator(".pair").click()
    expect(pg.locator(".pairbox")).to_contain_text("Type 482 913 on the device, then press Enter.")
    expect(pg.locator("#paired .row")).to_have_count(7)


def test_bt_pair_provide_pin_wrong_then_right(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Car Kit 2").locator(".pair").click()
    pg.locator("#pinIn").fill("1111"); pg.locator("#pinIn").press("Enter")
    expect(pg.locator("#btMsg")).to_have_text("Wrong PIN. Try again.")
    nearby(pg, "Car Kit 2").locator(".pair").click()
    pg.locator("#pinIn").fill("0000"); pg.locator(".pairbox .yes").click()
    expect(pg.locator("#paired .row")).to_have_count(7)


def test_bt_power_off_and_on(open_page):
    pg = bt_page(open_page)
    pg.locator("#btPower").click()
    expect(pg.locator("#bt")).to_have_class(re.compile(r"\boff\b"))
    expect(pg.locator("#btPower")).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#btOnNote")).to_be_visible()
    pg.locator("#btOn").click()
    expect(pg.locator("#bt")).not_to_have_class(re.compile(r"\boff\b"))
    expect(pg.locator("#btRunNote")).to_be_visible()


def test_bt_search_stops_when_leaving_page(open_page):
    pg = bt_page(open_page, "window.MOCK_SEARCH_HOLD = true; window.MOCK_LOG = [];")
    pg.locator("#btSearch").click()
    expect(pg.locator("#btSearch .label")).to_have_text("Searching…")
    pg.keyboard.press("Control+1")
    pg.wait_for_function("window.MOCK_LOG.includes('bt_search_stop')")


def test_hostile_nearby_name_is_text(open_page):
    pg = bt_page(open_page, "window.MOCK_HOSTILE = true;")
    pg.locator("#btSearch").click()
    row = nearby(pg, "<img src=x onerror=alert(2)>")
    expect(row).to_have_count(1)
    row.locator(".pair").click()
    expect(pg.locator(".pairbox")).to_contain_text("482 913")
    assert pg.locator("#nearby img").count() == 0 and not pg.errors
```

Check that `re` is imported at the top of `tests/ui/test_ui.py`.

- [ ] **Step 2: Run, expect failures**

Run `py -3.10 -m pytest tests/ui/test_ui.py -q -k bt_ or hostile_nearby`.

- [ ] **Step 3: Implement**

`ui/shared.css`: add a toggle switch. Check the existing variable names at the top of `shared.css`; use its accent variable for `--uni` and its surface variables:

```css
.switch { width: 36px; height: 20px; padding: 0; border-radius: 10px; border: 1px solid var(--line);
  background: var(--raised); position: relative; cursor: pointer; flex: none; }
.switch i { position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%; background: var(--muted); }
.switch.on { background: var(--uni); border-color: transparent; }
.switch.on i { background: #fff; }
.switch:disabled { opacity: .5; cursor: default; }
.switch:focus-visible { outline: 2px solid var(--uni); outline-offset: 2px; }
```

`ui/index.html` markup (Bluetooth section):

```html
    <div class="head"><h1>Bluetooth</h1><span class="grow"></span>
      <button class="switch on" id="btPower" role="switch" aria-checked="true" aria-label="Bluetooth"><i></i></button></div>
    <div class="radio-note">
      <p id="btRunNote">Bluetooth is running on the <b id="btRadio">…</b>. <span id="btOther"></span></p>
      <p id="btOnNote" hidden>Bluetooth is off. <button class="btn small" id="btOn"><span class="label">Turn on</span></button></p>
      <span class="msg" id="btMsg"></span>
      <button class="btn small" id="tryRadio"><span class="label">Use built-in radio</span></button>
    </div>
```

CSS in `index.html`'s `<style>`:

```css
  .bt.off .group { opacity: .45; pointer-events: none; }
  .pairbox { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 12px; margin: 2px 0 8px;
    background: var(--raised); border: 1px solid var(--line); border-radius: 8px; }
  .pairbox .pin { font: 600 18px/1 var(--display); letter-spacing: .08em; }
  .pairbox input { width: 120px; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--line);
    background: var(--panel); color: inherit; font: inherit; }
```

Check that `.radio-note` lays out the new `p`, the message and the button cleanly. Adjust its flex rules if the message no longer sits inside the `p`.

JS in the Bluetooth section:
- Replace the `#btSearch` handler and the `#nearby` click handler.
- In `loadBt`, call `renderPower()` after `renderRadio()`.
- In `go()`, add `if (id !== "bt") stopSearch();`.

```js
let searching = false, pairingRow = null;
const fmtPin = p => p && p.length === 6 ? `${p.slice(0, 3)} ${p.slice(3)}` : (p || "");
function renderPower() {
  const on = BT.power !== "off", sw = $("#btPower");
  sw.setAttribute("aria-checked", String(on));
  sw.classList.toggle("on", on);
  anime.animate($("i", sw), { x: on ? 16 : 0, duration: reduce ? 0 : 180, ease });
  $("#bt").classList.toggle("off", !on);
  $("#btRunNote").hidden = !on;
  $("#btOnNote").hidden = on;
  if (!on) stopSearch();
}
$("#btPower").addEventListener("click", async function () {
  if (this.disabled || !BT) return;
  const on = BT.power === "off";
  this.disabled = true;
  try {
    BT.power = (await call("bt_power", on)).power; renderPower();
    setMsg($("#btMsg"), on ? "Bluetooth is on." : "Bluetooth is off.");
    if (on) loadBt();
  } catch (e) { setMsg($("#btMsg"), e.message, true); }
  finally { this.disabled = false; }
});
$("#btOn").addEventListener("click", () => $("#btPower").click());

function endSearch(found) {
  if (!searching) return;
  searching = false;
  const b = $("#btSearch"); b.disabled = false; swap(b, "Search again"); $("#btProg").hidden = true;
  if (!found && !pairingRow) setMsg($("#btMsg"), "No devices found. Put the device in pairing mode and search again.");
}
function stopSearch() {
  if (!searching) return;
  call("bt_search_stop").catch(() => {});
  endSearch(true);
}
$("#btSearch").addEventListener("click", async function () {
  if (searching || this.disabled) return;
  this.disabled = true;
  try { await call("bt_search_start"); }
  catch (e) { this.disabled = false; return setMsg($("#btMsg"), e.message, true); }
  searching = true; swap(this, "Searching…"); $("#btProg").hidden = false; setMsg($("#btMsg"), "");
});
// the whole current list arrives each time: add newcomers, drop devices that left (never the one being paired)
window.onBtNearby = ({ devices, done }) => {
  const list = $("#nearby"), ids = new Set(devices.map(d => d.id));
  $$(".row", list).forEach(r => { if (!ids.has(r.dataset.id) && r !== pairingRow && r.style.display !== "none") removeEl(r); });
  const have = new Set($$(".row", list).map(r => r.dataset.id));
  devices.filter(d => !have.has(d.id)).forEach(d => addEl(list, nearbyRow(d)));
  if (done) endSearch(devices.length > 0);
};

function closePrompt() { const box = $("#nearby .pairbox"); if (box) box.remove(); }
window.onPairPrompt = ({ kind, pin }) => {
  const r = pairingRow; if (!r) return;
  closePrompt();
  const p = `<b class="pin">${esc(fmtPin(pin))}</b>`;
  const html = kind === "confirm"
    ? `<div class="pairbox"><span>Does the device show ${p}?</span><button class="btn small yes"><span class="label">Yes, pair</span></button><button class="btn small no"><span class="label">Cancel</span></button></div>`
    : kind === "display"
    ? `<div class="pairbox"><span>Type ${p} on the device, then press Enter.</span></div>`
    : `<div class="pairbox"><label for="pinIn">Enter the device's PIN</label><input id="pinIn" maxlength="16" autocomplete="off" placeholder="Often 0000 or 1234"><button class="btn small yes"><span class="label">Pair</span></button><button class="btn small no"><span class="label">Cancel</span></button></div>`;
  r.insertAdjacentHTML("afterend", html);
  const box = r.nextElementSibling, input = $("#pinIn", box);
  arrive(box);
  const reply = ok => { call("bt_pair_answer", ok, input ? input.value.trim() : null).catch(() => {});
    $$("button, input", box).forEach(x => x.disabled = true); };
  if (input) { input.focus(); input.addEventListener("keydown", e => { if (e.key === "Enter") $(".yes", box).click(); }); }
  $(".yes", box)?.addEventListener("click", () => { if (input && !input.value.trim()) return input.focus(); reply(true); });
  $(".no", box)?.addEventListener("click", () => reply(false));
};

// pairing moves the device from Nearby into Paired
$("#nearby").addEventListener("click", async e => {
  const b = e.target.closest(".pair"); if (!b || b.disabled || pairingRow) return;
  const r = b.closest(".row");
  pairingRow = r; stopSearch();
  setMsg($("#btMsg"), "Pairing. This can take up to a minute.");
  let d;
  try { d = await busy(b, "Pairing…", call("bt_pair", r.dataset.id)); }
  catch (err) { closePrompt(); pairingRow = null; return setMsg($("#btMsg"), err.message, true); }
  closePrompt(); pairingRow = null;
  setMsg($("#btMsg"), `Paired with ${r.dataset.name}.`);
  removeEl(r);
  d = d || { id: r.dataset.id, ids: [r.dataset.id], name: r.dataset.name, kind: r.dataset.kind, connected: false };
  const old = $$("#paired .row").find(x => x.dataset.id === d.id); if (old) old.remove();
  addEl($("#paired"), pairedRow(d)); countPaired();
});
```

`renderRadio` used to put the admin message into `#btMsg`. That still works: `#btMsg` is now a sibling of the notes.

- [ ] **Step 4: Run tests**

Run `py -3.10 -m pytest tests/ui -q`. Every UI test passes, the old ones included.

- [ ] **Step 5: Commit**

```bash
git add ui/index.html ui/shared.css tests/ui/test_ui.py
git commit -m "feat(ui): Bluetooth on/off switch, live search and inline pairing prompts"
```

---

### Task 6: Widget on/off switch

**Files:**
- Modify: `ui/widget.html`
- Test: `tests/ui/test_widget.py`

- [ ] **Step 1: Failing test** (append to `tests/ui/test_widget.py`; it uses that file's existing page fixture)

```python
def test_widget_bluetooth_power(open_widget):
    pg = open_widget()
    sw = pg.locator("#btPower")
    expect(sw).to_have_attribute("aria-checked", "true")
    sw.click()
    expect(sw).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#btDev")).to_have_text("Bluetooth is off")
    sw.click()
    expect(sw).to_have_attribute("aria-checked", "true")
```

Use the fixture name that `tests/ui/test_widget.py` actually defines. Read it first.

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement**

Add the markup `<button class="switch on" id="btPower" role="switch" aria-checked="true" aria-label="Bluetooth"><i></i></button>` before `#btVer`. In `loadBt()`, after `BT = radio;`:

```js
  const on = BT.power !== "off", sw = $("#btPower");
  sw.setAttribute("aria-checked", String(on)); sw.classList.toggle("on", on);
  anime.animate($("i", sw), { x: on ? 16 : 0, duration: reduce ? 0 : 180, ease });
```

Set `#btDev` to `on ? (dev ? dev.name : "No device connected") : "Bluetooth is off"`. Add the handler:

```js
$("#btPower").addEventListener("click", async function () {
  if (this.disabled || !BT) return;
  this.disabled = true;
  try { await call("bt_power", BT.power === "off"); } catch (e) { note($("#btMsg"), e.message, true); }
  finally { this.disabled = false; }
  loadBt().catch(fail($("#btMsg")));
});
```

- [ ] **Step 4: Run** `py -3.10 -m pytest tests/ui -q`. It passes.

- [ ] **Step 5: Commit** with `git commit -m "feat(widget): Bluetooth on/off switch"`.

---

### Task 7: Hardware check, docs, build, release 1.0.2

**Files:**
- Modify: `README.md`, `docs/superpowers/test-reports/manual-checklist.md`, `bt.py` (`SERVICE_TOGGLE`, if the check decides it), `version.py` (after release)

- [ ] **Step 1: Full suite:** run `py -3.10 -m pytest -q` and `py -3.10 -m pytest -m hardware -q`. Everything passes.
- [ ] **Step 2: Real-hardware check with the user.** Run the app from source (`py -3.10 app.py --no-elevate`), or a fresh build. The user:
  - (a) puts the OnePlus buds in pairing mode, with the phone's Bluetooth off, then searches and pairs. Expect: Paired, and connected.
  - (b) pairs a phone. Expect the confirm-PIN panel.
  - (c) uses Disconnect/Connect on a paired speaker. Watch `app.log` for which way worked.
  - (d) toggles on/off.

  Record the results in `manual-checklist.md`. If KS worked in (c), leave `SERVICE_TOGGLE` as the fallback. If neither KS nor the toggle worked, keep the settings fallback and note it in the README.
- [ ] **Step 3: Update the README.**
  - Features: live search, PIN prompts, on/off, audio connect.
  - Known limitations: replace the "Bluetooth audio Connect" bullet with the measured result.
  - Badge and test counts: update both.
  - Requirements: no change.
- [ ] **Step 4: Build:** run `py -3.10 build_exe.py`. Expect `version 1.0.2: release it as v1.0.2`. Then smoke-test the exe:
  - Start it with `--no-elevate` and confirm it stays running.
  - Open the Bluetooth page and check that the paired list loads and search works. That proves winrt is bundled.
  - Stop only the PIDs you started.

  If PyInstaller misses winrt modules, add `"--collect-submodules", "winrt"` to `build_exe.py`.
- [ ] **Step 5: Commit and push.** Commit the README, checklist, build script and spec tweaks, then push.
- [ ] **Step 6: Release:**

  ```bash
  gh release create v1.0.2 dist\UnigenManager.exe --target main --title "Unigen Manager 1.0.2" --notes-file <notes>
  ```

  The notes cover what's new, plug and play steps, upgrade steps and the SHA-256. Then verify that `releases/latest/download/UnigenManager.exe` hashes to the built file.
- [ ] **Step 7: Update the installed copy.**
  1. Quit the tray app (the user, or `schtasks /End /TN "Unigen Manager"`).
  2. Copy the exe over `C:\Program Files\Unigen Manager\UnigenManager.exe` from an elevated prompt (`Start-Process -Verb RunAs`).
  3. Start it with `Start-ScheduledTask -TaskName "Unigen Manager"`.
- [ ] **Step 8: Bump the version.** Set `version.py` `VERSION = "1.0.3"`, then commit and push.
