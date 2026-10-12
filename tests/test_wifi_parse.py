import pytest
from tests.conftest import fixture
import wifi


def test_interfaces_both_adapters():
    a, b = wifi.parse_interfaces(fixture("interfaces.txt"))
    assert a["name"] == "Wi-Fi" and "MT7921" in a["description"]
    assert a["state"] == "connected" and a["ssid"] == "HOME-5G"
    assert a["channel"] == 36 and a["rx"] == 866.7 and a["signal"] == 80 and a["radio"] == "802.11ac"
    assert a["guid"] == "11111111-2222-4333-8444-555555555551"
    assert b["name"] == "Wi-Fi 2" and b["description"] == "AIC8800D80 USB WiFi"
    assert b["state"] == "disconnected" and "ssid" not in b and "signal" not in b


def test_interfaces_none_present():
    assert wifi.parse_interfaces("There is no wireless interface on the system.\r\n") == []


def test_non_english_output_raises():
    german = "\n    Name                   : WLAN\n    Beschreibung           : AIC8800D80 USB WiFi\n    Status                 : Verbunden\n"
    with pytest.raises(wifi.ParseError, match="Is Windows set to English"):
        wifi.parse_interfaces(german)


def test_networks_bands_and_hidden():
    nets = {n["ssid"]: n for n in wifi.parse_networks(fixture("networks.txt"))}
    assert len(nets) == 8
    bina = nets["Maple House"]
    assert bina["auth"] == "WPA2-Personal"
    assert [(a["channel"], a["signal"], a["band"]) for a in bina["aps"]] == [(6, 100, 2.4), (1, 26, 2.4), (36, 24, 5)]
    assert nets["AirFiber-Cedar12"]["aps"][0] == {"bssid": "02:00:00:00:00:08", "signal": 8, "radio": "802.11ax", "channel": 157, "band": 5}
    assert nets["[Smart_Fridge]a1b2"]["aps"][0]["channel"] == 11
    assert nets[""]["auth"] == "Open"  # hidden network keeps an empty SSID


def test_profiles_per_interface():
    p = wifi.parse_profiles(fixture("profiles.txt"))
    assert p["Wi-Fi"] == ["HOME-5G", "phone_hotspot", "Cafe_wifi", "Guest_net 2", "Guest_net"]
    assert len(p["Wi-Fi 2"]) == 7 and "oldrouter" in p["Wi-Fi 2"]


def test_key_present_and_absent():
    assert wifi.parse_key(fixture("profile_key.txt")) == "REDACTED-PASS"
    assert wifi.parse_key("    Security key           : Absent\n") is None


def test_drivers_standard_and_wpa3():
    d = wifi.parse_drivers(fixture("drivers.txt"))
    assert wifi.wifi_standard(d["Wi-Fi 2"]["radio_types"]) == "Wi-Fi 6"
    assert d["Wi-Fi"]["wpa3"] is True and d["Wi-Fi 2"]["wpa3"] is False
    assert wifi.wifi_standard(["802.11n", "802.11ac"]) == "Wi-Fi 5"
    assert wifi.wifi_standard(["802.11g"]) is None


def test_band_boundaries():
    assert wifi.band(1) == 2.4 and wifi.band(14) == 2.4 and wifi.band(36) == 5 and wifi.band(165) == 5


def test_replacement_characters_do_not_crash():
    text = fixture("networks.txt").replace("Maple House", "Caf� ��")
    assert any(n["ssid"] == "Caf� ��" for n in wifi.parse_networks(text))
