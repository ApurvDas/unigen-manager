import json

import pytest

import hw, pnp, winrun

UNI_WIFI = r"USB\VID_368B&PID_8D81&MI_02\7&AAAA0001&0&0002"
UNI_BT = r"USB\VID_368B&PID_8D81&MI_00\7&AAAA0001&0&0000"
MT_WIFI = r"PCI\VEN_14C3&DEV_7961&SUBSYS_00000000&REV_00\4&BBBB0002&0&00E0"
MT_BT = r"USB\VID_13D3&PID_3563\000000000000"
ETH = r"PCI\VEN_10EC&DEV_8168&SUBSYS_00000000&REV_15\4&CCCC0003&0&00E1"


def row(i, name, status="OK", problem="CM_PROB_NONE"):
    return {"id": i, "name": name, "status": status, "problem": problem}


ALL = [row(UNI_WIFI, "AIC8800D80 USB WiFi"), row(UNI_BT, "Generic Bluetooth Adapter"),
       row(MT_WIFI, "MediaTek Wi-Fi 6 MT7921 Wireless LAN Card"),
       row(MT_BT, "MediaTek Bluetooth Adapter", "Error", "CM_PROB_DISABLED"),
       row(ETH, "PCIe Gigabit Ethernet Controller")]


def test_device_key_maps_known_ids():
    assert hw.device_key(UNI_WIFI, "x") == ("unigen", "wifi")
    assert hw.device_key(UNI_BT, "x") == ("unigen", "bt")
    assert hw.device_key(MT_WIFI, "x") == ("builtin", "wifi")
    assert hw.device_key(r"PCI\VEN_0000&DEV_0000", "MediaTek Wi-Fi 6 MT7921") == ("builtin", "wifi")
    assert hw.device_key(MT_BT, "x") == ("builtin", "bt")
    assert hw.device_key(ETH, "PCIe Gigabit Ethernet Controller") == (None, None)


def test_devices_groups_by_adapter(monkeypatch):
    monkeypatch.setattr(hw, "_rows", lambda: ALL)
    monkeypatch.setattr(hw, "_radios", lambda: {"unigen": {"guid": "g", "on": True}})
    d = hw.devices()
    assert set(d) == {"unigen", "builtin"}
    assert d["unigen"] == {"present": True, "wifi": {"id": UNI_WIFI, "ok": True, "disabled": False, "pnp_off": False},
                           "bt": {"id": UNI_BT, "ok": True, "disabled": False, "pnp_off": False}}
    assert d["builtin"]["wifi"]["ok"] is True
    assert d["builtin"]["bt"] == {"id": MT_BT, "ok": False, "disabled": True, "pnp_off": True}


def test_devices_radio_off_counts_as_off(monkeypatch):
    monkeypatch.setattr(hw, "_rows", lambda: ALL)
    monkeypatch.setattr(hw, "_radios", lambda: {"builtin": {"guid": "g", "on": False}})
    assert hw.devices()["builtin"]["wifi"] == {"id": MT_WIFI, "ok": False, "disabled": True, "pnp_off": False}


def test_wifi_on_uses_the_radio_and_device_manager_only_when_disabled_there(monkeypatch):
    calls, radios = [], {}
    monkeypatch.setattr(hw, "enable", lambda i: (calls.append(("enable", i)), radios.update(builtin={"guid": "g", "on": False})))
    monkeypatch.setattr(hw, "_radios", lambda: dict(radios))
    monkeypatch.setattr(hw, "set_radio", lambda g, on: calls.append(("radio", g, on)))
    d = {"id": MT_WIFI, "ok": False, "disabled": True, "pnp_off": True}
    assert hw.wifi_on("builtin", d, sleep=lambda s: None) is True
    assert calls == [("enable", MT_WIFI), ("radio", "g", True)] and d["pnp_off"] is False
    calls.clear()
    assert hw.wifi_on("builtin", d) is True and calls == [("radio", "g", True)]  # next time: the radio only
    hw.wifi_off("builtin", d)
    assert calls[-1] == ("radio", "g", False)


def test_devices_without_dongle(monkeypatch):
    monkeypatch.setattr(hw, "_rows", lambda: ALL[2:])
    monkeypatch.setattr(hw, "_radios", lambda: {})
    assert "unigen" not in hw.devices()




def test_choice_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    assert hw.load_choice(p) is None
    p.write_text("{not json", encoding="utf-8")
    assert hw.load_choice(p) is None
    hw.save_choice(p, "unigen")
    assert hw.load_choice(p) == "unigen"
    p.write_text('{"use": "toaster"}', encoding="utf-8")
    assert hw.load_choice(p) is None


def test_save_choice_keeps_other_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"other": 1}', encoding="utf-8")
    hw.save_choice(p, "builtin")
    assert json.loads(p.read_text(encoding="utf-8")) == {"other": 1, "use": "builtin"}


def test_enable_disable_call_pnp(monkeypatch):
    seen = []
    monkeypatch.setattr(pnp, "set_enabled", lambda i, on, *a, **kw: seen.append((i, on)))
    hw.enable(UNI_WIFI)
    hw.disable(MT_WIFI)
    assert seen == [(UNI_WIFI, True), (MT_WIFI, False)]


# ---- hw.use ----
import itertools, threading

import bt, wifi

BUILTIN_IF = {"name": "Wi-Fi", "description": "MediaTek Wi-Fi 6 MT7921 Wireless LAN Card", "state": "connected",
              "ssid": "HOME-5G", "profile": "HOME-5G"}
DONGLE_IF = {"name": "Wi-Fi 2", "description": "AIC8800D80 USB WiFi", "state": "disconnected", "guid": "00000000-0000-0000-0000-000000000002"}


def dev(i, ok=True):
    return {"id": i, "ok": ok, "disabled": not ok, "pnp_off": not ok}


class World:
    """Fake PC: the dongle is plugged in, its devices are off, the built-in adapter is on and joined to HOME-5G."""

    def __init__(self, monkeypatch, tmp_path, *, appear=True, connected=True, dongle_profile=False):
        self.calls, self.steps, self.appear = [], [], appear
        self.path = tmp_path / "settings.json"
        self.state = {"unigen": {"wifi": False, "bt": False}, "builtin": {"wifi": True, "bt": True}}
        self.ids = {"unigen": {"wifi": UNI_WIFI, "bt": UNI_BT}, "builtin": {"wifi": MT_WIFI, "bt": MT_BT}}
        self.ifaces = [dict(BUILTIN_IF, state="connected" if connected else "disconnected")]
        self.fail_connect = self.fail_bt = self.fail_disable_old = False
        self.bt_calls = []
        self.scans, self.visible_after = 0, 0  # the dongle sees HOME-5G only after this many scans
        mp = monkeypatch
        mp.setattr(wifi, "trigger_scan", lambda guid, **kw: setattr(self, "scans", self.scans + 1))
        mp.setattr(wifi, "networks", lambda iface: [{"ssid": "HOME-5G", "auth": "WPA2-Personal", "aps": []}]
                   if iface != "Wi-Fi 2" or self.scans >= self.visible_after else [])
        mp.setattr(hw, "devices", self.devices)
        mp.setattr(hw, "enable", self.enable)
        mp.setattr(hw, "disable", self.disable)
        mp.setattr(hw, "wifi_on", lambda key, d, sleep=None, **kw: hw._settled(hw.enable, d["id"], sleep) or True)  # radio as on/off
        mp.setattr(hw, "wifi_off", lambda key, d: hw.disable(d["id"]))
        mp.setattr(wifi, "interfaces", lambda: [dict(i) for i in self.ifaces])
        mp.setattr(wifi, "profiles", lambda: {"Wi-Fi": ["HOME-5G"], "Wi-Fi 2": ["HOME-5G"] if dongle_profile else []})
        mp.setattr(wifi, "copy_profile", lambda *a: self.calls.append(("copy",) + a))
        mp.setattr(wifi, "connect", self.connect)
        mp.setattr(bt, "switch", self.bt_switch)

    def devices(self):
        return {k: {"present": True, **{kind: dev(self.ids[k][kind], on) for kind, on in v.items()}}
                for k, v in self.state.items()}

    def _which(self, dev_id):
        return next((k, kind) for k, v in self.ids.items() for kind, i in v.items() if i == dev_id)

    def enable(self, dev_id):
        self.calls.append(("enable", dev_id))
        k, kind = self._which(dev_id)
        self.state[k][kind] = True
        if (k, kind) == ("unigen", "wifi") and self.appear and not any(i["name"] == "Wi-Fi 2" for i in self.ifaces):
            self.ifaces.append(dict(DONGLE_IF))

    def disable(self, dev_id):
        self.calls.append(("disable", dev_id))
        k, kind = self._which(dev_id)
        if self.fail_disable_old and k == "builtin":
            raise winrun.CmdError("Access denied")
        self.state[k][kind] = False
        if (k, kind) == ("unigen", "wifi"):
            self.ifaces = [i for i in self.ifaces if i["name"] != "Wi-Fi 2"]

    def connect(self, iface, ssid, **kw):
        self.calls.append(("connect", iface, ssid))
        if iface == "Wi-Fi 2" and self.scans < self.visible_after:
            raise wifi.WifiError(f'The network specified by profile "{ssid}" is not available to connect.')
        if self.fail_connect:
            raise wifi.WifiError(f"Couldn't connect to {ssid}.")

    def bt_switch(self, key):
        self.bt_calls.append(key)
        self.calls.append(("bt", key))
        if self.fail_bt and key == "unigen":
            raise bt.BtError("The Unigen dongle radio didn't start.")

    def on_step(self, text):
        self.steps.append(text)

    def use(self, target="unigen"):
        self.later_notes = []
        return hw.use(target, on_step=self.on_step, on_later=lambda text, ok: self.later_notes.append((text, ok)), path=self.path,
                      clock=itertools.count().__next__, sleep=lambda s: None, spawn=lambda f: f())  # Bluetooth inline


@pytest.fixture
def world(monkeypatch, tmp_path):
    return World(monkeypatch, tmp_path)


def test_use_full_switch_order(world):
    assert world.use() == "unigen"
    # one device change at a time (Windows queues them anyway); Bluetooth last, after the switch reports done
    assert world.calls == [("enable", UNI_WIFI), ("copy", "HOME-5G", "Wi-Fi", "Wi-Fi 2"), ("connect", "Wi-Fi 2", "HOME-5G"),
                           ("disable", MT_WIFI), ("bt", "unigen")]
    assert hw.load_choice(world.path) == "unigen"
    assert world.steps == ["Turning on the Unigen dongle…", "Connecting to HOME-5G…",
                           "Done. Using the Unigen dongle. Bluetooth is moving too; this can take up to a minute."]
    assert world.later_notes == [("Bluetooth moved to the Unigen dongle.", True)]


def test_use_returns_before_bluetooth_moves_and_holds_the_lock_until_it_has(world):
    jobs = []
    r = hw.use("unigen", on_step=world.on_step, path=world.path, clock=itertools.count().__next__, sleep=lambda s: None,
               spawn=jobs.append)
    assert r == "unigen" and world.bt_calls == [] and len(jobs) == 1  # Wi-Fi works; old Wi-Fi and Bluetooth not touched yet
    assert ("disable", MT_WIFI) not in world.calls
    with pytest.raises(hw.HwError, match="still finishing"):
        world.use()
    jobs[0]()
    assert world.bt_calls == ["unigen"] and hw._lock.acquire(blocking=False)
    hw._lock.release()


def test_use_skips_copy_when_dongle_already_has_the_profile(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path, dongle_profile=True)
    w.use()
    assert not any(c[0] == "copy" for c in w.calls) and ("connect", "Wi-Fi 2", "HOME-5G") in w.calls


def test_use_without_network_skips_connect(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path, connected=False)
    w.use()
    assert [c[0] for c in w.calls] == ["enable", "disable", "bt"] and w.calls[-2] == ("disable", MT_WIFI)
    assert hw.load_choice(w.path) == "unigen"


def test_use_target_wifi_never_appears_restarts_once_then_rolls_back(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path, appear=False)
    hw.save_choice(w.path, "builtin")
    with pytest.raises(hw.HwError) as e:
        w.use()
    assert w.calls == [("enable", UNI_WIFI), ("disable", UNI_WIFI), ("enable", UNI_WIFI), ("disable", UNI_WIFI)]  # Bluetooth untouched
    assert str(e.value) == "The Unigen dongle's Wi-Fi didn't start. You're still on the Built-in MediaTek."
    assert hw.load_choice(w.path) == "builtin"


def test_use_connect_fails_rolls_back(world):
    world.fail_connect = True
    hw.save_choice(world.path, "builtin")
    with pytest.raises(hw.HwError, match="You're still on the Built-in MediaTek"):
        world.use()
    assert world.calls[-1] == ("disable", UNI_WIFI)
    assert ("disable", MT_WIFI) not in world.calls and hw.load_choice(world.path) == "builtin"
    assert world.bt_calls == []  # Bluetooth moves only after Wi-Fi works


def test_use_bt_hung_in_a_driver_frees_the_switch_and_says_replug(world, monkeypatch):
    stuck = threading.Event()
    monkeypatch.setattr(bt, "switch", lambda key: stuck.wait(5))
    monkeypatch.setattr(hw, "BT_STUCK", 0.05)
    try:
        assert world.use() == "unigen"
        (text, ok), = world.later_notes
        assert not ok and text.startswith("Bluetooth is stuck") and "Unplug the dongle" in text
        assert hw._lock.acquire(blocking=False)  # Wi-Fi switching works again
        hw._lock.release()
    finally:
        stuck.set()


def test_use_bt_fails_keeps_wifi_and_warns(world):
    world.fail_bt = True
    assert world.use() == "unigen"
    assert ("disable", MT_WIFI) in world.calls and hw.load_choice(world.path) == "unigen"
    assert world.later_notes == [("Bluetooth couldn't move and stays on the Built-in MediaTek. Switch again to retry.", False)]
    assert hw._lock.acquire(blocking=False)  # released even when Bluetooth failed
    hw._lock.release()


def test_use_enable_refused_is_a_plain_sentence(world, monkeypatch):
    def refuse(i): raise winrun.CmdError("Enable-PnpDevice : Access is denied")
    monkeypatch.setattr(hw, "enable", refuse)
    with pytest.raises(hw.HwError) as e:
        world.use()
    assert str(e.value) == "Couldn't turn on the Unigen dongle. You're still on the Built-in MediaTek."


def test_use_already_in_use_only_saves_choice(world):
    world.state = {"unigen": {"wifi": True, "bt": True}, "builtin": {"wifi": False, "bt": False}}
    assert world.use() == "unigen"
    assert world.calls == [] and world.bt_calls == [] and hw.load_choice(world.path) == "unigen"
    assert world.steps == ["Done. Using the Unigen dongle."]


def test_use_already_in_use_repairs_half_moved_bluetooth(world):
    world.state = {"unigen": {"wifi": True, "bt": False}, "builtin": {"wifi": False, "bt": True}}
    assert world.use() == "unigen"
    assert world.calls == [("bt", "unigen")]
    assert world.steps == ["Done. Using the Unigen dongle. Bluetooth is moving too; this can take up to a minute."]
    assert world.later_notes == [("Bluetooth moved to the Unigen dongle.", True)]


def test_use_old_wifi_disable_fails_still_succeeds(world):
    world.fail_disable_old = True
    assert world.use() == "unigen"
    assert hw.load_choice(world.path) == "unigen"
    assert world.later_notes == [("The Built-in MediaTek couldn't be turned off; Windows may still use it. "
                                  "Bluetooth moved to the Unigen dongle.", False)]


def test_use_target_not_plugged_in(world):
    del world.state["unigen"]
    with pytest.raises(hw.HwError, match="The Unigen dongle isn't plugged in."):
        world.use()
    assert world.calls == []


def test_second_concurrent_use_refused(world):
    assert hw._lock.acquire(blocking=False)
    try:
        with pytest.raises(hw.HwError, match="A switch is still finishing."):
            world.use()
    finally:
        hw._lock.release()


# ---- hw.Follower ----
class Pc:
    """Fake devices() for the watchdog: dongle plugged or not, each adapter's Wi-Fi/Bluetooth on or off."""

    def __init__(self, monkeypatch, tmp_path, choice="unigen", plugged=True, unigen_on=True):
        self.path, self.plugged, self.enabled = tmp_path / "settings.json", plugged, []
        self.state = {"unigen": unigen_on, "builtin": not unigen_on}
        if choice:
            hw.save_choice(self.path, choice)
        monkeypatch.setattr(hw, "devices", self.devices)
        monkeypatch.setattr(hw, "enable", self.enable)
        monkeypatch.setattr(hw, "wifi_on", lambda key, d, **kw: hw.enable(d["id"]) or True)
        monkeypatch.setattr(hw, "wifi_off", lambda key, d: (self.offs.append(key), self.state.update({key: False})))
        self.used, self.notes, self.fail, self.offs = [], [], None, []

    def enable(self, dev_id):
        self.enabled.append(dev_id)
        self.state["builtin"] = True

    def devices(self):
        ids = {"unigen": (UNI_WIFI, UNI_BT), "builtin": (MT_WIFI, MT_BT)}
        return {k: {"present": True, "wifi": dev(w, self.state[k]), "bt": dev(b, self.state[k])}
                for k, (w, b) in ids.items() if k != "unigen" or self.plugged}

    def use(self, target, **kw):
        self.used.append(target)
        if self.fail:
            raise hw.HwError(self.fail)
        self.state = {k: k == target for k in self.state}
        return target

    def follower(self, admin=True):
        return hw.Follower(self.path, lambda t, changed: self.notes.append((t, changed)), admin=admin, use=self.use)


def test_follow_unplug_enables_builtin_once(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()  # dongle in use and present: nothing to do
    pc.plugged = False
    f.step()
    f.step()
    assert pc.enabled == [MT_WIFI, MT_BT]
    assert pc.notes == [("The dongle was unplugged. Using the built-in adapter.", True)]
    assert hw.load_choice(pc.path) == "unigen"  # the choice stays


def test_follow_replug_switches_back_once(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    pc.state["builtin"] = True  # what the unplug step enabled
    pc.plugged = True
    f.step()
    f.step()
    assert pc.used == ["unigen"]
    assert pc.notes[-1] == ("Dongle plugged in. Using the dongle.", True)


def test_follow_failed_replug_does_not_retry(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    pc.state["builtin"] = True
    pc.plugged, pc.fail = True, "Couldn't finish switching to the Unigen dongle. You're still on the Built-in MediaTek."
    for _ in range(4):
        f.step()
    assert pc.used == ["unigen"]
    assert pc.notes[-1] == (pc.fail, False) and len(pc.notes) == 2


def test_follow_failed_replug_retries_after_next_unplug(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    pc.state["builtin"] = True
    pc.plugged, pc.fail = True, "no"
    f.step()
    pc.plugged = False
    f.step()
    pc.plugged = True
    f.step()
    assert pc.used == ["unigen", "unigen"]


def test_follow_startup_enforces_choice(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", unigen_on=True)  # Windows brought the dongle back after a restart
    f = pc.follower()
    f.step()
    f.step()
    assert pc.used == ["builtin"] and pc.notes == [("Using the Built-in MediaTek.", True)]


def test_follow_startup_failure_notifies_once(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", unigen_on=True)
    pc.fail = "Couldn't turn on the Built-in MediaTek."
    f = pc.follower()
    f.step()
    f.step()
    assert pc.used == ["builtin"] and pc.notes == [(pc.fail, False)]


def test_follow_startup_with_dongle_already_gone_and_builtin_on_is_quiet(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, plugged=False, unigen_on=False)
    pc.follower().step()
    assert pc.enabled == [] and pc.notes == [] and pc.used == []


def test_follow_noop_without_admin(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", unigen_on=True)
    f = pc.follower(admin=False)
    f.step()
    pc.plugged = False
    f.step()
    assert pc.used == [] and pc.enabled == [] and pc.notes == []


def test_follow_without_choice_does_nothing(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice=None)
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    assert pc.used == [] and pc.enabled == [] and pc.notes == []


def test_follow_step_never_raises(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    def boom(): raise winrun.CmdError("powershell.exe took longer than 90 s.")
    monkeypatch.setattr(hw, "devices", boom)
    pc.follower().step()


def test_follow_unplug_retries_enable_until_it_works(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.plugged = False
    real, tries = pc.enable, []
    def flaky(i):
        tries.append(i)
        if len(tries) == 1:
            raise winrun.CmdError("busy")
        real(i)
    monkeypatch.setattr(hw, "enable", flaky)
    f.step()  # fails: logged, no notice yet
    assert pc.notes == []
    f.step()
    f.step()
    assert tries == [MT_WIFI, MT_WIFI, MT_BT] and len(pc.notes) == 1




def test_use_waits_until_the_new_adapter_sees_the_network(world):
    world.visible_after = 3  # a freshly enabled adapter hasn't scanned yet: connecting at once fails
    assert world.use() == "unigen"
    assert world.scans >= 3 and ("connect", "Wi-Fi 2", "HOME-5G") in world.calls


def test_use_waits_out_netsh_errors_while_the_adapter_starts(world, monkeypatch):
    real, n = wifi.interfaces, []
    def flaky():
        n.append(1)
        if len(n) in (2, 3):  # after enable: netsh says "not in the correct state" for a moment
            raise winrun.CmdError("The group or resource is not in the correct state to perform the requested operation.")
        return real()
    monkeypatch.setattr(wifi, "interfaces", flaky)
    assert world.use() == "unigen" and ("connect", "Wi-Fi 2", "HOME-5G") in world.calls


def test_use_retries_enable_while_the_device_settles(world, monkeypatch):
    real, tries = world.enable, []
    def busy_once(i):
        tries.append(i)
        if len(tries) == 1:
            raise winrun.CmdError("The group or resource is not in the correct state to perform the requested operation.")
        real(i)
    monkeypatch.setattr(hw, "enable", busy_once)
    assert world.use() == "unigen" and tries[:2] == [UNI_WIFI, UNI_WIFI]


def test_follow_turns_the_other_radio_off_quietly_when_both_are_on(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.state["builtin"] = True  # Windows' Wi-Fi switch turned the built-in radio back on
    assert hw._lock.acquire(blocking=False)
    try:
        f.step()  # a switch is running: hands off
    finally:
        hw._lock.release()
    assert pc.offs == []
    f.step()
    assert pc.offs == ["builtin"] and pc.used == [] and pc.notes == []
