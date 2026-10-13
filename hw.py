"""One switch for Wi-Fi and Bluetooth: which adapter is in use, and the Device Manager state that makes it stick."""
import json, logging, threading, time
from pathlib import Path

import bt, winrun, wifi

log = logging.getLogger("unigen")
_ps = winrun.ps  # tests replace this
_SCRIPT = Path(__file__).with_name("hw.ps1")


class HwError(Exception):
    """A switch could not finish; str(e) is safe to show the user and says where the user stands."""


def _call(action, **params):
    return json.loads(_ps(_SCRIPT.read_text(encoding="utf-8"), {"action": action, **params}, timeout=90))


def device_key(instance_id, name):
    """(adapter, kind) for a PnP device, or (None, None) for anything else (Ethernet, USB hubs, ...)."""
    up = instance_id.upper()
    if "VID_368B&PID_8D81" in up:
        return ("unigen", "wifi") if "MI_02" in up else ("unigen", "bt") if "MI_00" in up else (None, None)
    if "VEN_14C3&DEV_7961" in up or "MT7921" in name.upper():
        return "builtin", "wifi"
    if "VID_13D3&PID_3563" in up:
        return "builtin", "bt"
    return None, None


def devices():
    rows = _call("devices")
    out = {}
    for r in rows if isinstance(rows, list) else [rows]:  # PowerShell can unwrap a one-item array
        key, kind = device_key(r["id"], r["name"])
        if key is None:
            continue
        entry = out.setdefault(key, {"present": True, "wifi": None, "bt": None})
        entry[kind] = entry[kind] or {"id": r["id"], "ok": r["status"] == "OK", "disabled": r["problem"] in ("CM_PROB_DISABLED", "22")}
    return out


def enable(dev_id):
    _call("enable", id=dev_id)


def disable(dev_id):
    _call("disable", id=dev_id)


def load_choice(path):
    try:
        key = json.loads(Path(path).read_text(encoding="utf-8")).get("use")
    except (OSError, ValueError, AttributeError):
        return None
    return key if key in ("unigen", "builtin") else None


def save_choice(path, key):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**data, "use": key}), encoding="utf-8")
