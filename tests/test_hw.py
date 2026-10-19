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
    monkeypatch.setattr(hw, "_radios", lambda: {k: {"guid": "g", "on": True} for k in ("unigen", "builtin")})
    d = hw.devices()
    assert set(d) == {"unigen", "builtin"}
    assert d["unigen"] == {"present": True, "wifi": {"id": UNI_WIFI, "ok": True, "disabled": False, "pnp_off": False, "lost": False},
                           "bt": {"id": UNI_BT, "ok": True, "disabled": False, "pnp_off": False}}
    assert d["builtin"]["wifi"]["ok"] is True
    assert d["builtin"]["bt"] == {"id": MT_BT, "ok": False, "disabled": True, "pnp_off": True}


def test_devices_radio_off_counts_as_off(monkeypatch):
    monkeypatch.setattr(hw, "_rows", lambda: ALL)
    monkeypatch.setattr(hw, "_radios", lambda: {"builtin": {"guid": "g", "on": False}})
    assert hw.devices()["builtin"]["wifi"] == {"id": MT_WIFI, "ok": False, "disabled": True, "pnp_off": False, "lost": False}


def test_devices_started_wifi_without_a_wlan_interface_isnt_working(monkeypatch):
    """A crashed dongle: Device Manager says OK, Windows has no WLAN interface for it."""
    monkeypatch.setattr(hw, "_rows", lambda: ALL)
    monkeypatch.setattr(hw, "_radios", lambda: {"builtin": {"guid": "g", "on": True}})
    d = hw.devices()
    assert d["unigen"]["wifi"] == {"id": UNI_WIFI, "ok": False, "disabled": False, "pnp_off": False, "lost": True}
    assert d["builtin"]["wifi"]["ok"] is True
    monkeypatch.setattr(hw, "_radios", lambda: {})  # the read failed: trust Device Manager
    assert hw.devices()["unigen"]["wifi"]["ok"] is True


def test_wifi_off_without_a_wlan_interface_has_nothing_to_turn_off(monkeypatch):
    calls = []
    monkeypatch.setattr(hw, "_radios", lambda: {})
    monkeypatch.setattr(hw, "disable", lambda i: calls.append(("disable", i)))
    monkeypatch.setattr(hw, "set_radio", lambda g, on: calls.append(("radio", g, on)))
    hw.wifi_off("unigen", {"id": UNI_WIFI, "ok": True, "disabled": False, "pnp_off": False})
    assert calls == []


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
    assert hw.load_choice(p, "wifi") is None
    p.write_text("{not json", encoding="utf-8")
    assert hw.load_choice(p, "wifi") is None
    hw.save_choice(p, "wifi", "unigen")
    assert hw.load_choice(p, "wifi") == "unigen"
    p.write_text('{"wifi": "toaster"}', encoding="utf-8")
    assert hw.load_choice(p, "wifi") is None


def test_each_switch_has_its_own_saved_choice(tmp_path):
    p = tmp_path / "settings.json"
    hw.save_choice(p, "wifi", "unigen")
    hw.save_choice(p, "bt", "builtin")
    assert (hw.load_choice(p, "wifi"), hw.load_choice(p, "bt")) == ("unigen", "builtin")


def test_choice_falls_back_to_the_one_switch_setting(tmp_path):
    """Settings saved before the switches were split only have "use": it answers both until one is saved."""
    p = tmp_path / "settings.json"
    p.write_text('{"use": "unigen"}', encoding="utf-8")
    assert (hw.load_choice(p, "wifi"), hw.load_choice(p, "bt")) == ("unigen", "unigen")
    hw.save_choice(p, "wifi", "builtin")
    assert (hw.load_choice(p, "wifi"), hw.load_choice(p, "bt")) == ("builtin", "unigen")
    p.write_text('{"use": "toaster"}', encoding="utf-8")
    assert hw.load_choice(p, "bt") is None


def test_save_choice_keeps_other_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"other": 1}', encoding="utf-8")
    hw.save_choice(p, "wifi", "builtin")
    assert json.loads(p.read_text(encoding="utf-8")) == {"other": 1, "wifi": "builtin"}


def test_enable_disable_call_pnp(monkeypatch):
    seen = []
    monkeypatch.setattr(pnp, "set_enabled", lambda i, on, *a, **kw: seen.append((i, on)))
    hw.enable(UNI_WIFI)
    hw.disable(MT_WIFI)
    assert seen == [(UNI_WIFI, True), (MT_WIFI, False)]


# ---- hw.use_wifi / hw.use_bt ----
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
        return hw.use_wifi(target, on_step=self.on_step, on_later=lambda text, ok: self.later_notes.append((text, ok)), path=self.path,
                           clock=itertools.count().__next__, sleep=lambda s: None, spawn=lambda f: f())  # the old Wi-Fi off, inline

    def use_bt(self, target="unigen", spawn=lambda f: f()):  # inline
        self.later_notes = []
        return hw.use_bt(target, on_later=lambda text, ok: self.later_notes.append((text, ok)), path=self.path, spawn=spawn)


@pytest.fixture
def world(monkeypatch, tmp_path):
    return World(monkeypatch, tmp_path)


def test_use_wifi_full_switch_order(world):
    assert world.use() == "unigen"
    # one device change at a time (Windows queues them anyway); the old Wi-Fi last, after the switch reports done
    assert world.calls == [("enable", UNI_WIFI), ("copy", "HOME-5G", "Wi-Fi", "Wi-Fi 2"), ("connect", "Wi-Fi 2", "HOME-5G"),
                           ("disable", MT_WIFI)]
    assert hw.load_choice(world.path, "wifi") == "unigen"
    assert hw.load_choice(world.path, "bt") is None  # Bluetooth is not touched, nor its choice saved
    assert world.steps == ["Turning on the Unigen dongle…", "Connecting to HOME-5G…", "Done. Using the Unigen dongle."]
    assert world.later_notes == [("The Built-in MediaTek is off.", True)]


def test_use_wifi_returns_before_the_old_wifi_goes_off_and_holds_the_lock_until_it_has(world):
    jobs = []
    r = hw.use_wifi("unigen", on_step=world.on_step, path=world.path, clock=itertools.count().__next__, sleep=lambda s: None,
                    spawn=jobs.append)
    assert r == "unigen" and len(jobs) == 1  # Wi-Fi works; the old Wi-Fi not touched yet
    assert ("disable", MT_WIFI) not in world.calls
    with pytest.raises(hw.HwError, match="still finishing"):
        world.use()
    jobs[0]()
    assert ("disable", MT_WIFI) in world.calls and hw._lock.acquire(blocking=False)
    hw._lock.release()


def test_use_wifi_skips_copy_when_dongle_already_has_the_profile(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path, dongle_profile=True)
    w.use()
    assert not any(c[0] == "copy" for c in w.calls) and ("connect", "Wi-Fi 2", "HOME-5G") in w.calls


def test_use_wifi_without_network_skips_connect(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path, connected=False)
    w.use()
    assert [c[0] for c in w.calls] == ["enable", "disable"] and w.calls[-1] == ("disable", MT_WIFI)
    assert hw.load_choice(w.path, "wifi") == "unigen"


def test_use_wifi_target_never_appears_restarts_once_then_rolls_back(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path, appear=False)
    hw.save_choice(w.path, "wifi", "builtin")
    with pytest.raises(hw.HwError) as e:
        w.use()
    assert w.calls == [("enable", UNI_WIFI), ("disable", UNI_WIFI), ("enable", UNI_WIFI), ("disable", UNI_WIFI)]  # Bluetooth untouched
    assert str(e.value) == "The Unigen dongle's Wi-Fi didn't start. You're still on the Built-in MediaTek."
    assert hw.load_choice(w.path, "wifi") == "builtin"


def test_use_wifi_connect_fails_rolls_back(world):
    world.fail_connect = True
    hw.save_choice(world.path, "wifi", "builtin")
    with pytest.raises(hw.HwError, match="You're still on the Built-in MediaTek"):
        world.use()
    assert world.calls[-1] == ("disable", UNI_WIFI)
    assert ("disable", MT_WIFI) not in world.calls and hw.load_choice(world.path, "wifi") == "builtin"
    assert world.bt_calls == []


def test_use_wifi_never_moves_bluetooth(world):
    world.state = {"unigen": {"wifi": True, "bt": False}, "builtin": {"wifi": False, "bt": True}}  # Bluetooth on the other radio
    assert world.use() == "unigen"
    assert world.calls == [] and world.bt_calls == []  # Wi-Fi already on the dongle: nothing to do, Bluetooth stays put
    world.state = {"unigen": {"wifi": False, "bt": False}, "builtin": {"wifi": True, "bt": True}}
    world.use()
    assert world.bt_calls == []


def test_use_wifi_old_wifi_hung_in_a_driver_frees_the_switch_and_says_replug(world, monkeypatch):
    stuck = threading.Event()
    monkeypatch.setattr(hw, "wifi_off", lambda key, d: stuck.wait(5))
    monkeypatch.setattr(hw, "BT_STUCK", 0.05)
    try:
        assert world.use() == "unigen"
        (text, ok), = world.later_notes
        assert not ok and text.startswith("Wi-Fi is stuck") and "Unplug the dongle" in text
        assert hw._lock.acquire(blocking=False)  # switching works again
        hw._lock.release()
    finally:
        stuck.set()


def test_finish_wifi_off_hung_in_a_driver_still_frees_the_lock(monkeypatch):
    stuck, later = threading.Event(), []
    monkeypatch.setattr(hw, "wifi_off", lambda key, d: stuck.wait(5))
    monkeypatch.setattr(hw, "BT_STUCK", 0.05)
    assert hw._lock.acquire(blocking=False)  # use_wifi() holds it for _finish
    try:
        hw._finish("unigen", "builtin", dev(MT_WIFI), lambda text, ok: later.append((text, ok)))
        (text, ok), = later
        assert not ok and text.startswith("Wi-Fi is stuck")
        assert hw._lock.acquire(blocking=False)
        hw._lock.release()
    finally:
        stuck.set()


def test_finish_logs_the_outcome(world, caplog):
    caplog.set_level("INFO", logger="unigen")
    world.use()
    assert "switch to unigen finished: The Built-in MediaTek is off." in caplog.text
    world.use_bt()
    assert "Bluetooth switch to unigen finished: Bluetooth moved to the Unigen dongle." in caplog.text


def test_finish_unexpected_error_is_reported_not_called_stuck(monkeypatch):
    later = []
    def boom(key, d): raise RuntimeError("boom")
    monkeypatch.setattr(hw, "wifi_off", boom)
    assert hw._lock.acquire(blocking=False)
    hw._finish("unigen", "builtin", dev(MT_WIFI), lambda text, ok: later.append((text, ok)))  # BT_STUCK left at 150: must not wait
    assert later == [("Something went wrong finishing the switch; switch again to retry.", False)]
    assert hw._lock.acquire(blocking=False)
    hw._lock.release()


def test_use_wifi_to_unresponsive_dongle_says_replug(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path, appear=False)
    stuck = threading.Event()
    monkeypatch.setattr(hw, "disable", lambda i: stuck.wait(5))
    monkeypatch.setattr(hw, "RESTART_LIMIT", 0.1)
    try:
        with pytest.raises(hw.HwError, match="isn't responding. Unplug it and plug it back in"):
            w.use()
        assert hw._lock.acquire(blocking=False)
        hw._lock.release()
    finally:
        stuck.set()


def test_use_wifi_enable_refused_is_a_plain_sentence(world, monkeypatch):
    def refuse(i): raise winrun.CmdError("Enable-PnpDevice : Access is denied")
    monkeypatch.setattr(hw, "enable", refuse)
    with pytest.raises(hw.HwError) as e:
        world.use()
    assert str(e.value) == "Couldn't turn on the Unigen dongle. You're still on the Built-in MediaTek."


def test_use_wifi_already_in_use_only_saves_choice(world):
    world.state = {"unigen": {"wifi": True, "bt": True}, "builtin": {"wifi": False, "bt": False}}
    assert world.use() == "unigen"
    assert world.calls == [] and world.bt_calls == [] and hw.load_choice(world.path, "wifi") == "unigen"
    assert world.steps == ["Done. Using the Unigen dongle."]


def test_use_wifi_old_wifi_disable_fails_still_succeeds(world):
    world.fail_disable_old = True
    assert world.use() == "unigen"
    assert hw.load_choice(world.path, "wifi") == "unigen"
    assert world.later_notes == [("The Built-in MediaTek couldn't be turned off; Windows may still use it.", False)]


def test_use_wifi_target_not_plugged_in(world):
    del world.state["unigen"]
    with pytest.raises(hw.HwError, match="The Unigen dongle isn't plugged in."):
        world.use()
    assert world.calls == []


# ---- hw.use_bt ----
def test_use_bt_moves_only_bluetooth(world):
    world.use_bt()
    assert world.calls == [("bt", "unigen")]  # no Wi-Fi device touched
    assert hw.load_choice(world.path, "bt") == "unigen" and hw.load_choice(world.path, "wifi") is None
    assert world.later_notes == [("Bluetooth moved to the Unigen dongle.", True)]
    assert hw._lock.acquire(blocking=False)  # released when the move is over
    hw._lock.release()


def test_use_bt_returns_at_once_and_holds_the_lock_until_the_move_ends(world):
    jobs = []
    assert world.use_bt(spawn=jobs.append) is None and world.bt_calls == [] and len(jobs) == 1
    with pytest.raises(hw.HwError, match="still finishing"):
        world.use_bt()
    jobs[0]()
    assert world.bt_calls == ["unigen"] and hw._lock.acquire(blocking=False)
    hw._lock.release()


def test_wifi_and_bluetooth_switches_share_one_lock(world):
    jobs = []
    world.use_bt(spawn=jobs.append)  # a Bluetooth move is pending...
    with pytest.raises(hw.HwError, match="A switch is still finishing."):
        world.use()  # ...so Wi-Fi waits
    jobs[0]()
    wifi_jobs = []
    hw.use_wifi("unigen", on_step=world.on_step, path=world.path, clock=itertools.count().__next__, sleep=lambda s: None,
                spawn=wifi_jobs.append)  # a Wi-Fi tail is pending...
    with pytest.raises(hw.HwError, match="A switch is still finishing."):
        world.use_bt()  # ...so Bluetooth waits
    wifi_jobs[0]()
    world.use_bt()  # and goes once the tail is over
    assert world.bt_calls == ["unigen", "unigen"]


def test_use_bt_choice_is_saved_only_when_the_move_worked(world):
    world.fail_bt = True
    hw.save_choice(world.path, "bt", "builtin")
    world.use_bt()
    assert hw.load_choice(world.path, "bt") == "builtin"  # the watchdog must not retry a failed move
    assert world.later_notes == [("Bluetooth couldn't move and stays on the Built-in MediaTek. Switch again to retry.", False)]
    assert hw._lock.acquire(blocking=False)  # released even when Bluetooth failed
    hw._lock.release()


def test_use_bt_old_radio_stuck_passes_on_what_to_do(world, monkeypatch):
    def stuck(key):
        raise bt.StuckRadio("Windows didn't finish turning off the Built-in MediaTek radio. Switch again in a minute.")
    monkeypatch.setattr(bt, "switch", stuck)
    world.use_bt()
    assert world.later_notes == [("Windows didn't finish turning off the Built-in MediaTek radio. Switch again in a minute.", False)]
    assert hw.load_choice(world.path, "bt") is None


def test_use_bt_hung_in_a_driver_frees_the_switch_and_says_replug(world, monkeypatch):
    stuck = threading.Event()
    monkeypatch.setattr(bt, "switch", lambda key: stuck.wait(5))
    monkeypatch.setattr(hw, "BT_STUCK", 0.05)
    try:
        world.use_bt()
        (text, ok), = world.later_notes
        assert not ok and text.startswith("Bluetooth is stuck") and "Unplug the dongle" in text
        assert hw.load_choice(world.path, "bt") is None
        assert hw._lock.acquire(blocking=False)  # Wi-Fi switching works again
        hw._lock.release()
    finally:
        stuck.set()


def test_use_bt_unexpected_error_is_reported_not_called_stuck(world, monkeypatch):
    def boom(key): raise RuntimeError("boom")
    monkeypatch.setattr(bt, "switch", boom)
    world.use_bt()  # BT_STUCK left at 150: must not wait
    assert world.later_notes == [("Bluetooth couldn't move and stays on the Built-in MediaTek. Switch again to retry.", False)]


def test_use_bt_target_missing_or_without_bluetooth(world, monkeypatch):
    world.use_bt("builtin")
    assert world.bt_calls == ["builtin"]
    monkeypatch.setattr(hw, "devices", lambda: {"unigen": {"present": True, "wifi": dev(UNI_WIFI), "bt": None}})  # no Bluetooth device
    with pytest.raises(hw.HwError, match="The Unigen dongle has no Bluetooth device to turn on."):
        world.use_bt()
    monkeypatch.setattr(hw, "devices", lambda: {})
    with pytest.raises(hw.HwError, match="The Unigen dongle isn't plugged in."):
        world.use_bt()
    assert world.bt_calls == ["builtin"] and hw._lock.acquire(blocking=False)  # a refused switch frees the lock
    hw._lock.release()


def test_second_concurrent_use_refused(world):
    assert hw._lock.acquire(blocking=False)
    try:
        with pytest.raises(hw.HwError, match="A switch is still finishing."):
            world.use()
        with pytest.raises(hw.HwError, match="A switch is still finishing."):
            world.use_bt()
    finally:
        hw._lock.release()


# ---- hw.Follower ----
class Pc:
    """Fake devices() for the watchdog: dongle plugged or not, each adapter's Wi-Fi/Bluetooth on or off."""

    def __init__(self, monkeypatch, tmp_path, choice="unigen", plugged=True, unigen_on=True, bt_choice=None, bt_on=None):
        self.path, self.plugged, self.enabled = tmp_path / "settings.json", plugged, []
        self.state = {"unigen": unigen_on, "builtin": not unigen_on}  # Wi-Fi
        self.bt = {"unigen": unigen_on if bt_on is None else bt_on, "builtin": not (unigen_on if bt_on is None else bt_on)}
        if choice:
            hw.save_choice(self.path, "wifi", choice)
            hw.save_choice(self.path, "bt", bt_choice or choice)
        monkeypatch.setattr(hw, "devices", self.devices)
        monkeypatch.setattr(hw, "enable", self.enable)
        monkeypatch.setattr(hw, "wifi_on", lambda key, d, **kw: hw.enable(d["id"]) or True)
        monkeypatch.setattr(hw, "wifi_off", lambda key, d: (self.offs.append(key), self.state.update({key: False})))
        self.used, self.notes, self.fail, self.offs = [], [], None, []

    def enable(self, dev_id):
        self.enabled.append(dev_id)
        self.state["builtin"] = self.bt["builtin"] = True

    lost = False  # the dongle's Wi-Fi is started but has no WLAN interface

    def devices(self):
        ids = {"unigen": (UNI_WIFI, UNI_BT), "builtin": (MT_WIFI, MT_BT)}
        return {k: {"present": True, "wifi": {**dev(w, self.state[k] and not (self.lost and k == "unigen")),
                                              "lost": self.lost and k == "unigen"}, "bt": dev(b, self.bt[k])}
                for k, (w, b) in ids.items() if k != "unigen" or self.plugged}

    def use_wifi(self, target, **kw):
        self.used.append(("wifi", target))
        if self.fail:
            raise hw.HwError(self.fail)
        self.state = {k: k == target for k in self.state}
        return target

    def use_bt(self, target, **kw):
        self.used.append(("bt", target))
        if self.fail:
            raise hw.HwError(self.fail)
        self.bt = {k: k == target for k in self.bt}

    def follower(self, admin=True):
        return hw.Follower(self.path, lambda t, changed: self.notes.append((t, changed)), admin=admin,
                           use_wifi=self.use_wifi, use_bt=self.use_bt)


def test_follow_unplug_enables_builtin_once(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()  # dongle in use and present: nothing to do
    pc.plugged = False
    f.step()
    f.step()
    assert pc.enabled == [MT_WIFI, MT_BT]
    assert pc.notes == [("The dongle was unplugged. Using the built-in adapter.", True)]
    assert hw.load_choice(pc.path, "wifi") == hw.load_choice(pc.path, "bt") == "unigen"  # the choices stay


def test_follow_unplug_with_builtin_chosen_turns_a_disabled_builtin_bt_back_on(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", plugged=False, unigen_on=False)
    devices = pc.devices
    monkeypatch.setattr(hw, "devices", lambda: {"builtin": {**devices()["builtin"], "bt": dev(MT_BT, False)}})
    pc.follower().step()
    assert pc.enabled == [MT_BT]


def test_follow_second_unplug_notifies_again_with_builtin_chosen(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", unigen_on=False)
    base = pc.devices
    monkeypatch.setattr(hw, "devices", lambda: (lambda d: {**d, "builtin": {**d["builtin"], "bt": dev(MT_BT, False)}})(base()))
    f = pc.follower()
    f.step()
    for _ in range(2):
        pc.plugged = False
        f.step()
        pc.plugged = True
        f.step()
    assert pc.enabled == [MT_BT, MT_BT]
    unplugged, plugged = "The dongle was unplugged. Using the built-in adapter.", "Dongle plugged in."
    assert [t for t, changed in pc.notes] == [unplugged, plugged, unplugged, plugged]  # said again each time


def test_watchdog_moves_off_a_crashed_dongle(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.lost = True
    f.step()
    f.step()
    assert pc.enabled == [] and pc.notes == []  # two passes: maybe just starting up
    f.step()
    assert pc.enabled == [MT_WIFI, MT_BT]
    (text, changed), = pc.notes
    assert "stopped responding" in text and "plug it back in" in text and changed
    f.step()
    assert len(pc.notes) == 1


def test_watchdog_returns_to_the_dongle_after_replug(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.lost = True
    for _ in range(hw.LOST_PASSES):
        f.step()
    pc.lost, pc.plugged = False, False
    f.step()
    assert pc.used == []
    pc.plugged = True
    f.step()
    f.step()
    assert pc.used == [("wifi", "unigen"), ("bt", "unigen")]


def test_brief_missing_interface_is_not_a_crash(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.lost = True
    f.step()
    f.step()
    pc.lost = False
    f.step()
    f.step()
    assert pc.enabled == [] and pc.notes == [] and pc.used == []


def test_watchdog_tells_the_user_before_a_turn_on_that_blocks(monkeypatch, tmp_path, caplog):
    """Windows' PnP service waits on the crashed dongle, so enable() can block until it's re-plugged."""
    caplog.set_level("INFO", logger="unigen")
    pc = Pc(monkeypatch, tmp_path, choice="builtin", unigen_on=False)
    pc.lost = True
    base, seen = pc.devices, []
    monkeypatch.setattr(hw, "devices", lambda: (lambda d: {**d, "builtin": {**d["builtin"], "bt": dev(MT_BT, False)}})(base()))
    def blocked(i):
        seen.append(list(pc.notes))
        raise RuntimeError("hung")
    monkeypatch.setattr(hw, "enable", blocked)
    f = pc.follower()
    for _ in range(hw.LOST_PASSES - 1):
        f.step()
    assert seen == []
    f.step()
    assert len(seen) == 1 and "stopped responding" in seen[0][0][0]  # notified before enable ran
    assert "watchdog: turning on the built-in Bluetooth" in caplog.text


def test_follow_replug_switches_back_once(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    pc.state["builtin"] = True  # what the unplug step enabled
    pc.plugged = True
    f.step()
    assert pc.used == [("wifi", "unigen")]  # Wi-Fi first: its tail holds the lock, so Bluetooth waits for the next pass
    f.step()
    f.step()
    f.step()
    assert pc.used == [("wifi", "unigen"), ("bt", "unigen")]
    assert pc.notes == [("The dongle was unplugged. Using the built-in adapter.", True),
                        ("Dongle plugged in. Using the dongle.", True)]  # one notice, not two


@pytest.mark.parametrize("wifi_choice, bt_choice, restored", [
    ("unigen", "builtin", [("wifi", "unigen")]), ("builtin", "unigen", [("bt", "unigen")]), ("builtin", "builtin", [])])
def test_follow_replug_restores_only_the_switches_set_to_the_dongle(monkeypatch, tmp_path, wifi_choice, bt_choice, restored):
    pc = Pc(monkeypatch, tmp_path, choice=wifi_choice, bt_choice=bt_choice, unigen_on=wifi_choice == "unigen", bt_on=bt_choice == "unigen")
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    pc.plugged = True
    for _ in range(4):
        f.step()
    assert pc.used == restored


def test_follow_failed_replug_does_not_retry(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path)
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    pc.state["builtin"] = True
    pc.plugged, pc.fail = True, "Couldn't finish switching to the Unigen dongle. You're still on the Built-in MediaTek."
    for _ in range(6):
        f.step()
    assert pc.used == [("wifi", "unigen"), ("bt", "unigen")]  # each tried once, neither retried
    assert pc.notes[-1] == (pc.fail, False) and len(pc.notes) == 3


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
    assert pc.used == [("wifi", "unigen"), ("wifi", "unigen")]  # the queue is dropped at the unplug, then filled again


def test_follow_startup_enforces_each_choice(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", unigen_on=True)  # Windows brought the dongle back after a restart
    f = pc.follower()
    f.step()
    assert pc.used == [("wifi", "builtin")]  # Bluetooth waits for the next pass: the Wi-Fi tail holds the lock
    f.step()
    f.step()
    assert pc.used == [("wifi", "builtin"), ("bt", "builtin")] and pc.notes == [("Using the Built-in MediaTek.", True)]


def test_follow_startup_enforces_only_what_differs(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", bt_choice="unigen", unigen_on=True)  # Bluetooth is where it should be
    f = pc.follower()
    for _ in range(3):
        f.step()
    assert pc.used == [("wifi", "builtin")]
    pc = Pc(monkeypatch, tmp_path, choice="unigen", bt_choice="builtin", unigen_on=True)  # Wi-Fi is, Bluetooth is not
    f = pc.follower()
    for _ in range(3):
        f.step()
    assert pc.used == [("bt", "builtin")]


def test_follow_startup_failure_notifies_once(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", bt_choice="unigen", unigen_on=True)
    pc.fail = "Couldn't turn on the Built-in MediaTek."
    f = pc.follower()
    f.step()
    f.step()
    assert pc.used == [("wifi", "builtin")] and pc.notes == [(pc.fail, False)]


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
    f.step()  # fails: logged; the notice already went out, before the turn-on
    assert len(pc.notes) == 1
    f.step()
    f.step()
    assert tries == [MT_WIFI, MT_WIFI, MT_BT] and len(pc.notes) == 1




def test_use_waits_until_the_new_adapter_sees_the_network(world):
    world.visible_after = 3  # a freshly enabled adapter hasn't scanned yet: connecting at once fails
    assert world.use() == "unigen"
    assert world.scans >= 3 and ("connect", "Wi-Fi 2", "HOME-5G") in world.calls


def test_use_wedged_adapter_that_sees_nothing_says_replug(world):
    world.visible_after = 10**6  # the dongle's chip is stuck: scans never find a network
    with pytest.raises(hw.HwError) as e:
        world.use()
    assert str(e.value) == ("The Unigen dongle can't see any Wi-Fi network. Unplug it and plug it back in, then switch "
                            "again. You're still on the Built-in MediaTek.")
    assert world.calls[-1] == ("disable", UNI_WIFI) and not any(c[0] == "connect" for c in world.calls)


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


# ---- the dongle's status ----
def test_dongle_state_connected_not_responding_unplugged(monkeypatch):
    monkeypatch.setattr(hw, "_rows", lambda: ALL)
    monkeypatch.setattr(hw, "_radios", lambda: {k: {"guid": "g", "on": True} for k in ("unigen", "builtin")})
    assert hw.dongle_state(hw.devices()) == "connected"
    monkeypatch.setattr(hw, "_radios", lambda: {"builtin": {"guid": "g", "on": True}})  # started, but no WLAN interface
    assert hw.dongle_state(hw.devices()) == "not_responding"
    monkeypatch.setattr(hw, "_rows", lambda: ALL[2:])
    assert hw.dongle_state(hw.devices()) == "unplugged"


def test_dongle_bluetooth_code_31_is_not_a_crash(monkeypatch):
    """Windows allows one active Bluetooth adapter: with the built-in radio on, the dongle's shows code 31. Normal."""
    rows = [ALL[0], row(UNI_BT, "Generic Bluetooth Adapter", "Error", "CM_PROB_FAILED_ADD"), ALL[2],
            row(MT_BT, "MediaTek Bluetooth Adapter")]
    monkeypatch.setattr(hw, "_rows", lambda: rows)
    monkeypatch.setattr(hw, "_radios", lambda: {k: {"guid": "g", "on": True} for k in ("unigen", "builtin")})
    d = hw.devices()
    assert d["unigen"]["bt"]["ok"] is False and d["unigen"]["wifi"]["lost"] is False
    assert hw.dongle_state(d) == "connected"


def test_follow_tells_the_windows_when_the_dongle_is_plugged_in(monkeypatch, tmp_path):
    pc = Pc(monkeypatch, tmp_path, choice="builtin", unigen_on=False)  # nothing to switch back
    f = pc.follower()
    f.step()
    pc.plugged = False
    f.step()
    assert pc.notes == [("The dongle was unplugged. Using the built-in adapter.", True)]
    pc.plugged = True
    f.step()
    f.step()
    assert pc.notes[-1] == ("Dongle plugged in.", True) and len(pc.notes) == 2 and pc.used == []
