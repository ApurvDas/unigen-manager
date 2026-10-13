import json

import pytest

import hw, winrun

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


def fake_ps(rows):
    def ps(script, params=None, *, timeout=60):
        return json.dumps(rows if params["action"] == "devices" else {"ok": True})
    return ps


def test_device_key_maps_known_ids():
    assert hw.device_key(UNI_WIFI, "x") == ("unigen", "wifi")
    assert hw.device_key(UNI_BT, "x") == ("unigen", "bt")
    assert hw.device_key(MT_WIFI, "x") == ("builtin", "wifi")
    assert hw.device_key(r"PCI\VEN_0000&DEV_0000", "MediaTek Wi-Fi 6 MT7921") == ("builtin", "wifi")
    assert hw.device_key(MT_BT, "x") == ("builtin", "bt")
    assert hw.device_key(ETH, "PCIe Gigabit Ethernet Controller") == (None, None)


def test_devices_groups_by_adapter(monkeypatch):
    monkeypatch.setattr(hw, "_ps", fake_ps(ALL))
    d = hw.devices()
    assert set(d) == {"unigen", "builtin"}
    assert d["unigen"] == {"present": True, "wifi": {"id": UNI_WIFI, "ok": True, "disabled": False},
                           "bt": {"id": UNI_BT, "ok": True, "disabled": False}}
    assert d["builtin"]["wifi"]["ok"] is True
    assert d["builtin"]["bt"] == {"id": MT_BT, "ok": False, "disabled": True}


def test_devices_without_dongle(monkeypatch):
    monkeypatch.setattr(hw, "_ps", fake_ps(ALL[2:]))
    assert "unigen" not in hw.devices()


def test_devices_single_object_from_powershell(monkeypatch):
    monkeypatch.setattr(hw, "_ps", lambda *a, **k: json.dumps(ALL[2]))  # ConvertTo-Json of one item, if not wrapped
    assert hw.devices()["builtin"]["bt"] is None


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


def test_enable_disable_pass_id_as_param(monkeypatch):
    seen = []
    monkeypatch.setattr(hw, "_ps", lambda script, params=None, *, timeout=60: seen.append((script, params)) or '{"ok":true}')
    hw.enable(UNI_WIFI)
    hw.disable(MT_WIFI)
    assert [p for _, p in seen] == [{"action": "enable", "id": UNI_WIFI}, {"action": "disable", "id": MT_WIFI}]
    assert all(UNI_WIFI not in s and MT_WIFI not in s for s, _ in seen)
