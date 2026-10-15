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
    """Wi-Fi counts as off when it's disabled in Device Manager (pnp_off) or its radio is off; Bluetooth by the former."""
    out = {}
    for r in _rows():
        key, kind = device_key(r["id"], r["name"])
        if key is None:
            continue
        entry = out.setdefault(key, {"present": True, "wifi": None, "bt": None})
        off = r["problem"] in ("CM_PROB_DISABLED", "22")
        entry[kind] = entry[kind] or {"id": r["id"], "ok": r["status"] == "OK", "disabled": off, "pnp_off": off}
    radios = _radios()
    for key, entry in out.items():
        w, r = entry["wifi"], radios.get(key)
        if w and r and not r["on"]:
            w["ok"], w["disabled"] = False, True
    return out


def _radios():  # tests replace this
    try:
        return wifi.radios()
    except (wifi.WifiError, OSError):
        return {}


def enable(dev_id):  # tests replace this and disable
    pnp.set_enabled(dev_id, True)


def disable(dev_id):
    pnp.set_enabled(dev_id, False)


def set_radio(guid, on):  # tests replace this
    wifi.set_radio(guid, on)


def wifi_on(key, dev, *, wait=20.0, clock=time.monotonic, sleep=time.sleep):
    """Turn an adapter's Wi-Fi on by its radio (instant). Device Manager only if it's disabled there (as earlier
    versions left it): the driver then takes 7-26 s to start, once. False if the adapter never showed up."""
    if dev["pnp_off"]:
        _settled(enable, dev["id"], sleep)
        dev["pnp_off"] = False
    deadline = clock() + wait
    while not (r := _radios().get(key)):  # the interface appears a moment after the driver starts
        if clock() >= deadline:
            return False
        sleep(0.25)
    set_radio(r["guid"], True)
    return True


def wifi_off(key, dev):
    """Radio off: the adapter stays enabled, so switching back is instant."""
    r = _radios().get(key)
    if r:
        set_radio(r["guid"], False)
    elif not dev["pnp_off"]:
        disable(dev["id"])


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
BT_STUCK = 120  # s: a Bluetooth move this long has hung in a driver (tests lower it)
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
        sleep(0.25)
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


def _finish(target, old, wifi_dev, move_bt, on_later):
    """The tail of a switch, once Wi-Fi works: turn the old adapter's Wi-Fi off, then move Bluetooth (the slow part)."""
    notes, ok = [], True
    try:
        if wifi_dev:
            try:
                wifi_off(old, wifi_dev)
            except _FAIL as e:
                log.warning("turning off %s failed: %s", old, e)
                notes.append(f"The {_name(old)} couldn't be turned off; Windows may still use it.")
                ok = False
        if move_bt:
            result = []

            def move():
                try:
                    bt.switch(target)
                    result.append(None)
                except Exception as e:  # bt.switch put the old radio back
                    result.append(e)
            mover = threading.Thread(target=move, name="bt-switch", daemon=True)
            mover.start()
            mover.join(BT_STUCK)
            if not result:  # a driver hung in the kernel; nothing in user mode can end it, but Wi-Fi stays usable
                log.warning("moving Bluetooth to %s still hasn't finished after %d s", target, BT_STUCK)
                notes.append("Bluetooth is stuck: Windows hasn't finished turning a radio off. Unplug the dongle and "
                             "plug it back in (or restart the PC), then switch again.")
                ok = False
            elif result[0]:
                log.warning("moving Bluetooth to %s failed: %s", target, result[0])
                notes.append(f"Bluetooth couldn't move and stays on the {_name(old)}. Switch again to retry.")
                ok = False
            else:
                notes.append(f"Bluetooth moved to the {_name(target)}.")
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
    bail = lambda: _undo(t, target)  # Wi-Fi failed: Bluetooth hasn't moved yet, so only Wi-Fi needs undoing
    up = lambda: wifi_on(target, t["wifi"], wait=wait, clock=clock, sleep=sleep) and _wait_iface(target, wait, clock, sleep)
    on_step(f"Turning on the {_name(target)}…")
    try:
        if not up():
            _settled(disable, t["wifi"]["id"], sleep)  # restart once: clears a half-started driver
            t["wifi"]["pnp_off"] = True
            if not up():
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
            if not _wait_visible(ti, ssid, wait, clock, sleep):
                bail()
                fix = "Unplug it and plug it back in" if target == "unigen" else "Restart the PC"
                raise HwError(f"The {_name(target)} can't see any Wi-Fi network. {fix}, then switch again.{back}")
            wifi.connect(ti["name"], ssid, saved=True)
    except _FAIL as e:
        log.warning("switch to %s failed: %s", target, e)
        bail()
        raise HwError(f"Couldn't finish switching to the {_name(target)}.{back}") from None
    save_choice(path, target)  # Wi-Fi works: the rest happens in the background
    on_step(f"Done. Using the {_name(target)}.{later if both_bt else ''}")
    wifi_dev = o["wifi"] if o.get("wifi") and not o["wifi"]["disabled"] else None
    return target, (target, old, wifi_dev, both_bt) if wifi_dev or both_bt else None


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
    """A freshly enabled adapter hasn't scanned yet, and netsh can't connect to a network it hasn't seen.
    False if it saw no network at all: the adapter is wedged (the dongle after its Bluetooth driver hung)."""
    deadline, seen = clock() + wait, False
    while clock() < deadline:
        nets = wifi.networks(iface["name"])
        if any(n["ssid"] == ssid for n in nets):
            return True
        seen = seen or bool(nets)
        try:
            wifi.trigger_scan(iface["guid"], wait=3.0)  # returns when the scan is done (~1.5 s)
        except (wifi.WifiError, KeyError, OSError):
            sleep(2)  # Windows scans on its own too; connect still gets its chance after the wait
    return seen


def _undo(t, key):
    """Best effort: turn the target's Wi-Fi back off if it was off, so the old adapter is exactly as it was."""
    if t["wifi"]["disabled"]:
        try:
            wifi_off(key, t["wifi"])
        except _FAIL:
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
        if choice is None or _lock.locked():  # a switch is running: both adapters are on for a moment
            return
        devs = devices()
        present = "unigen" in devs
        first, was = self._first, self._was_present
        self._first, self._was_present = False, present
        key, other = next(((k, d) for k, d in devs.items() if k != choice), (None, None))
        other_on = bool(other and other["wifi"] and other["wifi"]["ok"])
        if first and choice in devs and other_on:  # after a restart: make the saved choice true again
            return self._switch(choice, f"Using the {_name(choice)}.")
        if choice in devs and other_on and (devs[choice]["wifi"] or {}).get("ok") and not (choice == "unigen" and was is False):
            return wifi_off(key, other["wifi"])  # both on (Windows' Wi-Fi switch): quietly turn the other off
        if choice != "unigen":
            return
        if not present:
            turned_on = False
            for kind in ("wifi", "bt"):  # every pass while it's gone: never leave the PC without Wi-Fi
                d = (devs.get("builtin") or {}).get(kind)
                if d and d["disabled"]:
                    wifi_on("builtin", d) if kind == "wifi" else enable(d["id"])
                    turned_on = True
            if (turned_on or was) and not self._told:
                self._told = True
                self._notify("The dongle was unplugged. Using the built-in adapter.", True)
            return
        self._told = False
        if was is False:
            self._switch("unigen", "Dongle plugged in. Using the dongle.")
