import pathlib, xml.etree.ElementTree as ET
import pytest
from tests.conftest import fixture
import wifi
from winrun import CmdError

NS = {"w": "http://www.microsoft.com/networking/WLAN/profile/v1"}


class FakeNetsh:
    """Records every argv; answers 'show interfaces' from a queue of texts."""
    def __init__(self, iface_texts=()):
        self.calls, self.iface_texts, self.files_seen = [], list(iface_texts), []

    def __call__(self, args, **kw):
        self.calls.append(args)
        if args[:4] == ["netsh", "wlan", "show", "interfaces"]:
            return self.iface_texts.pop(0) if len(self.iface_texts) > 1 else self.iface_texts[0]
        for a in args:
            if a.startswith("filename="):
                p = pathlib.Path(a[len("filename="):])
                self.files_seen.append((p, p.exists(), p.read_text(encoding="utf-8") if p.exists() else None))
        return ""


def connected_text(ssid):
    return fixture("interfaces.txt").replace("State                  : disconnected", f"State                  : connected\n    SSID                   : {ssid}")


def test_adapter_keys():
    assert wifi.adapter_key("AIC8800D80 USB WiFi") == "unigen"
    assert wifi.adapter_key("MediaTek Wi-Fi 6 MT7921 Wireless LAN Card") == "builtin"
    assert wifi.adapter_key("Intel Wi-Fi 6 AX201") == "Intel Wi-Fi 6 AX201"


def test_security_kinds():
    assert wifi.security_kind("WPA2-Personal") == "wpa2"
    assert wifi.security_kind("Open") == "open"
    assert wifi.security_kind("WPA3-Personal") is None and wifi.security_kind("WPA2-Enterprise") is None


@pytest.mark.parametrize("pw, ok", [("short", False), ("12345678", True), ("x" * 63, True), ("x" * 64, False),
                                    ("A" * 64, True), ("ünïcödé-pass", False)])
def test_password_rules(pw, ok):
    if ok:
        wifi.check_password(pw)
    else:
        with pytest.raises(wifi.WifiError, match="8 to 63 characters"):
            wifi.check_password(pw)


def test_profile_xml_escapes_and_hex():
    ssid = 'Cafe & "Bar" <5G>'
    xml = wifi.profile_xml(ssid, "wpa2", 'p<a>&ss"word', wifi.profile_name(ssid))
    root = ET.fromstring(xml)  # must be well-formed
    assert root.find("w:SSIDConfig/w:SSID/w:hex", NS).text == ssid.encode("utf-8").hex().upper()
    assert root.find("w:SSIDConfig/w:SSID/w:name", NS).text == ssid
    assert root.find("w:MSM/w:security/w:sharedKey/w:keyMaterial", NS).text == 'p<a>&ss"word'
    assert root.find("w:MSM/w:security/w:authEncryption/w:authentication", NS).text == "WPA2PSK"


def test_open_profile_has_no_key():
    root = ET.fromstring(wifi.profile_xml("Guest", "open", None, "Guest"))
    assert root.find("w:MSM/w:security/w:sharedKey", NS) is None
    assert root.find("w:MSM/w:security/w:authEncryption/w:encryption", NS).text == "none"


def test_profile_name_has_no_quotes():
    assert '"' not in wifi.profile_name('say "hi"')
    assert wifi.profile_name("HOME-5G") == "HOME-5G"


def test_connect_new_network_writes_temp_profile_then_deletes_it(monkeypatch):
    fake = FakeNetsh([connected_text("Maple House")])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.connect("Wi-Fi 2", "Maple House", auth="WPA2-Personal", password="12345678", sleep=lambda s: None)
    add = next(c for c in fake.calls if c[2] == "add")
    assert add[:4] == ["netsh", "wlan", "add", "profile"] and "interface=Wi-Fi 2" in add and "user=all" in add
    path, existed, text = fake.files_seen[0]
    assert existed and "12345678" in text
    assert not path.exists() and not path.parent.exists()  # password file gone
    assert ["netsh", "wlan", "connect", "name=Maple House", "interface=Wi-Fi 2"] in fake.calls


def test_connect_saved_network_skips_profile(monkeypatch):
    fake = FakeNetsh([connected_text("HOME-5G")])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.connect("Wi-Fi 2", "HOME-5G", saved=True, sleep=lambda s: None)
    assert not any(c[2] == "add" for c in fake.calls)


def test_connect_wrong_password_deletes_profile(monkeypatch):
    fake = FakeNetsh([fixture("interfaces.txt")])  # never connects
    monkeypatch.setattr(wifi, "_run", fake)
    t = iter(range(0, 100))
    with pytest.raises(wifi.WifiError, match="Couldn't connect to Maple House. Check the password."):
        wifi.connect("Wi-Fi 2", "Maple House", auth="WPA2-Personal", password="wrongpass",
                     timeout=15, clock=lambda: next(t), sleep=lambda s: None)
    assert ["netsh", "wlan", "delete", "profile", "name=Maple House", "interface=Wi-Fi 2"] in fake.calls


def test_connect_rejects_unsupported_security_before_running_anything(monkeypatch):
    fake = FakeNetsh([fixture("interfaces.txt")])
    monkeypatch.setattr(wifi, "_run", fake)
    with pytest.raises(wifi.WifiError, match="WPA3-Personal.*Windows settings"):
        wifi.connect("Wi-Fi 2", "Lab", auth="WPA3-Personal", password="12345678")
    assert fake.calls == []


def test_hostile_ssid_stays_one_argument(monkeypatch):
    fake = FakeNetsh([connected_text('x" & del C:\\ "')])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.connect("Wi-Fi 2", 'x" & del C:\\ "', auth="Open", sleep=lambda s: None)
    connect = next(c for c in fake.calls if c[2] == "connect")
    assert connect[3] == "name=" + wifi.profile_name('x" & del C:\\ "') and len(connect) == 5


def test_disconnect_password_delete_copy(monkeypatch):
    fake = FakeNetsh(["x"])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.disconnect("Wi-Fi 2")
    assert fake.calls[-1] == ["netsh", "wlan", "disconnect", "interface=Wi-Fi 2"]
    monkeypatch.setattr(wifi, "_run", lambda a, **k: fixture("profile_key.txt"))
    assert wifi.password("Wi-Fi 2", "HOME-5G") == "REDACTED-PASS"
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.delete_profile("oldrouter", ["Wi-Fi", "Wi-Fi 2"])
    assert fake.calls[-2:] == [["netsh", "wlan", "delete", "profile", "name=oldrouter", "interface=Wi-Fi"],
                               ["netsh", "wlan", "delete", "profile", "name=oldrouter", "interface=Wi-Fi 2"]]


def test_copy_profile_exports_to_temp_and_imports(monkeypatch):
    calls = []
    def fake(args, **kw):
        calls.append(args)
        if args[2] == "export":
            folder = pathlib.Path(next(a for a in args if a.startswith("folder="))[7:])
            (folder / "Wi-Fi 2-Maple House.xml").write_text("<WLANProfile/>", encoding="utf-8")
        if args[2] == "add":
            p = pathlib.Path(next(a for a in args if a.startswith("filename="))[9:])
            assert p.exists()
            calls.append(("folder", p.parent))
        return ""
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.copy_profile("Maple House", "Wi-Fi 2", "Wi-Fi")
    assert calls[0][:4] == ["netsh", "wlan", "export", "profile"] and "key=clear" in calls[0]
    assert "interface=Wi-Fi" in calls[1]
    assert not calls[2][1].exists()  # exported file with the clear key is gone


def test_delete_ignores_adapter_without_profile(monkeypatch):
    def fake(args, **kw):
        if "interface=Wi-Fi" in args:
            raise CmdError('Profile "oldrouter" is not found on interface "Wi-Fi".')
        return ""
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.delete_profile("oldrouter", ["Wi-Fi", "Wi-Fi 2"])  # no exception


def test_hex_key_uses_network_key():
    def key_type(pw):
        root = ET.fromstring(wifi.profile_xml("Lab", "wpa2", pw, "Lab"))
        return root.find("w:MSM/w:security/w:sharedKey/w:keyType", NS).text
    assert key_type("A" * 64) == "networkKey"
    assert key_type("12345678") == "passPhrase"


def test_connect_error_after_add_deletes_profile(monkeypatch):
    calls = []
    def fake(args, **kw):
        calls.append(args)
        if args[2] == "connect":
            raise CmdError("The network is not available.")
        if args[2] == "delete":
            raise CmdError("delete failed too")  # must be swallowed
        return ""
    monkeypatch.setattr(wifi, "_run", fake)
    with pytest.raises(CmdError, match="not available"):
        wifi.connect("Wi-Fi 2", "Maple House", auth="WPA2-Personal", password="12345678", sleep=lambda s: None)
    assert ["netsh", "wlan", "delete", "profile", "name=Maple House", "interface=Wi-Fi 2"] in calls
