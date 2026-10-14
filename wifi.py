"""Wi-Fi: parse netsh output, identify adapters, and act on networks and saved profiles."""
import ctypes
import pathlib
import re
import tempfile
import threading
import time
import uuid
from ctypes import wintypes
from xml.sax.saxutils import escape

import winrun


class ParseError(Exception):
    pass


class WifiError(Exception):
    pass


NOT_ENGLISH = "Couldn't read the Wi-Fi status. Is Windows set to English?"


def _kv(line):
    """'    Key   : value' -> ('Key', 'value'); None when the line has no colon."""
    if ":" not in line:
        return None
    k, v = line.split(":", 1)
    return k.strip(), v.strip()


def _pct(v):
    return int(v.rstrip("%").strip())


_IFACE_FIELDS = {
    "Description": ("description", str), "GUID": ("guid", str), "State": ("state", str),
    "SSID": ("ssid", str), "BSSID": ("bssid", str), "Radio type": ("radio", str),
    "Authentication": ("auth", str), "Channel": ("channel", int), "Receive rate (Mbps)": ("rx", float),
    "Transmit rate (Mbps)": ("tx", float), "Signal": ("signal", _pct), "Profile": ("profile", str),
}


def parse_interfaces(text):
    out, cur = [], None
    for line in text.splitlines():
        kv = _kv(line)
        if not kv:
            continue
        k, v = kv
        if k == "Name":
            cur = {"name": v}
            out.append(cur)
        elif cur is not None and k in _IFACE_FIELDS:
            key, conv = _IFACE_FIELDS[k]
            cur[key] = conv(v)
    if any("description" not in i or "state" not in i for i in out):
        raise ParseError(NOT_ENGLISH)
    if not out and text.strip() and "There is no wireless interface" not in text:
        raise ParseError(NOT_ENGLISH)
    return out


def band(channel):
    return 2.4 if channel <= 14 else 5


def parse_networks(text):
    nets, net, ap = [], None, None
    for line in text.splitlines():
        kv = _kv(line)
        if not kv:
            continue
        k, v = kv
        if re.fullmatch(r"SSID \d+", k):
            net, ap = {"ssid": v, "auth": None, "aps": []}, None
            nets.append(net)
        elif net is None:
            continue
        elif k == "Authentication":
            net["auth"] = v
        elif re.fullmatch(r"BSSID \d+", k):
            ap = {"bssid": v}
            net["aps"].append(ap)
        elif ap is not None and k == "Signal":
            ap["signal"] = _pct(v)
        elif ap is not None and k == "Radio type":
            ap["radio"] = v
        elif ap is not None and k == "Channel":
            ap["channel"] = int(v)
            ap["band"] = band(ap["channel"])
    return nets


def parse_profiles(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.fullmatch(r"Profiles on interface (.+):", line.strip())
        if m:
            cur = out.setdefault(m.group(1), [])
            continue
        kv = _kv(line)
        if cur is not None and kv and kv[0] in ("All User Profile", "Current User Profile"):
            cur.append(kv[1])
    return out


def parse_key(text):
    for line in text.splitlines():
        kv = _kv(line)
        if kv and kv[0] == "Key Content":
            return kv[1]
    return None


def parse_drivers(text):
    out, cur = {}, None
    for line in text.splitlines():
        kv = _kv(line)
        if kv and kv[0] == "Interface name":
            cur = out[kv[1]] = {"radio_types": [], "wpa3": False}
        elif cur is None:
            continue
        elif kv and kv[0] == "Radio types supported":
            cur["radio_types"] = kv[1].split()
        elif "WPA3-Personal" in line:
            cur["wpa3"] = True
    return out


_STANDARDS = [("802.11be", "Wi-Fi 7"), ("802.11ax", "Wi-Fi 6"), ("802.11ac", "Wi-Fi 5"), ("802.11n", "Wi-Fi 4")]


def wifi_standard(radio_types):
    return next((name for std, name in _STANDARDS if std in radio_types), None)


_run = winrun.run  # tests replace this
NETSH = "netsh"
ADAPTER_NAMES = {"unigen": "Unigen dongle", "builtin": "Built-in MediaTek"}


def adapter_key(description):
    if "AIC8800" in description:
        return "unigen"
    if "MT7921" in description:
        return "builtin"
    return description


def security_kind(auth):
    return {"Open": "open", "WPA2-Personal": "wpa2"}.get(auth)


def check_password(pw):
    if re.fullmatch(r"[0-9A-Fa-f]{64}", pw or "") or (pw and 8 <= len(pw) <= 63 and all(32 <= ord(c) <= 126 for c in pw)):
        return
    raise WifiError("The password must be 8 to 63 characters.")


def profile_name(ssid):
    return ssid.replace('"', "'")  # netsh can't take a quote inside name=


def profile_xml(ssid, kind, password, name):
    if kind == "open":
        security = ("<authEncryption><authentication>open</authentication><encryption>none</encryption>"
                    "<useOneX>false</useOneX></authEncryption>")
    else:
        key_type = "networkKey" if re.fullmatch(r"[0-9A-Fa-f]{64}", password) else "passPhrase"
        security = ("<authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption>"
                    "<useOneX>false</useOneX></authEncryption>"
                    f"<sharedKey><keyType>{key_type}</keyType><protected>false</protected>"
                    f"<keyMaterial>{escape(password)}</keyMaterial></sharedKey>")
    return ('<?xml version="1.0"?>\n'
            '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
            f"<name>{escape(name)}</name>"
            f"<SSIDConfig><SSID><hex>{ssid.encode('utf-8').hex().upper()}</hex><name>{escape(ssid)}</name></SSID></SSIDConfig>"
            "<connectionType>ESS</connectionType><connectionMode>auto</connectionMode>"
            f"<MSM><security>{security}</security></MSM></WLANProfile>")


def interfaces():
    return parse_interfaces(_run([NETSH, "wlan", "show", "interfaces"]))


def networks(iface):
    return parse_networks(_run([NETSH, "wlan", "show", "networks", "mode=bssid", f"interface={iface}"]))


def profiles():
    return parse_profiles(_run([NETSH, "wlan", "show", "profiles"]))


def drivers():
    return parse_drivers(_run([NETSH, "wlan", "show", "drivers"]))


class _NOTIF(ctypes.Structure):  # WLAN_NOTIFICATION_DATA
    _fields_ = [("source", wintypes.DWORD), ("code", wintypes.DWORD), ("guid", ctypes.c_ubyte * 16),
                ("size", wintypes.DWORD), ("data", ctypes.c_void_p)]


_NOTIFY = ctypes.WINFUNCTYPE(None, ctypes.POINTER(_NOTIF), ctypes.c_void_p)
_ACM, _SCAN_DONE, _SCAN_FAIL = 8, 7, 8  # WLAN_NOTIFICATION_SOURCE_ACM, wlan_notification_acm_scan_complete/_fail


def trigger_scan(guid, wait=0.0):
    """Ask the adapter for a fresh scan (netsh only shows Windows' cached list). With wait, return once Windows
    says the scan finished (about 1.5 s) or after wait seconds."""
    wlan = ctypes.WinDLL("wlanapi")
    handle, version = wintypes.HANDLE(), wintypes.DWORD()
    if wlan.WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(handle)):
        raise WifiError("Couldn't start a Wi-Fi scan.")
    g = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
    done = threading.Event()

    @_NOTIFY
    def on_note(n, _ctx):
        if n.contents.source == _ACM and n.contents.code in (_SCAN_DONE, _SCAN_FAIL) and bytes(n.contents.guid) == bytes(g):
            done.set()
    try:
        if wait:
            wlan.WlanRegisterNotification(handle, _ACM, False, on_note, None, None, None)
        rc = wlan.WlanScan(handle, ctypes.byref(g), None, None, None)
        if rc:
            raise WifiError(f"Couldn't start a Wi-Fi scan (error {rc}).")
        done.wait(wait)
    finally:
        wlan.WlanCloseHandle(handle, None)  # also drops the notification, after any running callback


def scan(iface, guid, *, wait=4.0):
    trigger_scan(guid, wait)
    return networks(iface)


def _state(iface):
    return next((i for i in interfaces() if i["name"] == iface), {})


def connect(iface, ssid, *, auth=None, password=None, saved=False, timeout=15.0, clock=time.monotonic, sleep=time.sleep):
    name, created, kind = profile_name(ssid), False, None
    if not saved:
        kind = security_kind(auth)
        if kind is None:
            raise WifiError(f"{ssid} uses {auth}, which this app can't set up yet. Use Windows settings.")
        if kind != "open":
            check_password(password)
        with tempfile.TemporaryDirectory() as d:  # the password file never outlives this block
            path = pathlib.Path(d, "profile.xml")
            path.write_text(profile_xml(ssid, kind, password, name), encoding="utf-8")
            _run([NETSH, "wlan", "add", "profile", f"filename={path}", f"interface={iface}", "user=all"])
        created = True
    try:
        _run([NETSH, "wlan", "connect", f"name={name}", f"interface={iface}"])
        deadline = clock() + timeout
        while clock() < deadline:
            st = _state(iface)
            if st.get("state") == "connected" and st.get("ssid") == ssid:
                return st
            sleep(1)
    except winrun.CmdError:
        if created:
            delete_profile(name, [iface])
        raise
    if created:
        delete_profile(name, [iface])
    raise WifiError(f"Couldn't connect to {ssid}." + (" Check the password." if created and kind != "open" else ""))


def disconnect(iface):
    _run([NETSH, "wlan", "disconnect", f"interface={iface}"])


def password(iface, ssid):
    return parse_key(_run([NETSH, "wlan", "show", "profile", f"name={ssid}", f"interface={iface}", "key=clear"]))


def delete_profile(ssid, ifaces):
    for iface in ifaces:
        try:
            _run([NETSH, "wlan", "delete", "profile", f"name={ssid}", f"interface={iface}"])
        except winrun.CmdError:
            pass  # not saved on this adapter


def copy_profile(ssid, src_iface, dst_iface):
    with tempfile.TemporaryDirectory() as d:  # the exported file holds the clear key
        _run([NETSH, "wlan", "export", "profile", f"name={ssid}", f"interface={src_iface}", f"folder={d}", "key=clear"])
        files = list(pathlib.Path(d).glob("*.xml"))
        if len(files) != 1:
            raise WifiError(f"Couldn't export {ssid} from the {src_iface} adapter.")
        _run([NETSH, "wlan", "add", "profile", f"filename={files[0]}", f"interface={dst_iface}", "user=all"])
