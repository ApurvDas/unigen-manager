"""Bluetooth: radios (switch with rollback), devices (list, pair, remove), audio connect/disconnect."""
import ctypes, logging, os, threading, time, uuid
from ctypes import wintypes

import btwinrt
import pnp, winrun
from btwinrt import BtError
from wifi import ADAPTER_NAMES

_set = pnp.set_enabled  # tests replace this
_switch_lock = threading.Lock()
SERVICE_TOGGLE = True  # Way 2 of audio connect; the hardware check in Task 7 decides whether it stays.
_OFF_WAIT = 45  # s: disabling a radio tears down its paired devices' audio first, which can take 25 s
LMP = {6: "4.0", 7: "4.1", 8: "4.2", 9: "5.0", 10: "5.1", 11: "5.2", 12: "5.3", 13: "5.4", 14: "6.0"}
AUDIO_SERVICES = ["0000110B-0000-1000-8000-00805F9B34FB", "0000111E-0000-1000-8000-00805F9B34FB"]  # A2DP sink, Hands-free


def version(lmp):
    return LMP.get(lmp)


def radio_key(instance_id, name):
    up = instance_id.upper()
    if "VID_368B&PID_8D81" in up:
        return "unigen"
    if "VID_13D3&PID_3563" in up or "MEDIATEK" in name.upper():
        return "builtin"
    return instance_id


def radios():
    return [{"key": radio_key(r["id"], r["name"]), "id": r["id"], "name": r["name"], "ok": r["status"] == "OK",
             "disabled": r["problem"] in ("CM_PROB_DISABLED", "22"), "version": version(r["lmp"]),
             "failed": r["problem"] not in ("CM_PROB_NONE", "CM_PROB_DISABLED", "22")} for r in _radio_rows()]


def _radio_rows():
    """Bluetooth radios (devices that report an LMP version), from SetupAPI: milliseconds, no PowerShell."""
    return [r for r in pnp.list_devices() if r["lmp"] is not None]


def _radio_up():
    """Windows has a working radio. Device Manager says "OK" for a crashed one too; this tells them apart. Tests replace it."""
    lib, k32 = ctypes.WinDLL("bthprops.cpl"), ctypes.WinDLL("kernel32")
    lib.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    radio, params = wintypes.HANDLE(), _RADIO_PARAMS(ctypes.sizeof(_RADIO_PARAMS))
    find = lib.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not find:
        return False
    lib.BluetoothFindRadioClose(wintypes.HANDLE(find))
    k32.CloseHandle(radio)
    return True


def _label(key):
    return ADAPTER_NAMES.get(key, key)


class StuckRadio(BtError):
    """The old radio didn't finish turning off; str(e) says what to do."""


class NotPairedHere(BtError):
    """The radio in use doesn't know the device: re-pairing fixes it, Windows Settings can't."""


def switch(target, **kw):
    if not _switch_lock.acquire(blocking=False):
        raise BtError("A radio switch is already running.")
    try:
        return _switch(target, **kw)
    finally:
        _switch_lock.release()


def _switch(target, *, wait=20.0, clock=time.monotonic, sleep=time.sleep):
    rs = radios()
    tgt = next((r for r in rs if r["key"] == target), None)
    if tgt is None:
        raise BtError("That Bluetooth radio isn't connected to this PC.")
    others = [r for r in rs if r["ok"] and r["key"] != target]
    if tgt["ok"] and not others and _radio_up():
        return target
    try:
        for r in others:  # Windows runs one Bluetooth radio at a time
            _set(r["id"], False, wait=_OFF_WAIT)
    except winrun.CmdError:  # it's mid-teardown: turning it back on is what hung the dongle's driver, so leave it
        raise StuckRadio(f"Windows didn't finish turning off the {_label(others[0]['key'])} radio. Switch again in a "
                         "minute; if Bluetooth stays off, re-plug the dongle or restart the PC.") from None
    try:
        if tgt["failed"]:  # never started (e.g. code 10): restart it. A stopping radio has no problem code and is left alone
            _set(tgt["id"], False)
        _set(tgt["id"], True)
        deadline = clock() + wait
        while clock() < deadline:
            if any(r["key"] == target and r["ok"] for r in radios()) and _radio_up():  # one radio runs at a time
                return target
            sleep(1)
    except winrun.CmdError:
        pass
    if others:  # never leave the user without Bluetooth: best-effort restore, each step on its own
        try:
            _set(tgt["id"], False, wait=_OFF_WAIT)
        except winrun.CmdError:
            pass
    for r in others:
        try:
            _set(r["id"], True)
        except winrun.CmdError:
            pass
    logging.getLogger("unigen").warning("radio %s didn't start; radios now: %s", target, radios())
    back = f" Switched back to the {_label(others[0]['key'])}." if others else ""
    raise BtError(f"The {_label(target)} radio didn't start.{back}")


pair, power, set_power, here_id = btwinrt.pair, btwinrt.power, btwinrt.set_power, btwinrt.here_id


def devices():
    """Paired devices; connected ones get the battery % Windows last heard (None when the device doesn't report it).
    Disconnected ones never do: Windows keeps the old value."""
    rows = btwinrt.paired()
    try:
        levels = pnp.battery_levels()
    except OSError as e:
        logging.getLogger("unigen").warning("battery read failed: %s", e)
        levels = {}
    for r in rows:
        r["battery"] = levels.get(r["address"]) if r["connected"] else None
    return rows
search_start, search_stop = btwinrt.search_start, btwinrt.search_stop


def remove(ids):
    for i in ids:  # a device's classic and LE records are both paired
        btwinrt.unpair(i)


# ---- audio connect, way 2: bthprops.cpl service toggle ----
class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in
                ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("Address", ctypes.c_ulonglong), ("ulClassofDevice", wintypes.ULONG),
                ("fConnected", wintypes.BOOL), ("fRemembered", wintypes.BOOL), ("fAuthenticated", wintypes.BOOL),
                ("stLastSeen", _SYSTEMTIME), ("stLastUsed", _SYSTEMTIME), ("szName", wintypes.WCHAR * 248)]


class _RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


def _service_changed(rc):
    """True if the service state was set, False if the device lacks the service (1060, e.g. no hands-free)."""
    if rc == 1060:
        return False
    if rc:
        raise BtError(f"Windows refused (error {rc}).")
    return True


def _set_audio(address_hex, flags):
    """Set the audio services of a paired device: [0, 1] makes Windows reconnect it, [0] disconnects it."""
    lib, k32 = ctypes.WinDLL("bthprops.cpl"), ctypes.WinDLL("kernel32")
    lib.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    radio, params = wintypes.HANDLE(), _RADIO_PARAMS(ctypes.sizeof(_RADIO_PARAMS))
    find = lib.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not find:
        raise BtError("No Bluetooth radio is on.")
    lib.BluetoothFindRadioClose(wintypes.HANDLE(find))
    try:
        info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO), Address=int(address_hex, 16))
        if lib.BluetoothGetDeviceInfo(radio, ctypes.byref(info)):
            raise NotPairedHere("Windows doesn't know that device.")
        def set_state(g, flag):
            guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(g).bytes_le)
            return lib.BluetoothSetServiceState(radio, ctypes.byref(info), ctypes.byref(guid), flag)
        _apply_services(set_state, flags)
    finally:
        k32.CloseHandle(radio)


def _apply_services(set_state, flags):
    """Run set_state(service, flag) -> Win32 rc over every audio service. A failure after a service was turned
    off turns them all back on, so a half-done connect never leaves the device without audio."""
    changed = disabled = False
    try:
        for flag in flags:
            for g in AUDIO_SERVICES:
                ok = _service_changed(set_state(g, flag))
                changed |= ok
                disabled |= ok and flag == 0
        if not changed:
            raise BtError("That device has no audio connection to switch.")
    except BtError:
        if disabled and 1 in flags:
            for g in AUDIO_SERVICES:
                try:
                    set_state(g, 1)
                except Exception:
                    pass
        raise


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
    verb = "connect" if connect else "disconnect"
    if not _radio_up():
        raise BtError(f"No Bluetooth radio is working, so {name} can't {verb}. Switch adapters again, or re-plug the dongle.")
    ways = [lambda: _ks_oneshot(address_hex, connect)]
    if SERVICE_TOGGLE:
        ways.append(lambda: _set_audio(address_hex, [0, 1] if connect else [0]))
    unknown = False
    for way in ways:
        try:
            way()
            return
        except (BtError, OSError, ValueError, ctypes.ArgumentError, AttributeError) as e:
            logging.getLogger("unigen").warning("audio %s failed: %s: %s", verb, type(e).__name__, e)
            unknown = unknown or isinstance(e, NotPairedHere)
    if unknown:
        raise NotPairedHere(f"This Bluetooth radio doesn't know {name}. Put it in pairing mode, then press Re-pair.")
    if open_settings is None:
        raise BtError(f"Windows didn't let the app {verb} {name}.")
    open_settings("ms-settings:bluetooth")
    raise BtError(f"Windows didn't let the app {verb} {name}. Bluetooth settings are open so you can do it there.")


def connect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, True, open_settings)


def disconnect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, False, open_settings)
