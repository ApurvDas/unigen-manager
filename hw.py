"""One switch for Wi-Fi and Bluetooth: which adapter is in use, and the Device Manager state that makes it stick."""
import json, logging, threading, time
from pathlib import Path

import bt, pnp, winrun, wifi

log = logging.getLogger("unigen")
_rows = pnp.list_devices  # tests replace this (reads)


class HwError(Exception):
    """A switch could not finish; str(e) is safe to show the user and says where the user stands."""


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
    out = {}
    for r in _rows():
        key, kind = device_key(r["id"], r["name"])
        if key is None:
            continue
        entry = out.setdefault(key, {"present": True, "wifi": None, "bt": None})
        entry[kind] = entry[kind] or {"id": r["id"], "ok": r["status"] == "OK", "disabled": r["problem"] in ("CM_PROB_DISABLED", "22")}
    return out


def enable(dev_id):  # tests replace this and disable
    pnp.set_enabled(dev_id, True)


def disable(dev_id):
    pnp.set_enabled(dev_id, False)


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
        try:
            i = _iface(key)
        except (wifi.WifiError, wifi.ParseError, winrun.CmdError):
            i = None  # netsh says "not in the correct state" while the adapter starts
        if i:
            return i
        sleep(1)
    return None


def use(target, *, on_step=lambda text: None, on_later=lambda text, ok: None, path, wait=20.0, clock=time.monotonic,
        sleep=time.sleep, spawn=lambda f: threading.Thread(target=f, name="bt-move", daemon=True).start()):
    """Make `target` the adapter in use: Wi-Fi and Bluetooth together. Any failure leaves the old adapter working.
    Returns once Wi-Fi works. The old Wi-Fi then goes off and Bluetooth moves in the background (spawn): taking a
    radio off can take a minute while Windows removes its paired devices' audio drivers. on_later(text, ok) reports
    how that went; the lock is held until it's over, so a second switch can't overlap it."""
    if not _lock.acquire(blocking=False):
        raise HwError("A switch is still finishing. Bluetooth can take up to a minute; try again in a moment.")
    move = None
    try:
        result, move = _use(target, on_step, path, wait, clock, sleep)
        return result
    finally:
        if move:
            spawn(lambda: _finish(*move, on_later))
        else:
            _lock.release()


def _finish(target, old, wifi_id, move_bt, on_later):
    """The slow tail of a switch, once Wi-Fi works: turn the old adapter's Wi-Fi off, then move Bluetooth."""
    notes, ok = [], True
    try:
        if wifi_id:
            try:
                disable(wifi_id)
            except winrun.CmdError as e:
                log.warning("turning off %s failed: %s", old, e)
                notes.append(f"The {_name(old)} couldn't be turned off; Windows may still use it.")
                ok = False
        if move_bt:
            try:
                bt.switch(target)
                notes.append(f"Bluetooth moved to the {_name(target)}.")
            except Exception as e:  # bt.switch put the old radio back
                log.warning("moving Bluetooth to %s failed: %s", target, e)
                notes.append(f"Bluetooth couldn't move and stays on the {_name(old)}. Switch again to retry.")
                ok = False
        on_later(" ".join(notes) or f"The {_name(old)} is off.", ok)
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
    both_bt = bool(t["bt"] and o.get("bt"))
    later = " Bluetooth is moving too; this can take up to a minute."
    if t["wifi"]["ok"] and not (o.get("wifi") and o["wifi"]["ok"]):  # already in use
        half = both_bt and (not t["bt"]["ok"] or o["bt"]["ok"])  # a half-done switch: finish moving Bluetooth
        save_choice(path, target)
        on_step(f"Done. Using the {_name(target)}.{later if half else ''}")
        return target, (target, old, None, True) if half else None
    old_iface = _iface(old) if old else None
    bail = lambda: _undo(t)  # Wi-Fi failed: Bluetooth hasn't moved yet, so only Wi-Fi needs undoing
    on_step(f"Turning on the {_name(target)}…")
    try:
        _settled(enable, t["wifi"]["id"], sleep)
        if not _wait_iface(target, wait, clock, sleep):
            _settled(disable, t["wifi"]["id"], sleep)  # restart once: clears a half-started driver
            _settled(enable, t["wifi"]["id"], sleep)
            if not _wait_iface(target, wait, clock, sleep):
                bail()
                raise HwError(f"The {_name(target)}'s Wi-Fi didn't start.{back}")
    except _FAIL as e:
        log.warning("turning on %s failed: %s", target, e)
        bail()
        raise HwError(f"Couldn't turn on the {_name(target)}.{back}") from None
    try:
        ssid = old_iface.get("ssid") if old_iface and old_iface.get("state") == "connected" else None
        if ssid:
            on_step(f"Connecting to {ssid}…")
            ti = _iface(target)
            names = wifi.profiles().get(ti["name"], [])
            if ssid not in names and wifi.profile_name(ssid) not in names:
                wifi.copy_profile(old_iface.get("profile") or ssid, old_iface["name"], ti["name"])
            _wait_visible(ti, ssid, wait, clock, sleep)
            wifi.connect(ti["name"], ssid, saved=True)
    except _FAIL as e:
        log.warning("switch to %s failed: %s", target, e)
        bail()
        raise HwError(f"Couldn't finish switching to the {_name(target)}.{back}") from None
    save_choice(path, target)  # Wi-Fi works: the rest happens in the background
    on_step(f"Done. Using the {_name(target)}.{later if both_bt else ''}")
    wifi_id = o["wifi"]["id"] if o.get("wifi") else None
    return target, (target, old, wifi_id, both_bt) if wifi_id or both_bt else None


def _settled(action, dev_id, sleep, tries=3):
    """Windows briefly refuses PnP changes while a device is still settling ("not in the correct state")."""
    for n in range(tries):
        try:
            return action(dev_id)
        except winrun.CmdError:
            if n == tries - 1:
                raise
            sleep(2)


def _wait_visible(iface, ssid, wait, clock, sleep):
    """A freshly enabled adapter hasn't scanned yet, and netsh can't connect to a network it hasn't seen."""
    deadline = clock() + wait
    while clock() < deadline:
        if any(n["ssid"] == ssid for n in wifi.networks(iface["name"])):
            return
        if iface.get("guid"):
            try:
                wifi.trigger_scan(iface["guid"])
            except wifi.WifiError:
                pass  # Windows scans on its own too; connect still gets its chance after the wait
        sleep(2)


def _undo(t):
    """Best effort: turn the target's Wi-Fi back off if it was off, so the old adapter is exactly as it was."""
    if t["wifi"]["disabled"]:
        try:
            disable(t["wifi"]["id"])
        except winrun.CmdError:
            pass


# ---- the watchdog ----
class Follower:
    """One pass every few seconds (step): keeps the saved choice true after a restart, and follows the dongle
    being unplugged (turn the built-in adapter on) and plugged back in (switch to it again)."""

    def __init__(self, path, notify, *, admin, use=use):
        self._path, self._notify, self._admin, self._use = path, notify, admin, use
        self._first, self._was_present, self._told = True, None, False

    def step(self):
        if not self._admin:
            return
        try:
            self._step()
        except Exception:
            log.exception("watchdog pass failed")

    def _switch(self, choice, ok_text):
        try:
            self._use(choice, path=self._path, on_later=lambda text, ok: ok or self._notify(text, False))
        except HwError as e:
            self._notify(str(e), False)
        else:
            self._notify(ok_text, True)

    def _step(self):
        choice = load_choice(self._path)
        if choice is None:
            return
        devs = devices()
        present = "unigen" in devs
        first, was = self._first, self._was_present
        self._first, self._was_present = False, present
        if first and choice in devs:
            other = next((d for k, d in devs.items() if k != choice), None)
            if other and other["wifi"] and other["wifi"]["ok"]:
                return self._switch(choice, f"Using the {_name(choice)}.")
        if choice != "unigen":
            return
        if not present:
            turned_on = False
            for kind in ("wifi", "bt"):  # every pass while it's gone: never leave the PC without Wi-Fi
                d = (devs.get("builtin") or {}).get(kind)
                if d and d["disabled"]:
                    enable(d["id"])
                    turned_on = True
            if (turned_on or was) and not self._told:
                self._told = True
                self._notify("The dongle was unplugged. Using the built-in adapter.", True)
            return
        self._told = False
        if was is False:
            self._switch("unigen", "Dongle plugged in. Using the dongle.")
