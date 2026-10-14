"""Device Manager reads straight from SetupAPI: milliseconds instead of a PowerShell Get-PnpDevice (about 0.5-1 s).
Changing a device (enable/disable) still goes through PowerShell in hw.ps1, which needs admin anyway."""
import ctypes, re, uuid
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
    """Present Wi-Fi/Ethernet and Bluetooth devices on USB or PCI, disabled ones included, in the shape bt.ps1 and
    hw.ps1 used to print: {"id", "name", "status": "OK" | "Error", "problem": "CM_PROB_NONE" | "CM_PROB_DISABLED" | "<n>",
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
