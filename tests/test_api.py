import json, pathlib, re, threading
import pytest
from tests.conftest import fixture, ROOT
import api, bt, speed, wifi


def raising(exc):
    def f(*a, **k):
        raise exc
    return f


@pytest.fixture
def hw(monkeypatch):
    """Fixture-backed adapters: built-in connected to HOME-5G, Unigen disconnected."""
    monkeypatch.setattr(wifi, "interfaces", lambda: wifi.parse_interfaces(fixture("interfaces.txt")))
    monkeypatch.setattr(wifi, "networks", lambda iface: wifi.parse_networks(fixture("networks.txt")))
    monkeypatch.setattr(wifi, "profiles", lambda: wifi.parse_profiles(fixture("profiles.txt")))
    monkeypatch.setattr(wifi, "drivers", lambda: wifi.parse_drivers(fixture("drivers.txt")))
    monkeypatch.setattr(bt, "radios", lambda: [
        {"key": "unigen", "id": "U", "name": "Generic Bluetooth Adapter", "ok": True, "disabled": False, "version": "5.4"},
        {"key": "builtin", "id": "M", "name": "MediaTek Bluetooth Adapter", "ok": False, "disabled": True, "version": "5.2"}])


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
    assert info["admin"] is True
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
    monkeypatch.setattr(wifi, "delete_profile", lambda *args: calls.append(("delete",) + args))
    a.copy_profile("oldrouter", "unigen", "builtin")
    a.delete_profile("oldrouter")
    assert calls == [("copy", "oldrouter", "Wi-Fi 2", "Wi-Fi"), ("delete", "oldrouter", ["Wi-Fi 2"])]


def test_bt_switch_needs_admin(hw, monkeypatch):
    monkeypatch.setattr(bt, "switch", lambda key: key)
    assert api.Api(admin=False).bt_switch("builtin") == {"ok": False, "error": "Bluetooth radio switching needs administrator rights. Restart the app and choose Yes."}
    assert api.Api(admin=True).bt_switch("builtin") == {"ok": True, "data": {"active": "builtin"}}
    r = api.Api(admin=False).bt_radio()["data"]
    assert r["active"] == "unigen" and r["can_switch"] is False and r["radios"][1]["name"] == "Built-in MediaTek"


def test_bt_connect_looks_up_address(hw, monkeypatch):
    monkeypatch.setattr(bt, "devices", lambda paired: [{"id": "D1", "name": "JBL Go 3", "connected": False, "kind": "Speaker", "address": "112233445566"}])
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


def test_use_adapter_joins_other_network_then_disconnects_it(hw, monkeypatch):
    calls = []
    monkeypatch.setattr(wifi, "connect", lambda iface, ssid, **kw: calls.append(("connect", iface, ssid, kw["saved"])) or {"rx": 433.0})
    monkeypatch.setattr(wifi, "disconnect", lambda iface: calls.append(("disconnect", iface)))
    monkeypatch.setattr(wifi, "copy_profile", lambda *a: calls.append(("copy",) + a))
    assert api.Api().use_adapter("unigen") == {"ok": True, "data": {"key": "unigen", "ssid": "HOME-5G"}}
    assert calls == [("connect", "Wi-Fi 2", "HOME-5G", True), ("disconnect", "Wi-Fi")]  # Unigen already has the profile


def test_use_adapter_copies_missing_profile_first(hw, monkeypatch):
    calls = []
    prof = wifi.parse_profiles(fixture("profiles.txt"))
    prof["Wi-Fi 2"].remove("HOME-5G")
    monkeypatch.setattr(wifi, "profiles", lambda: prof)
    monkeypatch.setattr(wifi, "connect", lambda iface, ssid, **kw: calls.append(("connect", iface)) or {})
    monkeypatch.setattr(wifi, "disconnect", lambda iface: calls.append(("disconnect", iface)))
    monkeypatch.setattr(wifi, "copy_profile", lambda ssid, src, dst: calls.append(("copy", ssid, src, dst)))
    api.Api().use_adapter("unigen")
    assert calls[0] == ("copy", "HOME-5G", "Wi-Fi", "Wi-Fi 2")


def test_use_adapter_needs_a_connection(hw, monkeypatch):
    ifs = wifi.parse_interfaces(fixture("interfaces.txt"))
    ifs[0]["state"] = "disconnected"
    monkeypatch.setattr(wifi, "interfaces", lambda: ifs)
    assert api.Api().use_adapter("unigen") == {"ok": False, "error": "Neither adapter is connected. Connect to a network first."}


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
