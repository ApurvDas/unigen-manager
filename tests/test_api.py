import json, pathlib, re, threading
import pytest

from tests.conftest import fixture, ROOT
import api, bt, speed, version, winrun, wifi
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
    monkeypatch.setattr(wifi, "interfaces", lambda: [i for i in wifi.parse_interfaces(fixture("interfaces.txt")) if i["name"] == "Wi-Fi"])
    assert api.Api().networks("unigen") == {"ok": False, "error": "The Unigen dongle isn't plugged in."}


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
    api.Api().bt_connect("BluetoothLE#l")
    assert seen == [("020000000011", "Galaxy Buds2 Pro")]


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


# ---- one switch ----
def test_switch_to_needs_admin(hw, monkeypatch):
    monkeypatch.setattr(hwm, "use", lambda *a, **k: pytest.fail("must not switch without admin"))
    assert api.Api(admin=False).switch_to("builtin") == {
        "ok": False, "error": "Switching adapters needs administrator rights. Restart the app and choose Yes."}


def test_switch_to_pushes_steps_and_final(hw, monkeypatch):
    def fake_use(target, *, on_step, on_later, path):
        on_step("Turning on the Built-in MediaTek…")
        on_step("Done. Using the Built-in MediaTek.")
        seen.append(on_later)
        return target
    seen = []
    monkeypatch.setattr(hwm, "use", fake_use)
    a = api.Api(admin=True)
    a._window, a._widget = Win(), Win()
    assert a.switch_to("builtin") == {"ok": True, "data": {"using": "builtin"}}
    for w in (a._window, a._widget):  # both windows hear every step, then the final one
        assert [json.loads(s.split("onSwitchStep(", 1)[1][:-1]) for s in w.scripts] == [
            {"text": "Turning on the Built-in MediaTek…", "done": False, "error": False},
            {"text": "Done. Using the Built-in MediaTek.", "done": False, "error": False},
            {"text": "Done. Using the Built-in MediaTek.", "done": True, "error": False}]
        assert all(s.startswith("window.onSwitchStep && window.onSwitchStep(") for s in w.scripts)
    seen[0]("Bluetooth moved to the Built-in MediaTek.", True)  # later, from the Bluetooth thread: windows reload
    assert json.loads(a._window.scripts[-1].split("onSwitchStep(", 1)[1][:-1]) == {
        "text": "Bluetooth moved to the Built-in MediaTek.", "done": True, "error": False}


def test_switch_to_error_pushes_error_and_returns_message(hw, monkeypatch):
    msg = "Couldn't finish switching to the Built-in MediaTek. You're still on the Unigen dongle."
    monkeypatch.setattr(hwm, "use", raising(hwm.HwError(msg)))
    a = api.Api(admin=True)
    a._window = Win()
    assert a.switch_to("builtin") == {"ok": False, "error": msg}
    assert json.loads(a._window.scripts[-1].split("onSwitchStep(", 1)[1][:-1]) == {"text": msg, "done": True, "error": True}


def test_switch_to_passes_the_settings_path(hw, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(hwm, "use", lambda target, *, on_step, on_later, path: seen.update(path=path) or target)
    api.Api(admin=True, settings_path=tmp_path / "s.json").switch_to("unigen")
    assert seen["path"] == tmp_path / "s.json"


def test_app_info_lists_off_adapter(hw, monkeypatch, tmp_path):
    devs = hwm.devices()
    devs["builtin"]["wifi"] = {"id": "builtin-w", "ok": False, "disabled": True}
    monkeypatch.setattr(hwm, "devices", lambda: devs)
    monkeypatch.setattr(wifi, "interfaces", lambda: [i for i in wifi.parse_interfaces(fixture("interfaces.txt")) if i["name"] == "Wi-Fi 2"])
    hwm.save_choice(tmp_path / "settings.json", "unigen")
    info = api.Api(admin=True).app_info()["data"]
    ads = {a["key"]: a for a in info["adapters"]}
    assert set(ads) == {"unigen", "builtin"} and info["using"] == "unigen"
    assert ads["builtin"] == {"key": "builtin", "name": "Built-in MediaTek", "wifi": None, "bt": "5.2", "using": False, "off": True}
    assert ads["unigen"]["using"] is True and ads["unigen"]["off"] is False and ads["unigen"]["wifi"] == "Wi-Fi 6"


def test_app_info_without_choice_uses_the_connected_adapter(hw):
    info = api.Api().app_info()["data"]
    assert info["using"] == "builtin"  # the fixture's built-in adapter is the one joined to HOME-5G
    assert {a["key"]: a["using"] for a in info["adapters"]} == {"unigen": False, "builtin": True}


def test_app_info_ignores_a_choice_that_is_off(hw, monkeypatch, tmp_path):
    devs = hwm.devices()
    devs["unigen"]["wifi"] = {"id": "unigen-w", "ok": False, "disabled": True}
    monkeypatch.setattr(hwm, "devices", lambda: devs)
    hwm.save_choice(tmp_path / "settings.json", "unigen")  # saved choice, but its Wi-Fi is off right now
    info = api.Api().app_info()["data"]
    assert info["using"] == "builtin" and {a["key"]: a["off"] for a in info["adapters"]} == {"unigen": True, "builtin": False}


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
