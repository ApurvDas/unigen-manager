import ctypes
import pytest
import bt
import btwinrt
from winrun import CmdError

RADIOS_OK_UNIGEN = [
    {"id": "USB\\VID_368B&PID_8D81&MI_00\\6&28B24B5D&0&0000", "name": "Generic Bluetooth Adapter", "status": "OK", "problem": "CM_PROB_NONE", "lmp": 13},
    {"id": "USB\\VID_13D3&PID_3563&MI_00\\6&1D754FA2&0&0000", "name": "MediaTek Bluetooth Adapter", "status": "Error", "problem": "CM_PROB_DISABLED", "lmp": 11},
]


class FakePs:
    """Replaces bt._set (enable/disable, recorded as (action, id, wait)) and bt._radio_rows (a script of radio lists)."""
    def __init__(self, radio_states):
        self.calls, self.states = [], list(radio_states)

    def rows(self):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def set(self, dev_id, on, wait=30.0):
        self.calls.append(("enable" if on else "disable", dev_id, wait))


def use_fake(monkeypatch, fake):
    monkeypatch.setattr(bt, "_set", fake.set)
    monkeypatch.setattr(bt, "_radio_rows", fake.rows)
    return fake


def flipped(unigen_ok, builtin_ok):
    a, b = (dict(r) for r in RADIOS_OK_UNIGEN)
    a["status"], a["problem"] = ("OK", "CM_PROB_NONE") if unigen_ok else ("Error", "CM_PROB_DISABLED")
    b["status"], b["problem"] = ("OK", "CM_PROB_NONE") if builtin_ok else ("Error", "CM_PROB_DISABLED")
    return [a, b]


def test_versions_and_kinds():
    assert bt.version(13) == "5.4" and bt.version(11) == "5.2" and bt.version(9) == "5.0" and bt.version(3) is None
    assert btwinrt.kind(4, 5) == "Speaker" and btwinrt.kind(4, 6) == "Headphones" and btwinrt.kind(4, 0) == "Audio"
    assert btwinrt.kind(5, 2) == "Controller" and btwinrt.kind(2, 3) == "Phone" and btwinrt.kind(0, 0) == "Device"


def test_radios_keys_and_state(monkeypatch):
    use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))
    uni, bi = bt.radios()
    assert (uni["key"], uni["ok"], uni["version"]) == ("unigen", True, "5.4")
    assert (bi["key"], bi["ok"], bi["disabled"], bi["version"]) == ("builtin", False, True, "5.2")


def test_switch_success_disables_current_then_enables_target(monkeypatch):
    fake = FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)])
    use_fake(monkeypatch, fake)
    assert bt.switch("builtin", sleep=lambda s: None) == "builtin"
    assert [(a, i[:21]) for a, i, w in fake.calls] == [("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563")]
    assert fake.calls[0][2] == 45  # a radio with paired devices takes a long while to switch off


def test_switch_rolls_back_when_target_never_starts(monkeypatch):
    fake = FakePs([RADIOS_OK_UNIGEN, flipped(False, False)])
    use_fake(monkeypatch, fake)
    t = iter(range(100))
    with pytest.raises(bt.BtError, match="Built-in MediaTek radio didn't start. Switched back to the Unigen dongle."):
        bt.switch("builtin", wait=10, clock=lambda: next(t), sleep=lambda s: None)
    assert [(a, i[:21]) for a, i, w in fake.calls] == [
        ("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563"),
        ("disable", "USB\\VID_13D3&PID_3563"), ("enable", "USB\\VID_368B&PID_8D81")]


def test_switch_waits_20_s_for_the_target_by_default(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False)]))
    now = [0.0]
    with pytest.raises(bt.BtError):
        bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert now[0] == 20


def test_switch_rolls_back_when_enable_raises(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))

    def flaky(dev_id, on, wait=30.0):
        fake.calls.append(("enable" if on else "disable", dev_id, wait))
        if on and "13D3" in dev_id:
            raise CmdError("enable failed")
    monkeypatch.setattr(bt, "_set", flaky)
    with pytest.raises(bt.BtError, match="Switched back to the Unigen dongle"):
        bt.switch("builtin", sleep=lambda s: None)
    assert [(a, i[:21]) for a, i, w in fake.calls][-1] == ("enable", "USB\\VID_368B&PID_8D81")


def test_switch_leaves_an_old_radio_that_wont_finish_turning_off_alone(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))

    def stuck(dev_id, on, wait=30.0):
        fake.calls.append(("enable" if on else "disable", dev_id, wait))
        if not on and "368B" in dev_id:
            raise CmdError("The device didn't turn off.")
    monkeypatch.setattr(bt, "_set", stuck)
    with pytest.raises(bt.StuckRadio, match="didn't finish turning off the Unigen dongle radio.*re-plug the dongle"):
        bt.switch("builtin", sleep=lambda s: None)
    assert [a for a, i, w in fake.calls] == ["disable"]  # no re-enable of a radio mid-teardown, target untouched


def test_service_changed():
    assert bt._service_changed(0) is True and bt._service_changed(1060) is False
    with pytest.raises(bt.BtError, match="refused"):
        bt._service_changed(87)


def test_switch_to_missing_radio(monkeypatch):
    use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN[:1]]))
    with pytest.raises(bt.BtError, match="isn't connected to this PC"):
        bt.switch("builtin")


def test_device_info_struct_size():
    assert ctypes.sizeof(bt.BLUETOOTH_DEVICE_INFO) == 560


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


def test_remove_unpairs_every_id(monkeypatch):
    done = []
    monkeypatch.setattr(bt.btwinrt, "unpair", done.append)
    bt.remove(["Bluetooth#c", "BluetoothLE#l"])
    assert done == ["Bluetooth#c", "BluetoothLE#l"]


def test_ks_match_by_path_or_parent():
    a2dp = r"\\?\bthenum#{0000110b-0000-1000-8000-00805f9b34fb}_vid&0001004c#8&1&0&020000000013_c00000000#{6994ad04}\src"
    hfp = r"\\?\bthhfenum#bthhfpaudio#9&2&0&97#{6994ad04}\wave"
    assert bt._ks_match(a2dp, "", "020000000013")
    assert bt._ks_match(hfp, r"BTHENUM\{0000111e-0000-1000-8000-00805f9b34fb}_VID&0001004c\8&1&0&020000000013_C00000000", "020000000013")
    assert not bt._ks_match(hfp, r"BTHENUM\{0000111e}\8&1&0&020000000099_C0", "020000000013")


def test_connect_tries_ks_then_services_then_settings(monkeypatch, caplog):
    order, opened = [], []
    def ks(addr, on): order.append(("ks", on)); raise bt.BtError("no filter")
    def svc(addr, flags): order.append(("svc", flags)); raise bt.BtError("refused")
    monkeypatch.setattr(bt, "_ks_oneshot", ks)
    monkeypatch.setattr(bt, "_set_audio", svc)
    with pytest.raises(bt.BtError, match="Bluetooth settings are open"):
        bt.connect("020000000013", "Test Speaker", open_settings=opened.append)
    assert order == [("ks", True), ("svc", [0, 1])] and opened == ["ms-settings:bluetooth"]
    assert "audio connect failed" in caplog.text


def test_connect_stops_at_first_method_that_works(monkeypatch):
    order = []
    monkeypatch.setattr(bt, "_ks_oneshot", lambda addr, on: order.append(("ks", on)))
    monkeypatch.setattr(bt, "_set_audio", lambda addr, flags: order.append("svc"))
    bt.disconnect("020000000013", "Test Speaker", open_settings=None)
    assert order == [("ks", False)]


def test_connect_without_settings_fallback_just_raises(monkeypatch):
    monkeypatch.setattr(bt, "_ks_oneshot", lambda a, on: (_ for _ in ()).throw(bt.BtError("x")))
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", False)
    with pytest.raises(bt.BtError, match="Windows didn't let the app connect Test Speaker."):
        bt.connect("020000000013", "Test Speaker", open_settings=None)


def test_second_concurrent_switch_is_refused(monkeypatch):
    use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))
    assert bt._switch_lock.acquire(blocking=False)
    try:
        with pytest.raises(bt.BtError, match="A radio switch is already running."):
            bt.switch("builtin")
    finally:
        bt._switch_lock.release()
    with pytest.raises(bt.BtError, match="isn't connected"):  # and the lock is free again afterwards
        bt.switch("nothing")


def test_devices_add_battery_only_while_connected(monkeypatch):
    rows = [{"id": "C", "ids": ["C"], "name": "Test Speaker", "kind": "Speaker", "connected": True, "address": "020000000013"},
            {"id": "D", "ids": ["D"], "name": "Test Buds", "kind": "Headphones", "connected": False, "address": "020000000014"},
            {"id": "E", "ids": ["E"], "name": "Test Mouse", "kind": "Mouse", "connected": True, "address": "020000000015"}]
    monkeypatch.setattr(bt.btwinrt, "paired", lambda: [dict(r) for r in rows])
    monkeypatch.setattr(bt.pnp, "battery_levels", lambda: {"020000000013": 90, "020000000014": 40})
    assert [d["battery"] for d in bt.devices()] == [90, None, None]  # disconnected: Windows' value is stale


def test_devices_survive_battery_read_failure(monkeypatch):
    monkeypatch.setattr(bt.btwinrt, "paired", lambda: [{"id": "C", "ids": ["C"], "name": "S", "kind": "Speaker",
                                                       "connected": True, "address": "020000000013"}])
    def boom(): raise OSError("setupapi")
    monkeypatch.setattr(bt.pnp, "battery_levels", boom)
    assert bt.devices()[0]["battery"] is None
