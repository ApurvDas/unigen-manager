import ctypes, json
import pytest
import bt
from winrun import CmdError

RADIOS_OK_UNIGEN = [
    {"id": "USB\\VID_368B&PID_8D81&MI_00\\6&28B24B5D&0&0000", "name": "Generic Bluetooth Adapter", "status": "OK", "problem": "CM_PROB_NONE", "lmp": 13},
    {"id": "USB\\VID_13D3&PID_3563&MI_00\\6&1D754FA2&0&0000", "name": "MediaTek Bluetooth Adapter", "status": "Error", "problem": "CM_PROB_DISABLED", "lmp": 11},
]


class FakePs:
    """Answers bt.ps1 actions; radio states follow a script of 'radios' answers."""
    def __init__(self, radio_states, answers=None):
        self.calls, self.states, self.answers = [], list(radio_states), answers or {}

    def __call__(self, script, params, **kw):
        assert "$p.action" in script  # the fixed bt.ps1 text, never built from inputs
        self.calls.append(params)
        a = params["action"]
        if a == "radios":
            return json.dumps(self.states.pop(0) if len(self.states) > 1 else self.states[0])
        return json.dumps(self.answers.get(a, {"ok": True}))


def flipped(unigen_ok, builtin_ok):
    a, b = (dict(r) for r in RADIOS_OK_UNIGEN)
    a["status"], a["problem"] = ("OK", "CM_PROB_NONE") if unigen_ok else ("Error", "CM_PROB_DISABLED")
    b["status"], b["problem"] = ("OK", "CM_PROB_NONE") if builtin_ok else ("Error", "CM_PROB_DISABLED")
    return [a, b]


def test_versions_and_kinds():
    assert bt.version(13) == "5.4" and bt.version(11) == "5.2" and bt.version(9) == "5.0" and bt.version(3) is None
    assert bt.kind(4, 5) == "Speaker" and bt.kind(4, 6) == "Headphones" and bt.kind(4, 0) == "Audio"
    assert bt.kind(5, 2) == "Controller" and bt.kind(2, 3) == "Phone" and bt.kind(0, 0) == "Device"


def test_radios_keys_and_state(monkeypatch):
    monkeypatch.setattr(bt, "_ps", FakePs([RADIOS_OK_UNIGEN]))
    uni, bi = bt.radios()
    assert (uni["key"], uni["ok"], uni["version"]) == ("unigen", True, "5.4")
    assert (bi["key"], bi["ok"], bi["disabled"], bi["version"]) == ("builtin", False, True, "5.2")


def test_switch_success_disables_current_then_enables_target(monkeypatch):
    fake = FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)])
    monkeypatch.setattr(bt, "_ps", fake)
    assert bt.switch("builtin", sleep=lambda s: None) == "builtin"
    acts = [(c["action"], c.get("id", "")[:21]) for c in fake.calls if c["action"] != "radios"]
    assert acts == [("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563")]


def test_switch_rolls_back_when_target_never_starts(monkeypatch):
    fake = FakePs([RADIOS_OK_UNIGEN, flipped(False, False)])
    monkeypatch.setattr(bt, "_ps", fake)
    t = iter(range(100))
    with pytest.raises(bt.BtError, match="Built-in MediaTek radio didn't start. Switched back to the Unigen dongle."):
        bt.switch("builtin", wait=10, clock=lambda: next(t), sleep=lambda s: None)
    acts = [(c["action"], c["id"][:21]) for c in fake.calls if c["action"] != "radios"]
    assert acts == [("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563"),
                    ("disable", "USB\\VID_13D3&PID_3563"), ("enable", "USB\\VID_368B&PID_8D81")]


def test_switch_rolls_back_when_enable_raises(monkeypatch):
    fake = FakePs([RADIOS_OK_UNIGEN])
    real = fake.__call__

    def flaky(script, params, **kw):
        if params["action"] == "enable" and "13D3" in params["id"]:
            fake.calls.append(params)
            raise CmdError("enable failed")
        return real(script, params, **kw)

    monkeypatch.setattr(bt, "_ps", flaky)
    with pytest.raises(bt.BtError, match="Switched back to the Unigen dongle"):
        bt.switch("builtin", sleep=lambda s: None)
    acts = [(c["action"], c["id"][:21]) for c in fake.calls if c["action"] != "radios"]
    assert acts[-1] == ("enable", "USB\\VID_368B&PID_8D81")


def test_service_changed():
    assert bt._service_changed(0) is True and bt._service_changed(1060) is False
    with pytest.raises(bt.BtError, match="refused"):
        bt._service_changed(87)


def test_switch_to_missing_radio(monkeypatch):
    monkeypatch.setattr(bt, "_ps", FakePs([RADIOS_OK_UNIGEN[:1]]))
    with pytest.raises(bt.BtError, match="isn't connected to this PC"):
        bt.switch("builtin")


def test_devices_map_kind_and_keep_ids_as_params(monkeypatch):
    devs = [{"id": "Bluetooth#Bluetooth02:00:00:00:00:10-11:22:33:44:55:66", "name": "JBL Go 3", "connected": False, "major": 4, "minor": 5, "address": "112233445566"}]
    fake = FakePs([RADIOS_OK_UNIGEN], {"paired": devs})
    monkeypatch.setattr(bt, "_ps", fake)
    assert bt.devices(paired=True) == [{"id": devs[0]["id"], "name": "JBL Go 3", "connected": False, "kind": "Speaker", "address": "112233445566"}]
    assert fake.calls[-1] == {"action": "paired"}


@pytest.mark.parametrize("status, ok", [("Paired", True), ("AlreadyPaired", True), ("AuthenticationTimeout", False), ("Failed", False)])
def test_pair_statuses(monkeypatch, status, ok):
    fake = FakePs([RADIOS_OK_UNIGEN], {"pair": {"status": status}})
    monkeypatch.setattr(bt, "_ps", fake)
    if ok:
        bt.pair('Bluetooth#x"; rm -rf')
        assert fake.calls[-1] == {"action": "pair", "id": 'Bluetooth#x"; rm -rf'}
    else:
        with pytest.raises(bt.BtError):
            bt.pair("Bluetooth#x")


def test_remove(monkeypatch):
    monkeypatch.setattr(bt, "_ps", FakePs([RADIOS_OK_UNIGEN], {"unpair": {"status": "Unpaired"}}))
    bt.remove("Bluetooth#x")


def test_device_info_struct_size():
    assert ctypes.sizeof(bt.BLUETOOTH_DEVICE_INFO) == 560


def test_connect_falls_back_to_settings(monkeypatch):
    opened = []
    def boom(address, flags):
        raise bt.BtError("rc 87")
    monkeypatch.setattr(bt, "_set_audio", boom)
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", True)
    with pytest.raises(bt.BtError, match="Bluetooth settings are open"):
        bt.connect("112233445566", "JBL Go 3", open_settings=opened.append)
    assert opened == ["ms-settings:bluetooth"]


def test_connect_uses_service_toggle(monkeypatch):
    seen = []
    monkeypatch.setattr(bt, "_set_audio", lambda address, flags: seen.append((address, flags)))
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", True)
    bt.connect("112233445566", "JBL Go 3", open_settings=lambda u: pytest.fail("should not open settings"))
    bt.disconnect("112233445566", "JBL Go 3", open_settings=lambda u: pytest.fail("should not open settings"))
    assert seen == [("112233445566", [0, 1]), ("112233445566", [0])]


def test_connect_disabled_by_spike(monkeypatch):
    opened = []
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", False)
    with pytest.raises(bt.BtError, match="Bluetooth settings are open"):
        bt.disconnect("112233445566", "JBL Go 3", open_settings=opened.append)
    assert opened == ["ms-settings:bluetooth"]


def test_failed_connect_turns_services_back_on():
    calls = []
    def set_state(g, flag):
        calls.append((g, flag))
        return 87 if (g, flag) == (bt.AUDIO_SERVICES[0], 1) else 0  # disable works, re-enable of the first service is refused
    with pytest.raises(bt.BtError, match="refused"):
        bt._apply_services(set_state, [0, 1])
    assert calls[:3] == [(bt.AUDIO_SERVICES[0], 0), (bt.AUDIO_SERVICES[1], 0), (bt.AUDIO_SERVICES[0], 1)]
    assert calls[3:] == [(g, 1) for g in bt.AUDIO_SERVICES]  # best-effort restore of every service


def test_failed_disconnect_and_nothing_to_switch_do_not_enable_anything():
    calls = []
    def refuse(g, flag):
        calls.append(flag)
        return 87
    with pytest.raises(bt.BtError):
        bt._apply_services(refuse, [0])
    with pytest.raises(bt.BtError, match="no audio connection"):
        bt._apply_services(lambda g, flag: 1060, [0, 1])
    assert calls == [0]
    bt._apply_services(lambda g, flag: 0, [0, 1])  # the happy path still passes


def test_toggle_failure_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(bt, "_set_audio", lambda a, f: (_ for _ in ()).throw(bt.BtError("rc 87")))
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", True)
    with pytest.raises(bt.BtError):
        bt.connect("112233445566", "JBL Go 3", open_settings=lambda u: None)
    assert "audio toggle failed: BtError: rc 87" in caplog.text


def test_second_concurrent_switch_is_refused(monkeypatch):
    monkeypatch.setattr(bt, "_ps", FakePs([RADIOS_OK_UNIGEN]))
    assert bt._switch_lock.acquire(blocking=False)
    try:
        with pytest.raises(bt.BtError, match="A radio switch is already running."):
            bt.switch("builtin")
    finally:
        bt._switch_lock.release()
    with pytest.raises(bt.BtError, match="isn't connected"):  # and the lock is free again afterwards
        bt.switch("nothing")
