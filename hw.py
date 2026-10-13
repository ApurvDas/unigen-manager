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


# ---- the switch ----
_lock = threading.Lock()
_FAIL = (wifi.WifiError, wifi.ParseError, bt.BtError, winrun.CmdError)


def _name(k):
    return wifi.ADAPTER_NAMES.get(k, k)


def _iface(key):
    return next((i for i in wifi.interfaces() if wifi.adapter_key(i["description"]) == key), None)


def _wait_iface(key, wait, clock, sleep):
    deadline = clock() + wait
    while clock() < deadline:
        i = _iface(key)
        if i:
            return i
        sleep(1)
    return None


def use(target, *, on_step=lambda text: None, path, wait=20.0, clock=time.monotonic, sleep=time.sleep):
    """Make `target` the adapter in use: Wi-Fi and Bluetooth together. Any failure leaves the old adapter working."""
    if not _lock.acquire(blocking=False):
        raise HwError("A switch is already running.")
    try:
        return _use(target, on_step, path, wait, clock, sleep)
    finally:
        _lock.release()


def _use(target, on_step, path, wait, clock, sleep):
    devs = devices()
    if target not in devs:
        raise HwError(f"The {_name(target)} isn't plugged in.")
    old = next((k for k in devs if k != target), None)
    t, o = devs[target], devs.get(old) or {}
    back = f" You're still on the {_name(old)}." if old else ""
    if not t["wifi"]:
        raise HwError(f"The {_name(target)} has no Wi-Fi device to turn on.{back}")
    if t["wifi"]["ok"] and not (o.get("wifi") and o["wifi"]["ok"]):  # already in use
        save_choice(path, target)
        on_step(f"Done. Using the {_name(target)}.")
        return target
    old_iface = _iface(old) if old else None
    on_step(f"Turning on the {_name(target)}…")
    try:
        enable(t["wifi"]["id"])
        if not _wait_iface(target, wait, clock, sleep):
            disable(t["wifi"]["id"])  # restart once: clears a half-started driver
            enable(t["wifi"]["id"])
            if not _wait_iface(target, wait, clock, sleep):
                _undo(t)
                raise HwError(f"The {_name(target)}'s Wi-Fi didn't start.{back}")
    except _FAIL as e:
        log.warning("turning on %s failed: %s", target, e)
        _undo(t)
        raise HwError(f"Couldn't turn on the {_name(target)}.{back}") from None
    try:
        ssid = old_iface.get("ssid") if old_iface and old_iface.get("state") == "connected" else None
        if ssid:
            on_step(f"Connecting to {ssid}…")
            ti = _iface(target)
            names = wifi.profiles().get(ti["name"], [])
            if ssid not in names and wifi.profile_name(ssid) not in names:
                wifi.copy_profile(old_iface.get("profile") or ssid, old_iface["name"], ti["name"])
            wifi.connect(ti["name"], ssid, saved=True)
        if t["bt"] and o.get("bt"):
            on_step("Moving Bluetooth…")
            bt.switch(target)
    except _FAIL as e:
        log.warning("switch to %s failed: %s", target, e)
        _undo(t)
        raise HwError(f"Couldn't finish switching to the {_name(target)}.{back}") from None
    warn = ""
    if o.get("wifi"):
        on_step(f"Turning off the {_name(old)}…")
        try:
            disable(o["wifi"]["id"])
        except winrun.CmdError as e:
            log.warning("turning off %s failed: %s", old, e)
            warn = f" The {_name(old)} couldn't be turned off; Windows may still use it."
    save_choice(path, target)
    on_step(f"Done. Using the {_name(target)}.{warn}")
    return target


def _undo(t):
    """Best effort: turn the target's Wi-Fi back off if it was off, so the old adapter is exactly as it was."""
    if t["wifi"]["disabled"]:
        try:
            disable(t["wifi"]["id"])
        except winrun.CmdError:
            pass
