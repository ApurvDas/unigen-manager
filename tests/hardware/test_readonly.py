"""Read-only checks against this PC's real adapters. Run: py -3.10 -m pytest -m hardware"""
import os, re
from pathlib import Path

import pytest

import api, bt, hw, speed, traffic, wifi

pytestmark = pytest.mark.hardware


def by_key():
    return {wifi.adapter_key(i["description"]): i for i in wifi.interfaces()}


def test_wifi_adapter_in_use_is_listed():
    # the one switch turns the other adapter's Wi-Fi off, so netsh lists only the one in use
    import hw
    on = {k for k, d in hw.devices().items() if d["wifi"] and d["wifi"]["ok"]}
    assert on and on <= set(by_key())


def test_drivers_report_wifi_6():
    drv = wifi.drivers()
    for i in by_key().values():
        assert wifi.wifi_standard(drv[i["name"]]["radio_types"]) == "Wi-Fi 6"


def test_networks_and_profiles_parse():
    for i in by_key().values():
        assert isinstance(wifi.networks(i["name"]), list)
    assert any(wifi.profiles().values())


def test_trigger_scan_accepted():
    for i in by_key().values():
        wifi.trigger_scan(i["guid"])


def test_scan_returns_when_windows_finishes():
    # Windows reports scan-complete after ~1.5 s; the app used to sleep a fixed 4 s
    import time
    for i in by_key().values():
        t = time.perf_counter()
        wifi.scan(i["name"], i["guid"])
        assert time.perf_counter() - t < 3.5


def test_bluetooth_radios_and_versions():
    rs = {r["key"]: r for r in bt.radios()}
    assert rs["builtin"]["version"] == "5.2"
    assert "unigen" not in rs or rs["unigen"]["version"] == "5.4"  # the dongle may be unplugged
    assert any(r["ok"] for r in rs.values())


def test_paired_devices_list():
    devs = bt.devices()
    assert all(set(d) == {"id", "ids", "name", "connected", "kind", "address", "battery", "here"} for d in devs)
    assert all(isinstance(d["here"], bool) for d in devs)


def test_ping_router_from_connected_adapter():
    i = next((i for i in by_key().values() if i["state"] == "connected"), None)
    if i is None:
        pytest.skip("no adapter is connected")
    a = speed.addresses(i["name"])
    assert speed.ping(a["ip"], a["gateway"], count=3) >= 0


def test_api_end_to_end_reads():
    a = api.Api()
    key = a.adapters()["data"][0]["key"]  # the adapter in use; the other one is off
    for name, args in [("app_info", ()), ("adapters", ()), ("saved", ()), ("bt_radio", ()), ("bt_paired", ()), ("networks", (key,))]:
        r = getattr(a, name)(*args)
        assert r["ok"], (name, r)


def test_saved_password_readable_without_printing_it():
    a = api.Api()
    first = a.saved()["data"][0]["ssid"]
    r = a.password(first)
    readable = r["ok"] and isinstance(r["data"], str) and len(r["data"]) > 0
    assert readable, "could not read a saved password"  # never put the value in the assertion


def test_launcher_present():
    assert Path(os.environ["WINDIR"], "pyw.exe").exists()


def test_winrt_bluetooth_reads():
    import btwinrt
    assert btwinrt.power() in ("on", "off")
    rows = btwinrt.paired()
    assert all({"id", "ids", "name", "kind", "connected", "address"} <= set(r) for r in rows)
    local = btwinrt.local_address()
    assert re.fullmatch(r"[0-9a-f]{12}", local or "")


def test_hw_devices_finds_both_adapters():
    devs = hw.devices()
    if "unigen" not in devs:
        pytest.skip("the dongle isn't plugged in")
    assert {"unigen", "builtin"} <= set(devs)
    for k in ("unigen", "builtin"):
        assert devs[k]["wifi"] is not None and devs[k]["bt"] is not None, (k, devs[k])


def test_paired_list_is_fast():
    # the association-endpoint query with an explicit kind waits ~30 s before returning; the device selectors don't
    import time, btwinrt
    t = time.perf_counter()
    btwinrt.paired()
    assert time.perf_counter() - t < 3


def test_device_reads_are_fast():
    # SetupAPI, not PowerShell: the tray watchdog reads these every 5 s
    import time, bt, hw
    t = time.perf_counter()
    hw.devices(); bt.radios()
    assert time.perf_counter() - t < 0.3


def test_battery_levels_read():
    import pnp
    levels = pnp.battery_levels()
    assert all(len(a) == 12 and 0 <= v <= 100 for a, v in levels.items())


def test_device_state_read_matches_the_list():
    # set_enabled polls pnp._status; read-only here: set_enabled itself is never called on real devices
    import pnp
    for r in pnp.list_devices():
        state = pnp._status(r["id"])
        assert state is not None, r["id"]
        assert pnp._reached(state, True) == (r["status"] == "OK")
        assert pnp._reached(state, False) == (r["problem"] == "CM_PROB_DISABLED")


def test_traffic_counters_grow_on_the_real_wifi_adapter():
    """Windows' byte counters for the Wi-Fi adapter(s) with their radio on go up between two reads (ordinary background traffic)."""
    import time
    on = {k: r["guid"] for k, r in wifi.radios().items() if r["on"]}
    assert on, "no Wi-Fi adapter with its radio on"
    for key, guid in on.items():
        first = traffic.counters(guid)
        grew, deadline = None, time.monotonic() + 15
        while time.monotonic() < deadline and not grew:
            time.sleep(0.5)
            now = traffic.counters(guid)
            grew = (now[0] - first[0], now[1] - first[1]) if now[0] > first[0] or now[1] > first[1] else None
        print(f"{key}: {first} -> {now}, grew by {grew} bytes (down, up)")  # shown with -s
        assert grew and grew[0] >= 0 and grew[1] >= 0, f"{key}: counters did not grow in 15 s"


def test_sampler_measures_a_real_rate(tmp_path):
    import time
    s = traffic.Sampler(tmp_path / "traffic.json")  # never started or saved: two ticks by hand
    s.tick()
    time.sleep(1.2)
    s.tick()
    using = [k for k, on in s.radios().items() if on]
    assert using and all(s.rate(k) is not None and s.rate(k)[0] >= 0 for k in using)
