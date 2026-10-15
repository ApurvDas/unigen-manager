"""Device Manager reads straight from SetupAPI: milliseconds instead of a PowerShell Get-PnpDevice (about 0.5-1 s).
Changing a device (enable/disable) is set_enabled below: the class-installer call Device Manager makes, no PowerShell."""
import ctypes, re, time, uuid
from ctypes import wintypes

CLASSES = {"net": "4d36e972-e325-11ce-bfc1-08002be10318", "bluetooth": "e0cbf06c-cd8b-4647-bb8a-263b43f0f974"}
_LMP_KEY = ("a92f26ca-eda7-4b1d-9db2-27b68aa5a2eb", 4)  # DEVPKEY_Bluetooth_RadioLmpVersion (a byte)
_BATTERY_KEY = ("104ea319-6ee2-4701-bd47-8ddbf425bbe5", 2)  # battery %, on a device's hands-free node (Windows Settings reads it)
_DIGCF_ALLCLASSES = 0x4
_DIGCF_PRESENT, _SPDRP_DEVICEDESC, _SPDRP_FRIENDLYNAME = 0x2, 0x0, 0xC
_DN_STARTED, _DN_HAS_PROBLEM, _CM_PROB_DISABLED = 0x8, 0x400, 22


class _GUID(ctypes.Structure):
    _fields_ = [("b", ctypes.c_ubyte * 16)]


def _guid(text):
    return _GUID((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le))


class _DEVINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("guid", _GUID), ("devinst", wintypes.DWORD), ("reserved", ctypes.c_void_p)]


class _PROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]


def _libs():
    sa, cm = ctypes.WinDLL("setupapi"), ctypes.WinDLL("cfgmgr32")
    sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    sa.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    sa.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DEVINFO)]
    sa.SetupDiGetDeviceInstanceIdW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DEVINFO), wintypes.LPWSTR, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD)]
    sa.SetupDiGetDeviceRegistryPropertyW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DEVINFO), wintypes.DWORD,
                                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
                                                     ctypes.POINTER(wintypes.DWORD)]
    sa.SetupDiGetDevicePropertyW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DEVINFO), ctypes.POINTER(_PROPKEY),
                                             ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    cm.CM_Get_DevNode_Status.argtypes = [ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.ULONG), wintypes.DWORD,
                                         wintypes.ULONG]
    cm.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR, wintypes.ULONG]
    return sa, cm


def _name(sa, h, dev):
    buf = ctypes.create_unicode_buffer(256)
    for prop in (_SPDRP_FRIENDLYNAME, _SPDRP_DEVICEDESC):
        if sa.SetupDiGetDeviceRegistryPropertyW(h, ctypes.byref(dev), prop, None, buf, ctypes.sizeof(buf), None):
            return buf.value
    return ""


def _byte_prop(sa, h, dev, prop):
    key, kind, val = _PROPKEY(_guid(prop[0]), prop[1]), wintypes.ULONG(), ctypes.c_ubyte()
    if sa.SetupDiGetDevicePropertyW(h, ctypes.byref(dev), ctypes.byref(key), ctypes.byref(kind), ctypes.byref(val), 1, None, 0):
        return val.value
    return None


def list_devices():
    """Present Wi-Fi/Ethernet and Bluetooth devices on USB or PCI, disabled ones included, as
    {"id", "name", "status": "OK" | "Error", "problem": "CM_PROB_NONE" | "CM_PROB_DISABLED" | "<n>",
    "lmp": int | None}."""
    sa, cm = _libs()
    out = []
    for cls in CLASSES.values():
        g = _guid(cls)
        h = sa.SetupDiGetClassDevsW(ctypes.byref(g), None, None, _DIGCF_PRESENT)
        if not h or h == ctypes.c_void_p(-1).value:
            continue
        try:
            i = 0
            while True:
                dev = _DEVINFO(cbSize=ctypes.sizeof(_DEVINFO))
                if not sa.SetupDiEnumDeviceInfo(h, i, ctypes.byref(dev)):
                    break
                i += 1
                buf = ctypes.create_unicode_buffer(512)
                if not sa.SetupDiGetDeviceInstanceIdW(h, ctypes.byref(dev), buf, 512, None):
                    continue
                inst = buf.value
                if not inst.upper().startswith(("USB\\", "PCI\\")):
                    continue
                status, problem = wintypes.ULONG(), wintypes.ULONG()
                cm.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem), dev.devinst, 0)
                bad = bool(status.value & _DN_HAS_PROBLEM)
                ok = not bad and bool(status.value & _DN_STARTED)
                code = problem.value if bad else 0
                out.append({"id": inst, "name": _name(sa, h, dev), "status": "OK" if ok else "Error",
                            "problem": "CM_PROB_NONE" if not code else "CM_PROB_DISABLED" if code == _CM_PROB_DISABLED else str(code),
                            "lmp": _byte_prop(sa, h, dev, _LMP_KEY) if cls == CLASSES["bluetooth"] else None})
        finally:
            sa.SetupDiDestroyDeviceInfoList(h)
    return out


class _PROPCHANGE(ctypes.Structure):  # SP_PROPCHANGE_PARAMS, with its SP_CLASSINSTALL_HEADER inlined
    _fields_ = [("cbSize", wintypes.DWORD), ("InstallFunction", wintypes.DWORD), ("StateChange", wintypes.DWORD),
                ("Scope", wintypes.DWORD), ("HwProfile", wintypes.DWORD)]


class _INSTALLPARAMS(ctypes.Structure):  # SP_DEVINSTALL_PARAMS_W
    _fields_ = [("cbSize", wintypes.DWORD), ("Flags", wintypes.DWORD), ("FlagsEx", wintypes.DWORD), ("hwndParent", wintypes.HWND),
                ("InstallMsgHandler", ctypes.c_void_p), ("InstallMsgHandlerContext", ctypes.c_void_p),
                ("FileQueue", ctypes.c_void_p), ("ClassInstallReserved", ctypes.c_size_t), ("Reserved", wintypes.DWORD),
                ("DriverPath", wintypes.WCHAR * 260)]


_DIF_PROPERTYCHANGE, _DICS_ENABLE, _DICS_DISABLE, _DICS_FLAG_GLOBAL = 0x12, 1, 2, 1
_DI_NEEDRESTART, _DI_NEEDREBOOT = 0x80, 0x100


def _change(instance_id, on):
    """The class-installer call. Its result says little (a slow Bluetooth disable can fail or ask for a restart
    and still work), so set_enabled judges by the device's state. Raises winrun.CmdError with Windows' sentence."""
    from winrun import CmdError
    sa = ctypes.WinDLL("setupapi", use_last_error=True)
    sa.SetupDiCreateDeviceInfoList.restype = ctypes.c_void_p
    sa.SetupDiCreateDeviceInfoList.argtypes = [ctypes.c_void_p, wintypes.HWND]
    sa.SetupDiOpenDeviceInfoW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD, ctypes.POINTER(_DEVINFO)]
    sa.SetupDiSetClassInstallParamsW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DEVINFO), ctypes.c_void_p, wintypes.DWORD]
    sa.SetupDiCallClassInstaller.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(_DEVINFO)]
    sa.SetupDiGetDeviceInstallParamsW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DEVINFO), ctypes.POINTER(_INSTALLPARAMS)]
    sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

    def fail():
        err = ctypes.get_last_error()
        text = ctypes.FormatError(err).strip() if err < 0x80000000 else ""
        raise CmdError(text or f"Windows couldn't change the device (error 0x{err:08X}).")
    h = sa.SetupDiCreateDeviceInfoList(None, None)
    if not h or h == ctypes.c_void_p(-1).value:
        fail()
    try:
        dev = _DEVINFO(cbSize=ctypes.sizeof(_DEVINFO))
        if not sa.SetupDiOpenDeviceInfoW(h, instance_id, None, 0, ctypes.byref(dev)):
            fail()
        p = _PROPCHANGE(8, _DIF_PROPERTYCHANGE, _DICS_ENABLE if on else _DICS_DISABLE, _DICS_FLAG_GLOBAL, 0)
        if not (sa.SetupDiSetClassInstallParamsW(h, ctypes.byref(dev), ctypes.byref(p), ctypes.sizeof(p))
                and sa.SetupDiCallClassInstaller(_DIF_PROPERTYCHANGE, h, ctypes.byref(dev))):
            fail()
        ip = _INSTALLPARAMS(cbSize=ctypes.sizeof(_INSTALLPARAMS))
        if sa.SetupDiGetDeviceInstallParamsW(h, ctypes.byref(dev), ctypes.byref(ip)) and ip.Flags & (_DI_NEEDRESTART | _DI_NEEDREBOOT):
            raise CmdError("Windows needs a restart to finish changing that device.")
    finally:
        sa.SetupDiDestroyDeviceInfoList(h)


def _status(instance_id):
    """(status, problem) flags of a device, or None if Windows doesn't know it."""
    _, cm = _libs()
    node, status, problem = wintypes.DWORD(), wintypes.ULONG(), wintypes.ULONG()
    if cm.CM_Locate_DevNodeW(ctypes.byref(node), instance_id, 0) or cm.CM_Get_DevNode_Status(
            ctypes.byref(status), ctypes.byref(problem), node, 0):
        return None
    return status.value, problem.value


def _reached(state, on):
    """enabled = started with no problem; disabled = problem 22 (CM_PROB_DISABLED)."""
    if state is None:
        return False
    status, problem = state
    if on:
        return bool(status & _DN_STARTED) and not status & _DN_HAS_PROBLEM
    return bool(status & _DN_HAS_PROBLEM) and problem == _CM_PROB_DISABLED


def set_enabled(instance_id, on, wait=30.0, *, sleep=time.sleep, clock=time.monotonic, retry=3.0):
    """Enable or disable a device the way Device Manager does (it stays that way after a restart). Admin only.
    Success is the device reaching the wanted state within `wait` seconds, whatever the call returned.
    Windows refuses to remove a Bluetooth radio while something holds a paired device's audio driver open (it gives
    up after 7-21 s and flags the radio "needs restart"); the next call then goes through at once. So if the state hasn't
    arrived `retry` seconds after a call, the call is made again. (Not sooner: Windows is still tearing the radio's
    devices down after a refusal, and a call in the middle of that hung the dongle's Bluetooth driver for good.)
    A device already in the wanted state is left alone.
    Raises winrun.CmdError with Windows' sentence, or "The device didn't turn on/off."."""
    from winrun import CmdError
    if _reached(_status(instance_id), on):
        return
    deadline = clock() + wait
    while True:
        err = None
        try:
            _change(instance_id, on)
        except CmdError as e:
            err = e
        again = clock() + retry
        while not _reached(_status(instance_id), on):
            if clock() >= deadline:
                raise err or CmdError(f"The device didn't turn {'on' if on else 'off'}.")
            if clock() >= again:
                break  # ask again: a refused change usually goes through on the next call
            sleep(0.25)
        else:
            return


def address_from_instance(instance_id):
    """The remote device's Bluetooth address in a BTHENUM/BTHLEDEVICE instance id (...&0&020000000013_C00000000)."""
    m = re.search(r"&([0-9A-F]{12})_", instance_id.upper())
    return m.group(1) if m and m.group(1) != "000000000000" else None


def battery_levels():
    """{address: percent} for paired devices whose last battery report Windows kept (hands-free devices)."""
    sa, _ = _libs()
    out = {}
    for enumerator in ("BTHENUM", "BTHLEDEVICE"):
        h = sa.SetupDiGetClassDevsW(None, enumerator, None, _DIGCF_PRESENT | _DIGCF_ALLCLASSES)
        if not h or h == ctypes.c_void_p(-1).value:
            continue
        try:
            i = 0
            while True:
                dev = _DEVINFO(cbSize=ctypes.sizeof(_DEVINFO))
                if not sa.SetupDiEnumDeviceInfo(h, i, ctypes.byref(dev)):
                    break
                i += 1
                buf = ctypes.create_unicode_buffer(512)
                if not sa.SetupDiGetDeviceInstanceIdW(h, ctypes.byref(dev), buf, 512, None):
                    continue
                addr, level = address_from_instance(buf.value), _byte_prop(sa, h, dev, _BATTERY_KEY)
                if addr and level is not None and level <= 100:
                    out[addr] = level
        finally:
            sa.SetupDiDestroyDeviceInfoList(h)
    return out


if __name__ == "__main__":  # compare with: Get-PnpDevice -PresentOnly -Class Net,Bluetooth
    for r in list_devices():
        print(r)
