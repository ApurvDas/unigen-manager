"""Wi-Fi: parse netsh output, identify adapters, and act on networks and saved profiles."""
import re


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
