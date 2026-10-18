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
        if w:
            w["lost"] = False
            if r and not r["on"]:
                w["ok"], w["disabled"] = False, True
            elif radios and not r and not w["pnp_off"]:  # started but Windows has no WLAN interface: crashed
                w["ok"], w["lost"] = False, True
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
    """Radio off: the adapter stays enabled, so switching back is instant. No WLAN interface: nothing to turn off."""
    r = _radios().get(key)
    if r:
        set_radio(r["guid"], False)


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
# s: a Bluetooth move this long has hung in a driver (tests lower it). A normal move is disconnect wait (10) + settles (2+2)
# + old radio off (up to 45) + target on (up to 20) = 79, plus the per-device disconnect/reconnect calls: 150 leaves room.
BT_STUCK = 150
RESTART_LIMIT = 30  # s: restarting a half-started Wi-Fi driver; longer means it's not answering (tests lower it)
LOST_PASSES = 3  # watchdog passes (a few seconds each) the dongle's Wi-Fi may lack its WLAN interface before it counts as crashed
_FAIL = (wifi.WifiError, wifi.ParseError, bt.BtError, winrun.CmdError)


def _name(k):
    return wifi.ADAPTER_NAMES.get(k, k)


def _bounded(fn, seconds):
    """Run fn in a daemon thread for at most `seconds`: (finished, error). A driver hung in the kernel can't be ended
    from user mode, but it mustn't hold the switch lock."""
    err = []

    def run():
        try:
            fn()
        except Exception as e:
            err.append(e)
    t = threading.Thread(target=run, name="bt-switch", daemon=True)
    t.start()
    t.join(seconds)
    return not t.is_alive(), err[0] if err else None


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

    def tail():  # both steps are bounded together: a driver hung in the kernel must not hold the lock
        nonlocal ok
        if wifi_dev:
            try:
                wifi_off(old, wifi_dev)
            except _FAIL as e:
                log.warning("turning off %s failed: %s", old, e, exc_info=True)
                notes.append(f"The {_name(old)} couldn't be turned off; Windows may still use it.")
                ok = False
        if move_bt:
            try:
                bt.switch(target)
                notes.append(f"Bluetooth moved to the {_name(target)}.")
            except Exception as e:  # bt.switch put the old radio back
                log.warning("moving Bluetooth to %s failed: %s", target, e, exc_info=True)
                notes.append(str(e) if isinstance(e, bt.StuckRadio)
                             else f"Bluetooth couldn't move and stays on the {_name(old)}. Switch again to retry.")
                ok = False
    try:
        finished, err = _bounded(tail, BT_STUCK)
        if err:
            log.error("finishing the switch to %s failed", target, exc_info=err)
            notes.append("Something went wrong finishing the switch; switch again to retry.")
            ok = False
        elif not finished:  # Wi-Fi stays usable
            log.warning("switch to %s: turning off %s / moving Bluetooth still hasn't finished after %d s", target, old, BT_STUCK)
            notes.append("Bluetooth is stuck: Windows hasn't finished turning a radio off. Unplug the dongle and "
                         "plug it back in (or restart the PC), then switch again.")
            ok = False
        text = " ".join(notes) or f"The {_name(old)} is off."
        log.info("switch to %s finished: %s", target, text)
        on_later(text, ok)
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
            finished, err = _bounded(lambda: _settled(disable, t["wifi"]["id"], sleep), RESTART_LIMIT)  # restart once: clears a half-started driver
            if err:
                raise err
            if not finished:  # blocked in the driver: don't touch the device again
                raise HwError(f"The {_name(target)} isn't responding. Unplug it and plug it back in.{back}")
            t["wifi"]["pnp_off"] = True
            if not up():
                bail()
                raise HwError(f"The {_name(target)}'s Wi-Fi didn't start.{back}")
    except _FAIL as e:
        log.warning("turning on %s failed: %s", target, e, exc_info=True)
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
        log.warning("switch to %s failed: %s", target, e, exc_info=True)
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
        self._first, self._was_present, self._told, self._lost = True, None, False, 0

    def step(self):
        if not self._admin:
            return
        try:
            self._step()
        except Exception:
            log.exception("watchdog pass failed")

    def _switch(self, choice, ok_text):
        log.info("watchdog: switching to %s", choice)
        try:
            self._use(choice, path=self._path, on_later=lambda text, ok: ok or self._notify(text, False))
        except HwError as e:
            log.warning("watchdog: switch to %s failed: %s", choice, e)
            self._notify(str(e), False)
        else:
            self._notify(ok_text, True)

    def _step(self):
        choice = load_choice(self._path)
        if choice is None or _lock.locked():  # a switch is running: both adapters are on for a moment
            return
        devs = devices()
        lost = ((devs.get("unigen") or {}).get("wifi") or {}).get("lost")
        self._lost = self._lost + 1 if lost else 0
        crashed = self._lost >= LOST_PASSES  # a dongle that just came up has no WLAN interface for a second or two
        present = "unigen" in devs and not crashed
        first, was = self._first, self._was_present
        self._first, self._was_present = False, present
        key, other = next(((k, d) for k, d in devs.items() if k != choice), (None, None))
        other_on = bool(other and other["wifi"] and other["wifi"]["ok"])
        if first and choice in devs and other_on:  # after a restart: make the saved choice true again
            return self._switch(choice, f"Using the {_name(choice)}.")
        if choice in devs and other_on and (devs[choice]["wifi"] or {}).get("ok") and not (choice == "unigen" and was is False):
            log.info("watchdog: both Wi-Fi adapters on, turning off %s", key)
            return wifi_off(key, other["wifi"])  # both on (Windows' Wi-Fi switch): quietly turn the other off
        if not present:
            todo = [k for k in ("wifi", "bt") if ((devs.get("builtin") or {}).get(k) or {}).get("disabled")]
            if (todo or was) and not self._told:  # first: turning on can block until the dongle is re-plugged
                self._told = True
                self._notify("The dongle stopped responding. Using the built-in adapter. Unplug it and plug it back in."
                             if crashed else "The dongle was unplugged. Using the built-in adapter.", True)
            for kind in todo:  # every pass while it's gone: never leave the PC without Wi-Fi
                log.info("watchdog: turning on the built-in %s", "Wi-Fi" if kind == "wifi" else "Bluetooth")
                d = devs["builtin"][kind]
                wifi_on("builtin", d) if kind == "wifi" else enable(d["id"])
            return
        self._told = False
        if choice != "unigen":
            return
        if was is False:
            self._switch("unigen", "Dongle plugged in. Using the dongle.")
