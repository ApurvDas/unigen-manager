import json
import winreg

import pytest

import sysproxy

PAC, WCM = sysproxy.PAC, sysproxy.WCM
URL = "http://127.0.0.1:18780/proxy.pac"


class FakeReg:
    """Dict-backed stand-in for sysproxy.Reg: {(hive, path, name): (value, kind)}."""

    def __init__(self, **start):
        self.d = {}
        self.calls = []
        self.deny = set()  # triples whose put/delete raise PermissionError, like HKLM without admin
        for k, v in start.items():
            self.d[{"pac": PAC, "wcm": WCM}[k]] = v

    def get(self, hive, path, name):
        self.calls.append("get")
        v = self.d.get((hive, path, name))
        return None if v is None else v[0]

    def put(self, hive, path, name, value, kind):
        self.calls.append("put")
        if (hive, path, name) in self.deny:
            raise PermissionError(5, "Access is denied")
        self.d[(hive, path, name)] = (value, kind)

    def delete(self, hive, path, name):
        self.calls.append("delete")
        if (hive, path, name) in self.deny:
            raise PermissionError(5, "Access is denied")
        self.d.pop((hive, path, name), None)


@pytest.fixture(autouse=True)
def refreshed(monkeypatch):
    n = []
    monkeypatch.setattr(sysproxy, "_refresh", lambda: n.append(1))
    return n


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_apply_then_restore_absent_values(tmp_path, refreshed):
    s, reg = tmp_path / "settings.json", FakeReg()
    sysproxy.apply(URL, s, reg)
    assert reg.d[PAC] == (URL, winreg.REG_SZ)
    assert reg.d[WCM] == (0, winreg.REG_DWORD)
    assert read(s)["merge_saved"] == {"pac": None, "wcm": None}
    assert sysproxy.restore(s, reg) is True
    assert reg.d == {}
    assert "merge_saved" not in read(s)
    assert len(refreshed) == 2


def test_restore_puts_back_old_pac(tmp_path):
    s = tmp_path / "settings.json"
    reg = FakeReg(pac=("http://corp/pac", winreg.REG_SZ), wcm=(1, winreg.REG_DWORD))
    sysproxy.apply(URL, s, reg)
    assert reg.d[PAC][0] == URL
    sysproxy.restore(s, reg)
    assert reg.d[PAC] == ("http://corp/pac", winreg.REG_SZ)
    assert reg.d[WCM] == (1, winreg.REG_DWORD)


def test_apply_twice_keeps_first_saved(tmp_path):
    s = tmp_path / "settings.json"
    reg = FakeReg(pac=("http://corp/pac", winreg.REG_SZ))
    sysproxy.apply(URL, s, reg)
    sysproxy.apply("http://127.0.0.1:50000/proxy.pac", s, reg)
    assert read(s)["merge_saved"] == {"pac": "http://corp/pac", "wcm": None}
    assert reg.d[PAC][0] == "http://127.0.0.1:50000/proxy.pac"
    sysproxy.restore(s, reg)
    assert reg.d[PAC][0] == "http://corp/pac" and WCM not in reg.d


def test_restore_leftover_after_crash(tmp_path, refreshed):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"merge_saved": {"pac": "http://corp/pac", "wcm": None}}), encoding="utf-8")
    reg = FakeReg(pac=(URL, winreg.REG_SZ), wcm=(0, winreg.REG_DWORD))
    assert sysproxy.restore(s, reg) is True
    assert reg.d == {PAC: ("http://corp/pac", winreg.REG_SZ)}
    assert "merge_saved" not in read(s)


def test_restore_without_record_touches_nothing(tmp_path, refreshed):
    s = tmp_path / "settings.json"
    reg = FakeReg(pac=(URL, winreg.REG_SZ))
    assert sysproxy.restore(s, reg) is False  # no file at all
    s.write_text("not json", encoding="utf-8")
    assert sysproxy.restore(s, reg) is False  # broken file
    s.write_text(json.dumps({"wifi": "x"}), encoding="utf-8")
    assert sysproxy.restore(s, reg) is False
    assert reg.calls == [] and reg.d == {PAC: (URL, winreg.REG_SZ)}
    assert refreshed == []


def test_other_settings_kept(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"wifi": "Home", "traffic_unit": "MB"}), encoding="utf-8")
    reg = FakeReg()
    sysproxy.apply(URL, s, reg)
    assert read(s)["wifi"] == "Home" and read(s)["traffic_unit"] == "MB"
    sysproxy.restore(s, reg)
    assert read(s) == {"wifi": "Home", "traffic_unit": "MB"}


def test_record_written_before_registry(tmp_path):
    """A crash between the two writes must still leave a record to restore from."""
    s = tmp_path / "settings.json"

    class Boom(FakeReg):
        def put(self, *a):
            assert read(s)["merge_saved"] == {"pac": None, "wcm": None}
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        sysproxy.apply(URL, s, Boom())


def test_paths_and_refresh_options(monkeypatch):
    assert PAC == (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", "AutoConfigURL")
    assert WCM == (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WcmSvc\GroupPolicy", "fMinimizeConnections")
    calls = []

    class Fn:
        def __call__(self, *a):
            calls.append(a)

    class W:
        InternetSetOptionW = Fn()

    monkeypatch.undo()  # drop the autouse stub so the real _refresh runs
    import ctypes
    monkeypatch.setattr(ctypes, "windll", type("D", (), {"wininet": W()})(), raising=False)
    sysproxy._refresh()
    assert calls == [(None, 39, None, 0), (None, 37, None, 0)]


def test_restore_without_admin_keeps_policy_for_later(tmp_path, refreshed):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"wifi": "Home", "merge_saved": {"pac": "http://corp/pac", "wcm": 1}}), encoding="utf-8")
    reg = FakeReg(pac=(URL, winreg.REG_SZ), wcm=(0, winreg.REG_DWORD))
    reg.deny.add(WCM)
    assert sysproxy.restore(s, reg) is True
    assert reg.d[PAC] == ("http://corp/pac", winreg.REG_SZ)
    assert reg.d[WCM] == (0, winreg.REG_DWORD)
    assert read(s) == {"wifi": "Home", "merge_saved": {"wcm": 1}}
    assert len(refreshed) == 1
    reg.deny.clear()  # next start, elevated: the leftover item is retried and the record goes
    assert sysproxy.restore(s, reg) is True
    assert reg.d[WCM] == (1, winreg.REG_DWORD)
    assert read(s) == {"wifi": "Home"}


def test_restore_skips_values_already_right(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"merge_saved": {"pac": "http://corp/pac", "wcm": None}}), encoding="utf-8")
    reg = FakeReg(pac=("http://corp/pac", winreg.REG_SZ))
    assert sysproxy.restore(s, reg) is True
    assert "put" not in reg.calls and "delete" not in reg.calls
    assert "merge_saved" not in read(s)


def test_apply_after_partial_restore_resaves_missing_original(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"merge_saved": {"wcm": 1}}), encoding="utf-8")
    reg = FakeReg(pac=("http://corp/pac", winreg.REG_SZ), wcm=(0, winreg.REG_DWORD))
    sysproxy.apply(URL, s, reg)
    assert read(s)["merge_saved"] == {"wcm": 1, "pac": "http://corp/pac"}


def test_keeping_connected_is_true_only_for_policy_zero():
    for start, want in (({}, False), ({"wcm": (0, winreg.REG_DWORD)}, True), ({"wcm": (1, winreg.REG_DWORD)}, False)):
        assert sysproxy.keeping_connected(FakeReg(**start)) is want
