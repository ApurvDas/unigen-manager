import json, pathlib, re, threading, time, types
import pytest

from tests.conftest import fixture, ROOT
import api, bt, speed, traffic, version, winrun, wifi
import hw as hwm  # the `hw` fixture below shadows the module name inside tests


def raising(exc):
    def f(*a, **k):
        raise exc
    return f


@pytest.fixture
def hw(monkeypatch, tmp_path):
    """Fixture-backed adapters: built-in connected to HOME-5G, Unigen disconnected. No saved choice."""
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)  # settings.json lands in tmp, never in the real %LOCALAPPDATA%
    monkeypatch.setattr(hwm, "devices", lambda: {k: {"present": True, "wifi": {"id": k + "-w", "ok": True, "disabled": False},
                                                   "bt": {"id": k + "-b", "ok": True, "disabled": False}} for k in ("unigen", "builtin")})
    monkeypatch.setattr(wifi, "interfaces", lambda: wifi.parse_interfaces(fixture("interfaces.txt")))
    monkeypatch.setattr(wifi, "networks", lambda iface: wifi.parse_networks(fixture("networks.txt")))
    monkeypatch.setattr(wifi, "profiles", lambda: wifi.parse_profiles(fixture("profiles.txt")))
    monkeypatch.setattr(wifi, "drivers", lambda: wifi.parse_drivers(fixture("drivers.txt")))
    monkeypatch.setattr(bt, "radios", lambda: [
        {"key": "unigen", "id": "U", "name": "Generic Bluetooth Adapter", "ok": True, "disabled": False, "version": "5.4"},
        {"key": "builtin", "id": "M", "name": "MediaTek Bluetooth Adapter", "ok": False, "disabled": True, "version": "5.2"}])
    monkeypatch.setattr(bt, "power", lambda: "on")


def test_envelopes(hw, monkeypatch, caplog):
    a = api.Api()
    assert a.adapters()["ok"] is True
    monkeypatch.setattr(wifi, "interfaces", raising(wifi.ParseError("Couldn't read the Wi-Fi status. Is Windows set to English?")))
    assert a.adapters() == {"ok": False, "error": "Couldn't read the Wi-Fi status. Is Windows set to English?"}
    monkeypatch.setattr(wifi, "interfaces", raising(ZeroDivisionError("boom")))
    r = a.adapters()
    assert r == {"ok": False, "error": "Something went wrong. Details are in app.log."}
    assert "ZeroDivisionError" in caplog.text


def test_report_log(hw, monkeypatch, caplog):
    """app.log: actions with their arguments, failures with where they happened, never a password."""
    caplog.set_level("DEBUG", logger="unigen")
    a = api.Api()
    monkeypatch.setattr(wifi, "connect", raising(wifi.WifiError("Couldn't connect to HOME-5G.")))
    a.connect("builtin", "HOME-5G", "hunter2-secret")
    assert "connect('builtin', 'HOME-5G', ***) failed" in caplog.text and "[at " in caplog.text
    assert "hunter2-secret" not in caplog.text
    a.adapters()  # polled: DEBUG, not INFO
    assert any(r.levelname == "DEBUG" and r.getMessage().startswith("adapters() ok") for r in caplog.records)


def test_app_info_versions(hw):
    info = api.Api(admin=True).app_info()["data"]
    assert info["admin"] is True and info["version"] == version.VERSION
    assert {a["key"]: (a["name"], a["wifi"], a["bt"]) for a in info["adapters"]} == {
        "unigen": ("Unigen dongle", "Wi-Fi 6", "5.4"), "builtin": ("Built-in MediaTek", "Wi-Fi 6", "5.2")}


def test_adapters_shape(hw):
    ads = {a["key"]: a for a in api.Api().adapters()["data"]}
    assert ads["builtin"] == {"key": "builtin", "name": "Built-in MediaTek", "state": "connected", "ssid": "HOME-5G",
                              "signal": 80, "rate": 867, "channel": 36, "band": 5}
    assert ads["unigen"]["state"] == "disconnected" and ads["unigen"]["ssid"] is None


def test_networks_states_order_and_hidden(hw):
    nets = api.Api().networks("builtin")["data"]["networks"]
    assert nets[0]["ssid"] == "HOME-5G" and nets[0]["state"] == "Connected"  # connected is pinned first
    by = {n["ssid"]: n for n in nets}
    assert by["Maple House"]["state"] == "" and by["Maple House"]["sec"] == "WPA2"
    assert by[""]["hidden"] is True and by[""]["sec"] == "Open"
    rest = [max(a["s"] for a in n["aps"]) for n in nets[1:]]
    assert rest == sorted(rest, reverse=True)
    uni = {n["ssid"]: n["state"] for n in api.Api().networks("unigen")["data"]["networks"]}
    assert uni["Maple House"] == "Saved" and uni["HOME-5G"] == "Saved"


def test_unplugged_adapter_message(hw, monkeypatch):
    monkeypatch.setattr(hwm, "devices", lambda: {"builtin": {"present": True}})
    monkeypatch.setattr(wifi, "interfaces", lambda: [i for i in wifi.parse_interfaces(fixture("interfaces.txt")) if i["name"] == "Wi-Fi"])
    assert api.Api().networks("unigen") == {"ok": False, "error": "The Unigen dongle isn't plugged in."}


def test_iface_of_crashed_dongle_says_replug(hw, monkeypatch):
    monkeypatch.setattr(wifi, "interfaces", lambda: [i for i in wifi.parse_interfaces(fixture("interfaces.txt")) if i["name"] == "Wi-Fi"])
    assert api.Api().networks("unigen") == {"ok": False, "error": "The Unigen dongle isn't responding. Unplug it and plug it back in."}


def test_connect_new_network_uses_scanned_auth(hw, monkeypatch):
    seen = {}
    def fake_connect(iface, ssid, **kw):
        seen.update(kw, iface=iface, ssid=ssid)
        return {"rx": 144.0}
    monkeypatch.setattr(wifi, "connect", fake_connect)
    r = api.Api().connect("unigen", "AirFiber-Maple House", "12345678")
    assert r == {"ok": True, "data": {"ssid": "AirFiber-Maple House", "rate": 144}}
    assert seen == {"iface": "Wi-Fi 2", "ssid": "AirFiber-Maple House", "auth": "WPA2-Personal", "password": "12345678", "saved": False}
    api.Api().connect("unigen", "Maple House")
    assert seen["saved"] is True
    assert api.Api().connect("unigen", "Far Away", "12345678") == {"ok": False, "error": "Far Away is out of range."}


def test_saved_merge_password_copy_delete(hw, monkeypatch):
    a = api.Api()
    saved = {s["ssid"]: s["on"] for s in a.saved()["data"]}
    assert saved["HOME-5G"] == ["builtin", "unigen"] and saved["oldrouter"] == ["unigen"]
    monkeypatch.setattr(wifi, "password", lambda iface, ssid: f"{iface}:{ssid}")
    assert a.password("oldrouter")["data"] == "Wi-Fi 2:oldrouter"
    assert a.password("nope")["ok"] is False
    calls = []
    monkeypatch.setattr(wifi, "copy_profile", lambda *args: calls.append(("copy",) + args))
    def fake_delete(ssid, ifaces):
        calls.append(("delete", ssid, ifaces))
        for n in ifaces:
            prof[n].remove(ssid)
    prof = wifi.parse_profiles(fixture("profiles.txt"))
    monkeypatch.setattr(wifi, "profiles", lambda: prof)
    monkeypatch.setattr(wifi, "delete_profile", fake_delete)
    a.copy_profile("oldrouter", "unigen", "builtin")
    a.delete_profile("oldrouter")
    assert calls == [("copy", "oldrouter", "Wi-Fi 2", "Wi-Fi"), ("delete", "oldrouter", ["Wi-Fi 2"])]


def test_delete_profile_that_did_not_go_away_is_an_error(hw, monkeypatch):
    monkeypatch.setattr(wifi, "delete_profile", lambda ssid, ifaces: None)  # netsh failed and wifi swallowed it
    assert api.Api().delete_profile("oldrouter") == {"ok": False, "error": "Couldn't delete oldrouter."}


def test_app_info_survives_bluetooth_failure(hw, monkeypatch):
    monkeypatch.setattr(bt, "radios", raising(bt.BtError("no radios")))
    info = api.Api().app_info()
    assert info["ok"] and [a["bt"] for a in info["data"]["adapters"]] == [None, None]


def test_bt_radio_reports_radios_and_admin(hw):
    r = api.Api(admin=False).bt_radio()["data"]
    assert r["active"] == "unigen" and r["can_switch"] is False and r["radios"][1]["name"] == "Built-in MediaTek"


def test_bt_connect_looks_up_address(hw, monkeypatch):
    monkeypatch.setattr(bt, "devices", lambda: [{"id": "D1", "ids": ["D1"], "name": "JBL Go 3", "connected": False, "kind": "Speaker", "address": "112233445566"}])
    seen = []
    monkeypatch.setattr(bt, "connect", lambda address, name: seen.append((address, name)))
    assert api.Api().bt_connect("D1")["ok"] is True and seen == [("112233445566", "JBL Go 3")]
    assert api.Api().bt_connect("gone")["error"] == "That device isn't paired any more."


class FakeWindow:
    def __init__(self):
        self.scripts = []

    def evaluate_js(self, s):
        self.scripts.append(s)


def test_speed_test_pushes_samples_and_saves(hw, monkeypatch, tmp_path):
    monkeypatch.setattr(speed, "addresses", lambda alias: {"ip": "192.168.0.143", "gateway": "192.168.0.1"})
    def fake_run(ip, gw, on_sample):
        on_sample("down", 12.5)
        on_sample("up", 3.0)
        return {"ping": 2, "down": 50, "up": 12, "samples": [12.5, 3.0], "split": 1, "at": "2026-10-13 10:00"}
    monkeypatch.setattr(speed, "run_test", fake_run)
    a = api.Api(results_path=tmp_path / "r.json")
    a._window = FakeWindow()
    r = a.speed_test("builtin")["data"]
    assert r["link"] == 867 and r["down"] == 50
    assert a._window.scripts[0].endswith('window.onSpeedSample({"phase": "down", "v": 12.5})')
    assert a.speed_results()["data"]["builtin"]["down"] == 50


def test_only_one_speed_test_at_a_time(hw, tmp_path):
    a = api.Api(results_path=tmp_path / "r.json")
    a._speed_lock.acquire()
    assert a.speed_test("builtin") == {"ok": False, "error": "A speed test is already running."}


def test_mock_api_matches_python_api():
    js = (ROOT / "ui" / "mock-api.js").read_text(encoding="utf-8")
    mock = set(re.findall(r'def\("(\w+)"', js))
    real = {n for n in dir(api.Api) if not n.startswith("_") and callable(getattr(api.Api, n))}
    assert mock == real


import tray


class FakeWin:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name,) + a)


def test_widget_fit_keeps_bottom_right_above_taskbar(monkeypatch):
    monkeypatch.setattr(tray, "work_area", lambda: (0, 0, 1920, 1040))
    monkeypatch.setattr(tray, "scale", lambda: 1.0)
    a = api.Api()
    a._widget = FakeWin()
    assert a.widget_fit(480.4)["ok"]
    assert a._widget.calls == [("resize", 342, 480), ("move", 1566, 548)]


def test_widget_opens_in_place_before_show(monkeypatch):
    monkeypatch.setattr(tray, "work_area", lambda: (0, 0, 1920, 1040))
    monkeypatch.setattr(tray, "scale", lambda: 1.0)
    a = api.Api()
    a._widget = FakeWin()
    a.widget_fit(300)
    a._widget.calls.clear()
    a._toggle_widget()  # reopening after a move/resize elsewhere: place it first, at the last reported height
    names = [c[0] for c in a._widget.calls]
    assert names.index("resize") < names.index("move") < names.index("show")
    assert a._widget.calls[0] == ("resize", 342, 300)


def test_is_visible_tracks_windows():
    a = api.Api()
    a._widget = FakeWin()
    assert a.is_visible("main") == {"ok": True, "data": True}
    assert a.is_visible("widget")["data"] is False
    a._main_visible = False
    a._toggle_widget()
    assert a.is_visible("main")["data"] is False and a.is_visible("widget")["data"] is True
    a.hide_widget()
    assert a.is_visible("widget")["data"] is False
    a._window = FakeWin()
    a._show_main()
    assert a.is_visible("main")["data"] is True
    assert ("evaluate_js", "window.onMainShown && window.onMainShown()") in a._window.calls  # refreshes at once


def test_toggle_ignores_the_click_that_blurred_it(monkeypatch):
    a = api.Api()
    a._widget = FakeWin()
    a._toggle_widget()  # opens
    assert ("show",) in a._widget.calls
    a.hide_widget()  # the widget hides itself when it loses focus (the tray click does that)...
    a._widget.calls.clear()
    a._toggle_widget()  # ...so this same click must not reopen it
    assert ("show",) not in a._widget.calls


def test_open_main_shows_window_and_hides_widget():
    a = api.Api()
    a._window, a._widget = FakeWin(), FakeWin()
    assert a.open_main()["ok"]
    assert ("show",) in a._window.calls and ("hide",) in a._widget.calls


def test_connected_network_without_details_uses_adapter_status(hw, monkeypatch):
    bare = "\nSSID 1 : HOME-5G\n    Network type            : Infrastructure\n    Authentication          : WPA2-Personal\n"
    monkeypatch.setattr(wifi, "networks", lambda iface: wifi.parse_networks(bare))
    nets = api.Api().networks("builtin")["data"]["networks"]
    assert nets[0]["state"] == "Connected" and nets[0]["aps"] == [{"b": 5, "ch": 36, "s": 80}]


ROWS = [{"id": "Bluetooth#c", "ids": ["Bluetooth#c", "BluetoothLE#l"], "name": "Galaxy Buds2 Pro", "kind": "Headphones",
         "connected": False, "address": "020000000011"}]


class Win:
    def __init__(self, on_script=None): self.scripts, self.on_script = [], on_script
    def evaluate_js(self, s):
        self.scripts.append(s)
        if self.on_script: self.on_script(s)


def test_bt_pair_prompts_page_and_uses_answer(monkeypatch):
    a, got = api.Api(), []
    a._window = Win(lambda s: a.bt_pair_answer(True, "0000") if "onPairPrompt" in s else None)
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: got.append(ask("provide", "")))
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(bt, "connect", lambda *a, **k: None)
    r = a.bt_pair("BluetoothLE#l")
    assert got == [(True, "0000")] and '"kind": "provide"' in a._window.scripts[0]
    assert r == {"ok": True, "data": dict(ROWS[0], connected=True)}  # audio device connected right away


def test_bt_pair_display_pin_does_not_wait(monkeypatch):
    a, got = api.Api(), []
    a._window = Win()
    monkeypatch.setattr(api, "PAIR_WAIT", 5)
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: got.append(ask("display", "482913")))
    monkeypatch.setattr(bt, "devices", lambda: [])
    assert a.bt_pair("Bluetooth#k") == {"ok": True, "data": None} and got == [(True, None)]


def test_pair_prompt_times_out_and_declines(monkeypatch):
    a, got = api.Api(), []
    a._window = Win()
    monkeypatch.setattr(api, "PAIR_WAIT", 0.01)
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: got.append(ask("confirm", "482913")))
    monkeypatch.setattr(bt, "devices", lambda: [])
    a.bt_pair("Bluetooth#p")
    assert got == [(False, None)]


def test_bt_pair_audio_connect_failure_is_not_an_error(monkeypatch):
    a = api.Api()
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: None)
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in ROWS])
    def nope(*a, **k): raise bt.BtError("refused")
    monkeypatch.setattr(bt, "connect", nope)
    assert a.bt_pair("Bluetooth#c")["data"]["connected"] is False


def test_bt_remove_unpairs_every_twin(monkeypatch):
    removed = []
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(bt, "remove", removed.append)
    api.Api().bt_remove("BluetoothLE#l")
    assert removed == [["Bluetooth#c", "BluetoothLE#l"]]


def test_bt_connect_uses_classic_address_of_twin(monkeypatch):
    seen = []
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(bt, "connect", lambda addr, name: seen.append((addr, name)))
    monkeypatch.setattr(bt, "power", lambda: "on")
    api.Api().bt_connect("BluetoothLE#l")
    assert seen == [("020000000011", "Galaxy Buds2 Pro")]


@pytest.mark.parametrize("state, error", [
    ("off", "Bluetooth is off. Turn it on, then connect."),
    ("unknown", "Bluetooth isn't ready yet. If you just switched adapters, it's still moving: try again in a moment.")])
def test_bt_connect_with_bluetooth_off_or_moving_says_so(monkeypatch, state, error):
    fake_time(monkeypatch, [0.0])
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(bt, "power", lambda: state)
    monkeypatch.setattr(bt, "connect", lambda *a, **k: pytest.fail("must not try, nor open Settings"))
    assert api.Api().bt_connect("Bluetooth#c") == {"ok": False, "error": error}


def test_app_info_reads_drivers_once_until_an_adapter_changes(hw, monkeypatch):
    calls = []
    real = wifi.drivers
    monkeypatch.setattr(wifi, "drivers", lambda: calls.append(1) or real())
    a = api.Api()
    a.app_info(), a.app_info()
    assert len(calls) == 1
    monkeypatch.setattr(wifi, "interfaces", lambda: wifi.parse_interfaces(fixture("interfaces.txt"))[:1])  # one unplugged
    a.app_info()
    assert len(calls) == 2


def test_push_to_a_closing_window_is_skipped(monkeypatch):
    class Gone:
        def evaluate_js(self, s): raise RuntimeError("ObjectDisposedException")
    a = api.Api()
    a._window, a._widget = Gone(), Win()
    a._push("x()")  # must not raise
    assert a._widget.scripts == ["x()"]


AWAY = [dict(ROWS[0], here=False)]


def test_bt_pair_on_a_row_from_the_other_radio_pairs_it_here(hw, monkeypatch):
    paired = []
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in AWAY])
    monkeypatch.setattr(bt, "here_id", lambda addr: f"here-{addr}")
    monkeypatch.setattr(bt, "pair", lambda dev_id, ask: paired.append(dev_id))
    monkeypatch.setattr(bt, "connect", lambda *a, **k: None)
    r = api.Api().bt_pair("Bluetooth#c")
    assert paired == ["here-020000000011"]
    assert r["data"]["radio_name"] == "Built-in MediaTek" and r["data"]["here_name"] == "Unigen dongle"


def test_bt_connect_on_a_row_from_the_other_radio_explains(hw, monkeypatch):
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in AWAY])
    monkeypatch.setattr(bt, "connect", lambda *a, **k: pytest.fail("must not try the audio ways"))
    assert api.Api().bt_connect("Bluetooth#c") == {"ok": False, "error":
        "Galaxy Buds2 Pro is paired with the Built-in MediaTek, not this one. Put it in pairing mode, then press Re-pair."}
    assert api.Api().bt_paired()["data"][0]["here_name"] == "Unigen dongle"


def test_bt_search_pushes_rows_to_main_window(monkeypatch):
    a = api.Api()
    a._window = Win()
    monkeypatch.setattr(bt, "search_start", lambda on_change: on_change(ROWS, True))
    assert a.bt_search_start() == {"ok": True, "data": None}
    assert a._window.scripts[0].startswith("window.onBtNearby && window.onBtNearby(") and '"done": true' in a._window.scripts[0]


def test_bt_radio_power(hw, monkeypatch):
    monkeypatch.setattr(bt, "power", lambda: "off")
    assert api.Api().bt_radio()["data"]["power"] == "off"
    calls = []
    monkeypatch.setattr(bt, "set_power", calls.append)
    assert api.Api().bt_power(1) == {"ok": True, "data": {"power": "off"}} and calls == [True]


# ---- two switches ----
def pushed(w):
    return [json.loads(s.split("onSwitchStep(", 1)[1][:-1]) for s in w.scripts]


def test_switch_wifi_needs_admin(hw, monkeypatch):
    monkeypatch.setattr(hwm, "use_wifi", lambda *a, **k: pytest.fail("must not switch without admin"))
    assert api.Api(admin=False).switch_wifi("builtin") == {
        "ok": False, "error": "Switching adapters needs administrator rights. Restart the app and choose Yes."}


def test_switch_bt_needs_admin(hw, monkeypatch):
    monkeypatch.setattr(hwm, "use_bt", lambda *a, **k: pytest.fail("must not switch without admin"))
    assert api.Api(admin=False).switch_bt("builtin") == {
        "ok": False, "error": "Switching adapters needs administrator rights. Restart the app and choose Yes."}


def test_switch_wifi_pushes_steps_and_final(hw, monkeypatch):
    def fake_use(target, *, on_step, on_later, path):
        on_step("Turning on the Built-in MediaTek…", step=1, of=2, label="Turning on the Built-in MediaTek")
        on_step("Turning off the Unigen dongle…", step=2, of=2, label="Turning off the Unigen dongle", later=True)
        seen.append(on_later)
        return target
    seen = []
    monkeypatch.setattr(hwm, "use_wifi", fake_use)
    a = api.Api(admin=True)
    a._window, a._widget = Win(), Win()
    assert a.switch_wifi("builtin") == {"ok": True, "data": {"using": "builtin"}}
    for w in (a._window, a._widget):  # both windows hear every step; the last one finishes in the background, so no end yet
        assert pushed(w) == [
            {"kind": "wifi", "text": "Turning on the Built-in MediaTek…", "done": False, "error": False, "step": 1, "of": 2,
             "label": "Turning on the Built-in MediaTek"},
            {"kind": "wifi", "text": "Turning off the Unigen dongle…", "done": False, "error": False, "step": 2, "of": 2,
             "label": "Turning off the Unigen dongle"}]
        assert all(s.startswith("window.onSwitchStep && window.onSwitchStep(") for s in w.scripts)
    seen[0]("The Unigen dongle is off.", True)  # later, from the background thread: the move is over, windows reload
    assert pushed(a._window)[-1] == {"kind": "wifi", "text": "Wi-Fi moved to the Built-in MediaTek.", "done": True, "error": False,
                                     "step": 2, "of": 2, "label": "Turning off the Unigen dongle"}
    seen[0]("The Unigen dongle couldn't be turned off; Windows may still use it.", False)
    assert pushed(a._window)[-1]["error"] is True and pushed(a._window)[-1]["text"].startswith("The Unigen dongle couldn't")


def test_switch_wifi_with_no_old_wifi_to_turn_off_ends_when_it_returns(hw, monkeypatch):
    def fake_use(target, *, on_step, on_later, path):
        on_step("Turning on the Built-in MediaTek…", step=1, of=2, label="Turning on the Built-in MediaTek")
        on_step("Done. Using the Built-in MediaTek.", step=2, of=2, label="Done")
        return target
    monkeypatch.setattr(hwm, "use_wifi", fake_use)
    a = api.Api(admin=True)
    a._window = Win()
    a.switch_wifi("builtin")
    assert pushed(a._window)[-1] == {"kind": "wifi", "text": "Wi-Fi moved to the Built-in MediaTek.", "done": True, "error": False,
                                     "step": 2, "of": 2, "label": "Done"}


def test_a_failed_switch_names_the_step_it_stopped_at(hw, monkeypatch):
    def fake_use(target, *, on_step, on_later, path):
        on_step("Finding HOME-5G…", step=3, of=5, label="Finding HOME-5G")
        raise hwm.HwError("The Built-in MediaTek can't see any Wi-Fi network.")
    monkeypatch.setattr(hwm, "use_wifi", fake_use)
    a = api.Api(admin=True)
    a._window = Win()
    assert a.switch_wifi("builtin")["ok"] is False
    assert pushed(a._window)[-1] == {"kind": "wifi", "text": "The Built-in MediaTek can't see any Wi-Fi network.", "done": True,
                                     "error": True, "step": 3, "of": 5, "label": "Finding HOME-5G"}


def test_a_switch_pressed_while_another_runs_doesnt_end_the_running_one(hw, monkeypatch):
    for method, use in (("switch_wifi", "use_wifi"), ("switch_bt", "use_bt")):
        monkeypatch.setattr(hwm, use, raising(hwm._busy()))
        a = api.Api(admin=True)
        a._window = Win()
        assert getattr(a, method)("builtin")["error"].startswith("A switch is still finishing")
        assert pushed(a._window) == []  # a done step would close the bar of the move that is really running


def test_switch_wifi_error_pushes_error_and_returns_message(hw, monkeypatch):
    msg = "Couldn't finish switching to the Built-in MediaTek. You're still on the Unigen dongle."
    monkeypatch.setattr(hwm, "use_wifi", raising(hwm.HwError(msg)))
    a = api.Api(admin=True)
    a._window = Win()
    assert a.switch_wifi("builtin") == {"ok": False, "error": msg}
    assert pushed(a._window)[-1] == {"kind": "wifi", "text": msg, "done": True, "error": True, "step": None, "of": None, "label": None}


def test_switch_wifi_passes_the_settings_path(hw, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(hwm, "use_wifi", lambda target, *, on_step, on_later, path: seen.update(path=path) or target)
    api.Api(admin=True, settings_path=tmp_path / "s.json").switch_wifi("unigen")
    assert seen["path"] == tmp_path / "s.json"


def test_switch_bt_returns_at_once_and_pushes_the_end_of_the_move(hw, monkeypatch):
    def fake_use(target, *, on_step, on_later, path):
        on_step("Moving Bluetooth to the Built-in MediaTek. This can take up to a minute.", step=0, of=4, label="Starting")
        on_step("Turning off the Unigen dongle radio…", step=2, of=4, label="Turning off the Unigen dongle radio")
        seen.append(on_later)
    seen = []
    monkeypatch.setattr(hwm, "use_bt", fake_use)
    a = api.Api(admin=True)
    a._window, a._widget = Win(), Win()
    assert a.switch_bt("builtin") == {"ok": True, "data": {"using": "builtin"}}
    for w in (a._window, a._widget):  # not done yet: the page waits for the move
        assert pushed(w) == [
            {"kind": "bt", "text": "Moving Bluetooth to the Built-in MediaTek. This can take up to a minute.", "done": False,
             "error": False, "step": 0, "of": 4, "label": "Starting"},
            {"kind": "bt", "text": "Turning off the Unigen dongle radio…", "done": False, "error": False, "step": 2, "of": 4,
             "label": "Turning off the Unigen dongle radio"}]
    seen[0]("Bluetooth moved to the Built-in MediaTek.", True)
    assert pushed(a._window)[-1] == {"kind": "bt", "text": "Bluetooth moved to the Built-in MediaTek.", "done": True, "error": False,
                                     "step": 2, "of": 4, "label": "Turning off the Unigen dongle radio"}
    seen[0]("Bluetooth couldn't move and stays on the Unigen dongle. Switch again to retry.", False)
    last = pushed(a._widget)[-1]
    assert last["error"] is True and last["kind"] == "bt" and last["step"] == 2  # the failed block is the step it stopped at


def test_switch_bt_error_pushes_error_and_returns_message(hw, monkeypatch):
    msg = "The Built-in MediaTek has no Bluetooth device to turn on."
    monkeypatch.setattr(hwm, "use_bt", raising(hwm.HwError(msg)))
    a = api.Api(admin=True)
    a._window = Win()
    assert a.switch_bt("builtin") == {"ok": False, "error": msg}
    assert pushed(a._window)[-1] == {"kind": "bt", "text": msg, "done": True, "error": True, "step": None, "of": None, "label": None}


def test_switch_bt_passes_the_settings_path(hw, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(hwm, "use_bt", lambda target, *, on_step, on_later, path: seen.update(path=path))
    api.Api(admin=True, settings_path=tmp_path / "s.json").switch_bt("unigen")
    assert seen["path"] == tmp_path / "s.json"


def fake_time(monkeypatch, now):  # api's own clock, so the wait costs no real time and the rest of pytest keeps the real one
    monkeypatch.setattr(api, "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s),
                                                           time=time.time))


def test_bt_connect_waits_for_windows_to_have_the_radio_then_connects(monkeypatch):
    """After a switch Windows' radio object appears a few seconds late (the 12:15 log): Connect waits for it."""
    seen, now, states = [], [0.0], iter(["unknown", "unknown", "unknown", "on"])
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(bt, "power", lambda: next(states))
    monkeypatch.setattr(bt, "connect", lambda addr, name: seen.append(name))
    fake_time(monkeypatch, now)
    assert api.Api().bt_connect("Bluetooth#c")["ok"] is True and seen == ["Galaxy Buds2 Pro"] and now[0] == 1.5


def test_bt_connect_gives_up_after_eight_seconds_without_a_radio(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(bt, "devices", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(bt, "power", lambda: "unknown")
    monkeypatch.setattr(bt, "connect", lambda *a, **k: pytest.fail("no radio, nothing to connect through"))
    fake_time(monkeypatch, now)
    r = api.Api().bt_connect("Bluetooth#c")
    assert r["ok"] is False and r["error"].startswith("Bluetooth isn't ready yet") and now[0] == api.READY_WAIT


def test_app_info_lists_off_adapter(hw, monkeypatch, tmp_path):
    devs = hwm.devices()
    devs["builtin"]["wifi"] = {"id": "builtin-w", "ok": False, "disabled": True}
    monkeypatch.setattr(hwm, "devices", lambda: devs)
    monkeypatch.setattr(wifi, "interfaces", lambda: [i for i in wifi.parse_interfaces(fixture("interfaces.txt")) if i["name"] == "Wi-Fi 2"])
    hwm.save_choice(tmp_path / "settings.json", "wifi", "unigen")
    info = api.Api(admin=True).app_info()["data"]
    ads = {a["key"]: a for a in info["adapters"]}
    assert set(ads) == {"unigen", "builtin"} and info["wifi_using"] == "unigen"
    assert ads["builtin"] == {"key": "builtin", "name": "Built-in MediaTek", "wifi": None, "bt": "5.2", "using": False, "off": True}
    assert ads["unigen"]["using"] is True and ads["unigen"]["off"] is False and ads["unigen"]["wifi"] == "Wi-Fi 6"


def test_app_info_without_choice_uses_the_connected_adapter(hw):
    info = api.Api().app_info()["data"]
    assert info["wifi_using"] == "builtin"  # the fixture's built-in adapter is the one joined to HOME-5G
    assert {a["key"]: a["using"] for a in info["adapters"]} == {"unigen": False, "builtin": True}


def test_app_info_ignores_a_choice_that_is_off(hw, monkeypatch, tmp_path):
    devs = hwm.devices()
    devs["unigen"]["wifi"] = {"id": "unigen-w", "ok": False, "disabled": True}
    monkeypatch.setattr(hwm, "devices", lambda: devs)
    hwm.save_choice(tmp_path / "settings.json", "wifi", "unigen")  # saved choice, but its Wi-Fi is off right now
    info = api.Api().app_info()["data"]
    assert info["wifi_using"] == "builtin" and {a["key"]: a["off"] for a in info["adapters"]} == {"unigen": True, "builtin": False}


def test_app_info_survives_hw_failure(hw, monkeypatch):
    monkeypatch.setattr(hwm, "devices", raising(winrun.CmdError("powershell.exe took longer than 90 s.")))
    info = api.Api().app_info()["data"]
    assert {a["key"] for a in info["adapters"]} == {"unigen", "builtin"} and not any(a["off"] for a in info["adapters"])


def test_follow_notify_pushes_reload_when_changed(hw):
    shown = []
    a = api.Api()
    a._window, a._widget, a._notify = Win(), Win(), shown.append
    a._follow_notify("The dongle was unplugged. Using the built-in adapter.", True)
    a._follow_notify("Couldn't turn on the Unigen dongle.", False)
    assert shown == ["The dongle was unplugged. Using the built-in adapter.", "Couldn't turn on the Unigen dongle."]
    for w in (a._window, a._widget):
        assert w.scripts == ["window.onUsingChanged && window.onUsingChanged()"]


def test_app_info_reads_the_old_one_switch_setting(hw, tmp_path):
    (tmp_path / "settings.json").write_text('{"use": "unigen"}', encoding="utf-8")
    assert api.Api().app_info()["data"]["wifi_using"] == "unigen"


# ---- dongle status ----
REAL_DEVICES = hwm.devices  # the `hw` fixture swaps it for fixture-backed adapters


def dongle(a):
    return a.app_info()["data"]["dongle"]


def test_app_info_dongle_connected_not_responding_or_unplugged(hw, monkeypatch):
    devs = hwm.devices()
    monkeypatch.setattr(hwm, "devices", lambda: devs)
    assert dongle(api.Api()) == "connected"
    devs["unigen"]["wifi"] = {"id": "unigen-w", "ok": False, "disabled": False, "lost": True}  # started, no WLAN interface
    assert dongle(api.Api()) == "not_responding"
    del devs["unigen"]
    assert dongle(api.Api()) == "unplugged"


def test_app_info_dongle_bluetooth_code_31_counts_as_connected(hw, monkeypatch):
    """Windows allows one active Bluetooth adapter: with the built-in radio on, the dongle's shows code 31. Normal."""
    uni, mt = r"USB\VID_368B&PID_8D81&MI_%s\7&AAAA0001&0&0000", r"PCI\VEN_14C3&DEV_7961\4&BBBB0002&0&00E0"
    rows = [{"id": uni % "02", "name": "AIC8800D80 USB WiFi", "status": "OK", "problem": "CM_PROB_NONE"},
            {"id": uni % "00", "name": "Generic Bluetooth Adapter", "status": "Error", "problem": "CM_PROB_FAILED_ADD"},
            {"id": mt, "name": "MediaTek Wi-Fi 6 MT7921 Wireless LAN Card", "status": "OK", "problem": "CM_PROB_NONE"},
            {"id": r"USB\VID_13D3&PID_3563\0", "name": "MediaTek Bluetooth Adapter", "status": "OK", "problem": "CM_PROB_NONE"}]
    monkeypatch.setattr(hwm, "devices", REAL_DEVICES)
    monkeypatch.setattr(hwm, "_rows", lambda: rows)
    monkeypatch.setattr(hwm, "_radios", lambda: {k: {"guid": "g", "on": True} for k in ("unigen", "builtin")})
    assert hwm.devices()["unigen"]["bt"]["ok"] is False
    assert dongle(api.Api()) == "connected"
    monkeypatch.setattr(hwm, "_radios", lambda: {"builtin": {"guid": "g", "on": True}})  # now its Wi-Fi really is gone
    assert dongle(api.Api()) == "not_responding"


def test_app_info_dongle_is_unknown_without_the_device_list(hw, monkeypatch):
    monkeypatch.setattr(hwm, "devices", raising(winrun.CmdError("powershell.exe took longer than 90 s.")))
    assert dongle(api.Api()) is None


def test_tray_tooltip_adds_the_dongle_only_when_it_is_not_there(hw, monkeypatch):
    devs = hwm.devices()
    monkeypatch.setattr(hwm, "devices", lambda: devs)
    a = api.Api()
    a.STATUS_EVERY = 0  # no reuse: every call below reads the dongle state again
    assert a._status() == "Built-in MediaTek: HOME-5G, 80%"
    devs["unigen"]["wifi"] = {"id": "unigen-w", "ok": False, "disabled": False, "lost": True}
    assert a._status() == "Built-in MediaTek: HOME-5G, 80% · Dongle not responding"
    del devs["unigen"]
    assert a._status() == "Built-in MediaTek: HOME-5G, 80% · Dongle unplugged"
    assert len(a._status()) <= 127  # Windows caps tray tooltips at 128 characters
    monkeypatch.setattr(hwm, "devices", raising(winrun.CmdError("busy")))
    assert a._status() == "Built-in MediaTek: HOME-5G, 80%"


# ---- traffic ----
class FakeSampler:
    def __init__(self, rates=None, on=None):
        self.rates, self.on = rates or {}, on if on is not None else {"unigen": False, "builtin": True}

    def rate(self, key):
        return self.rates.get(key)

    def radios(self):
        return self.on

    def snapshot(self):
        return {"tick": 7, "adapters": [{"key": k, "name": wifi.ADAPTER_NAMES[k], "down": 10, "up": 2, "history": [[10, 2]]} for k in self.on],
                "today": {k: {"down": 5, "up": 1} for k in self.on}}


def test_traffic_payload(hw):
    r = api.Api(sampler=FakeSampler())
    d = r.traffic()["data"]
    assert d["using"] == "builtin" and d["unit"] == "bytes" and d["tick"] == 7
    assert d["adapters"][0] == {"key": "unigen", "name": "Unigen dongle", "down": 10, "up": 2, "history": [[10, 2]]}
    assert d["today"]["builtin"] == {"down": 5, "up": 1}
    hwm.save_choice(r._settings, "wifi", "unigen")  # the saved choice is used only while its radio is on
    assert r.traffic()["data"]["using"] == "builtin"
    r._sampler.on["unigen"] = True
    assert r.traffic()["data"]["using"] == "unigen"
    r._sampler.on = {}
    d = r.traffic()["data"]
    assert d["using"] is None and d["adapters"] == [] and d["today"] == {}


def test_traffic_works_without_a_running_sampler(hw):
    d = api.Api().traffic()["data"]  # an unstarted sampler: nothing measured yet
    assert d["adapters"] == [] and d["using"] is None and d["unit"] == "bytes"


def test_set_traffic_unit_saves_keeps_other_keys_and_pushes_to_both_windows(hw):
    a = api.Api(sampler=FakeSampler())
    a._window, a._widget = FakeWindow(), FakeWindow()
    hwm.save_choice(a._settings, "wifi", "unigen")
    assert a.set_traffic_unit("bits") == {"ok": True, "data": {"unit": "bits"}}
    assert json.loads(a._settings.read_text(encoding="utf-8")) == {"wifi": "unigen", "traffic_unit": "bits"}
    assert a.traffic()["data"]["unit"] == "bits"
    for w in (a._window, a._widget):
        assert w.scripts == ['window.onTrafficUnit && window.onTrafficUnit("bits")']
    assert a.set_traffic_unit("furlongs")["ok"] is False
    assert json.loads(a._settings.read_text(encoding="utf-8"))["traffic_unit"] == "bits"  # a bad value saves nothing
    a._settings.write_text('{"traffic_unit": "nonsense"}', encoding="utf-8")
    assert a.traffic()["data"]["unit"] == "bytes"  # a bad value in the file falls back


def test_tooltip_shows_the_live_rate_in_the_chosen_unit_and_stays_short(hw, monkeypatch):
    a = api.Api(sampler=FakeSampler({"builtin": (4_200_000, 300_000)}))
    assert a._status() == "Built-in MediaTek: HOME-5G, 80% · ↓4.2 MB/s ↑300 KB/s"
    a.set_traffic_unit("bits")
    assert a._status() == "Built-in MediaTek: HOME-5G, 80% · ↓33.6 Mbps ↑2.4 Mbps"
    a._sampler.rates = {"builtin": (999_000_000, 999_000_000)}
    devs = hwm.devices()
    del devs["unigen"]
    monkeypatch.setattr(hwm, "devices", lambda: devs)
    a._base = None
    assert len(a._status()) <= 127
    a._sampler.rates = {}
    assert a._status() == "Built-in MediaTek: HOME-5G, 80% · Dongle unplugged"  # still measuring: no rate shown


def test_tooltip_reuses_the_netsh_part_for_ten_seconds_but_not_the_rate(hw, monkeypatch):
    a, n = api.Api(sampler=FakeSampler({"builtin": (1_000_000, 0)})), []
    real = wifi.interfaces
    monkeypatch.setattr(wifi, "interfaces", lambda: n.append(1) or real())
    first = a._status()
    a._sampler.rates = {"builtin": (2_000_000, 0)}
    assert a._status() != first and "↓2.0 MB/s" in a._status()
    assert len(n) == 1  # netsh ran once for three tooltips
    a._base = (a._base[0] - api.Api.STATUS_EVERY - 1,) + a._base[1:]
    a._status()
    assert len(n) == 2
