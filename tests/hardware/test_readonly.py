"""Read-only checks against this PC's real adapters. Run: py -3.10 -m pytest -m hardware"""
import os
from pathlib import Path

import pytest

import api, bt, speed, wifi

pytestmark = pytest.mark.hardware


def by_key():
    return {wifi.adapter_key(i["description"]): i for i in wifi.interfaces()}


def test_both_wifi_adapters_present():
    assert {"unigen", "builtin"} <= set(by_key())


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


def test_bluetooth_radios_and_versions():
    rs = {r["key"]: r for r in bt.radios()}
    assert rs["unigen"]["version"] == "5.4" and rs["builtin"]["version"] == "5.2"
    assert any(r["ok"] for r in rs.values())


def test_paired_devices_list():
    devs = bt.devices(paired=True)
    assert all(set(d) == {"id", "name", "connected", "kind", "address"} for d in devs)


def test_ping_router_from_connected_adapter():
    i = next((i for i in by_key().values() if i["state"] == "connected"), None)
    if i is None:
        pytest.skip("no adapter is connected")
    a = speed.addresses(i["name"])
    assert speed.ping(a["ip"], a["gateway"], count=3) >= 0


def test_api_end_to_end_reads():
    a = api.Api()
    for name, args in [("app_info", ()), ("adapters", ()), ("saved", ()), ("bt_radio", ()), ("networks", ("unigen",))]:
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
