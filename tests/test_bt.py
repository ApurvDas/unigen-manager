import ctypes
import os
import pytest
import bt
import btwinrt
from winrun import CmdError

REAL_VETO_PROBE = bt._veto_probe  # the autouse fixture below replaces it, so no test reads the real event log by accident

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

    def set(self, dev_id, on, wait=30.0, abort=None):
        self.calls.append(("enable" if on else "disable", dev_id, wait))


@pytest.fixture(autouse=True)
def radio_up(monkeypatch):
    monkeypatch.setattr(bt, "_radio_up", lambda: True)  # Windows has a working radio unless a test says otherwise
    monkeypatch.setattr(bt, "power", lambda: "on")  # and its radio object follows the device at once
    monkeypatch.setattr(bt, "_set_audio", lambda a, f: pytest.fail("the service toggle is only for audio devices and stragglers"))
    monkeypatch.setattr(bt, "_ks_filters", lambda a: [])  # no Bluetooth audio driver is loaded for anything (never ask the real PC)
    monkeypatch.setattr(bt, "_veto_probe", lambda instance_id: lambda since: False)  # never read the real event log
    monkeypatch.setattr(btwinrt, "paired", lambda: [])  # nothing is connected unless a test says so (never ask the real radio)


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


def test_switch_rolls_back_when_target_is_pnp_ok_but_windows_has_no_radio(monkeypatch):
    """A crashed dongle: Device Manager says OK, Windows finds no radio."""
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, True)]))
    monkeypatch.setattr(bt, "_radio_up", lambda: False)
    t = iter(range(100))
    with pytest.raises(bt.BtError, match="Built-in MediaTek radio didn't start. Switched back to the Unigen dongle."):
        bt.switch("builtin", wait=10, clock=lambda: next(t), sleep=lambda s: None)
    assert [(a, i[:21]) for a, i, w in fake.calls] == [
        ("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563"),
        ("disable", "USB\\VID_13D3&PID_3563"), ("enable", "USB\\VID_368B&PID_8D81")]


def test_switch_pnp_ok_target_without_a_radio_isnt_done_and_is_never_disabled(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([flipped(True, False)]))
    monkeypatch.setattr(bt, "_radio_up", lambda: False)
    t = iter(range(100))
    with pytest.raises(bt.BtError, match="Unigen dongle radio didn't start."):
        bt.switch("unigen", wait=10, clock=lambda: next(t), sleep=lambda s: None)
    assert [(a, i[:21]) for a, i, w in fake.calls] == [("enable", "USB\\VID_368B&PID_8D81")]  # disabling a crashed radio can hang


def test_switch_restarts_a_target_that_failed_to_start(monkeypatch):
    a, b = (dict(r) for r in RADIOS_OK_UNIGEN)
    b["problem"] = "10"  # started and failed while the dongle ran
    fake = use_fake(monkeypatch, FakePs([[a, b], flipped(False, True)]))
    assert bt.switch("builtin", sleep=lambda s: None) == "builtin"
    assert [(a, i[:21]) for a, i, w in fake.calls] == [("disable", "USB\\VID_368B&PID_8D81"), ("disable", "USB\\VID_13D3&PID_3563"), ("enable", "USB\\VID_13D3&PID_3563")]


def test_switch_never_restarts_a_stopped_target_without_a_problem(monkeypatch):
    a, b = (dict(r) for r in RADIOS_OK_UNIGEN)
    b["problem"] = "CM_PROB_NONE"  # status Error but no problem code: Windows is still stopping it
    fake = use_fake(monkeypatch, FakePs([[a, b], flipped(False, True)]))
    bt.switch("builtin", sleep=lambda s: None)
    assert [(a, i[:21]) for a, i, w in fake.calls] == [("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563")]


def test_switch_waits_20_s_for_the_target_by_default(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False)]))
    now = [0.0]
    with pytest.raises(bt.BtError):
        bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert now[0] == 20


def test_switch_rolls_back_when_enable_raises(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))

    def flaky(dev_id, on, wait=30.0, abort=None):
        fake.calls.append(("enable" if on else "disable", dev_id, wait))
        if on and "13D3" in dev_id:
            raise CmdError("enable failed")
    monkeypatch.setattr(bt, "_set", flaky)
    with pytest.raises(bt.BtError, match="Switched back to the Unigen dongle"):
        bt.switch("builtin", sleep=lambda s: None)
    assert [(a, i[:21]) for a, i, w in fake.calls][-1] == ("enable", "USB\\VID_368B&PID_8D81")


def test_switch_leaves_an_old_radio_that_wont_finish_turning_off_alone(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))

    def stuck(dev_id, on, wait=30.0, abort=None):
        fake.calls.append(("enable" if on else "disable", dev_id, wait))
        if not on and "368B" in dev_id:
            raise CmdError("The device didn't turn off.")
    monkeypatch.setattr(bt, "_set", stuck)
    with pytest.raises(bt.StuckRadio, match="didn't turn off the Unigen dongle radio.*audio.*disconnect your earbuds.*re-plug the dongle"):
        bt.switch("builtin", sleep=lambda s: None)
    assert [a for a, i, w in fake.calls] == ["disable"]  # no re-enable of a radio mid-teardown, target untouched


def buds(connected=True):
    return {"id": "x", "ids": ["x"], "name": "Buds", "kind": "Headphones", "connected": connected, "address": "AABBCCDDEEFF", "here": True}


def pad(connected=True):
    """A game controller: no audio, so it keeps the audio-driver disconnect path."""
    return dict(buds(connected), name="Pad", kind="Controller", address="AABBCCDDEE11")


def connected_world(monkeypatch, fake, still=0, device=buds):
    """`device` (the earbuds unless a test says otherwise) is connected on the old radio. `events` records
    disconnect / services / connect / radio calls in order; the device reads as connected for `still` more polls after
    it was asked to disconnect (by the audio driver or by the service toggle)."""
    events, left = [], [still]
    use_fake(monkeypatch, fake)
    monkeypatch.setattr(fake, "set", lambda dev_id, on, wait=30.0, abort=None: events.append(("enable" if on else "disable", dev_id[:21])))
    monkeypatch.setattr(bt, "_set", fake.set)

    def paired():
        if any(e[0] in ("disconnect", "services") for e in events):
            left[0] -= 1
            return [device(left[0] >= 0)]
        return [device()]
    monkeypatch.setattr(btwinrt, "paired", paired)
    monkeypatch.setattr(bt, "_set_audio", lambda a, f: events.append(("services", a, f)))
    monkeypatch.setattr(bt, "disconnect", lambda a, n, *, open_settings=os.startfile: events.append(("disconnect", a, open_settings)))
    monkeypatch.setattr(bt, "connect", lambda a, n, *, open_settings=os.startfile: events.append(("connect", a, open_settings)))
    return events


def test_switch_disconnects_connected_devices_before_turning_the_old_radio_off(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), still=1, device=pad)
    now = [0.0]
    assert bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)) == "builtin"
    assert events == [("disconnect", "AABBCCDDEE11", None), ("disable", "USB\\VID_368B&PID_8D81"),
                      ("enable", "USB\\VID_13D3&PID_3563"), ("connect", "AABBCCDDEE11", None)]  # Settings never opens
    assert now[0] < bt._DROP_WAIT + 3 * bt._SETTLE + 3  # it didn't wait out the full drop wait


def test_connected_audio_goes_straight_to_the_service_toggle_without_the_ks_wait(monkeypatch):
    """The old radio's turn-off took 42-51 s while the audio drivers were loaded, 10 s after they were unloaded."""
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    now = [0.0]
    assert bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)) == "builtin"
    assert events == [("services", "AABBCCDDEEFF", [0]), ("disable", "USB\\VID_368B&PID_8D81"),
                      ("enable", "USB\\VID_13D3&PID_3563"), ("connect", "AABBCCDDEEFF", None)]  # no disconnect (KS) call at all
    assert now[0] == bt._SETTLE + 1  # the settle, then one poll for the target: it didn't wait for the drop


def test_an_audio_device_that_wont_drop_after_the_toggle_is_waited_for_3_s_not_10(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), still=10**6)
    now = [0.0]
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert [e[0] for e in events] == ["services", "disable", "enable", "connect"]  # unloaded once, not asked again
    assert bt._AUDIO_DROP_WAIT <= now[0] < bt._DROP_WAIT


def test_a_device_with_a_loaded_audio_driver_counts_as_audio_whatever_its_kind(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]),
                             device=lambda c=True: dict(buds(c), kind="TV"))
    monkeypatch.setattr(bt, "_ks_filters", lambda a: ["\\\\?\\bth..."])
    bt.switch("builtin", sleep=lambda s: None)
    assert events[0] == ("services", "AABBCCDDEEFF", [0])


def test_audio_whose_service_toggle_fails_takes_the_ks_path(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    monkeypatch.setattr(bt, "_set_audio", lambda a, f: (_ for _ in ()).throw(bt.BtError("That device has no audio connection to switch.")))
    bt.switch("builtin", sleep=lambda s: None)
    assert [e[0] for e in events] == ["disconnect", "disable", "enable", "connect"]


def test_switch_gives_up_waiting_for_a_device_that_wont_disconnect(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), still=10**6, device=pad)
    now = [0.0]
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert [e[0] for e in events] == ["disconnect", "services", "disable", "enable", "connect"]
    assert events[1] == ("services", "AABBCCDDEE11", [0]) and now[0] >= bt._DROP_WAIT  # unloads its audio drivers so audiodg lets go


def test_service_toggle_is_up_front_for_audio_and_a_straggler_for_the_rest(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    reads = [0]

    def paired():  # Buds drop after the first read, the mouse never does
        reads[0] += 1
        return [dict(buds(), address="A1", connected=reads[0] < 2), dict(buds(), address="B2", name="Mouse", kind="Mouse")]
    monkeypatch.setattr(btwinrt, "paired", paired)
    toggled = []
    monkeypatch.setattr(bt, "_set_audio", lambda a, f: toggled.append((a, f)))
    now = [0.0]
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert toggled == [("A1", [0]), ("B2", [0])] and [e[0] for e in events].count("disconnect") == 1  # the mouse: KS first


def test_a_failing_service_toggle_doesnt_stop_the_switch(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), still=10**6, device=pad)
    monkeypatch.setattr(bt, "_set_audio", lambda a, f: (_ for _ in ()).throw(bt.BtError("Windows refused (error 87).")))
    now = [0.0]
    assert bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)) == "builtin"


def test_the_disconnect_is_logged_with_its_way_and_whether_the_device_dropped(monkeypatch, caplog):
    caplog.set_level("INFO", logger="unigen")
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), still=1, device=pad)
    bt.switch("builtin", sleep=lambda s: None)
    assert "disconnect Pad: asked through the audio driver (" in caplog.text and "Pad dropped after " in caplog.text
    caplog.clear()
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), still=10**6, device=pad)
    now = [0.0]
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert "Pad still connected after 10 s; unloading its audio services" in caplog.text and "Pad is still connected" in caplog.text
    caplog.clear()
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    now = [0.0]
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert "disconnect Buds: asked through the service toggle (0.0 s)" in caplog.text and "Buds dropped after 0.0 s" in caplog.text
    caplog.clear()
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), still=10**6)
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert "Buds still connected 3 s after its audio services were unloaded" in caplog.text


def test_switch_goes_on_when_a_disconnect_raises(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]), device=pad)

    def boom(a, n, *, open_settings=None):
        raise bt.BtError("Windows didn't let the app disconnect Buds.")
    monkeypatch.setattr(bt, "disconnect", boom)
    assert bt.switch("builtin", sleep=lambda s: None) == "builtin"
    assert [e[0] for e in events] == ["disable", "enable", "connect"]  # still tried to bring it back


def test_switch_goes_on_when_the_connected_list_cant_be_read(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    monkeypatch.setattr(btwinrt, "paired", lambda: (_ for _ in ()).throw(bt.BtError("Is Bluetooth on?")))
    assert bt.switch("builtin", sleep=lambda s: None) == "builtin"
    assert [a for a, i, w in fake.calls] == ["disable", "enable"]


def test_a_reconnect_that_fails_or_isnt_paired_here_doesnt_fail_the_switch(monkeypatch):
    for err in (bt.NotPairedHere("This Bluetooth radio doesn't know Buds."), bt.BtError("nope"), OSError("gone")):
        events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))

        def refuse(a, n, *, open_settings=None, err=err):
            raise err
        monkeypatch.setattr(bt, "connect", refuse)
        assert bt.switch("builtin", sleep=lambda s: None) == "builtin"


def test_no_reconnect_when_the_switch_fails(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False)]))
    t = iter(range(100))
    with pytest.raises(bt.BtError):
        bt.switch("builtin", wait=10, clock=lambda: next(t), sleep=lambda s: None)
    assert "connect" not in [e[0] for e in events]


def test_the_settle_is_one_second_and_only_when_something_was_taken_off(monkeypatch):
    sleeps = []
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    bt.switch("builtin", sleep=sleeps.append)
    assert sleeps == [1, 1] and bt._SETTLE == 1  # the settle, then one poll for the target
    sleeps.clear()
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    monkeypatch.setattr(btwinrt, "paired", lambda: [buds(connected=False)])
    bt.switch("builtin", sleep=sleeps.append)
    assert sleeps == [1]  # nothing connected: no settle


def test_devices_reconnect_with_no_pause_once_the_radio_is_ready(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, True)]))  # ready on the first look
    bt.switch("builtin", sleep=lambda s: events.append(("sleep", s)))
    assert events[-2][0] == "enable" and events[-1][0] == "connect"  # no sleep between the radio coming up and the reconnect


def test_no_connected_devices_means_no_disconnect_and_no_reconnect(monkeypatch):
    events = connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    monkeypatch.setattr(btwinrt, "paired", lambda: [buds(connected=False)])
    now = [0.0]
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert [e[0] for e in events] == ["disable", "enable"] and now[0] == 1  # one poll for the target, no settle


def test_switch_that_is_already_done_touches_no_device(monkeypatch):
    use_fake(monkeypatch, FakePs([flipped(True, False)]))
    monkeypatch.setattr(btwinrt, "paired", lambda: pytest.fail("nothing to switch"))
    assert bt.switch("unigen") == "unigen"


def test_service_changed():
    assert bt._service_changed(0) is True and bt._service_changed(1060) is False
    with pytest.raises(bt.BtError, match="refused"):
        bt._service_changed(87)
    with pytest.raises(bt.NotPairedHere):  # 1168 = ELEMENT_NOT_FOUND: the device isn't on this radio -> re-pair
        bt._service_changed(1168)


def test_ks_oneshot_with_no_filters_says_not_paired_here(monkeypatch):
    """No audio filters on this radio means the device is paired on the other one: re-pair, not a generic failure."""
    monkeypatch.setattr(bt, "_ks_filters", lambda a: [])
    with pytest.raises(bt.NotPairedHere, match="no Bluetooth audio driver on this radio"):
        bt._ks_oneshot("020000000013", True)


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


def test_connect_to_a_device_this_radio_doesnt_know_says_re_pair_not_settings(monkeypatch):
    """The app.log case: no audio driver on this radio, and Windows doesn't know the device: Settings can't help."""
    monkeypatch.setattr(bt, "_ks_oneshot", lambda a, on: (_ for _ in ()).throw(bt.BtError("no driver")))
    monkeypatch.setattr(bt, "_set_audio", lambda a, f: (_ for _ in ()).throw(bt.NotPairedHere("unknown")))
    opened = []
    with pytest.raises(bt.NotPairedHere, match="doesn't know Test Buds. Put it in pairing mode, then press Re-pair."):
        bt.connect("020000000011", "Test Buds", open_settings=opened.append)
    assert opened == []


def test_connect_without_a_working_radio_says_so_and_skips_settings(monkeypatch):
    monkeypatch.setattr(bt, "_radio_up", lambda: False)
    monkeypatch.setattr(bt, "_ks_oneshot", lambda a, on: pytest.fail("no radio, nothing to try"))
    opened = []
    with pytest.raises(bt.BtError, match="No Bluetooth radio is working, so Test Speaker can't connect."):
        bt.connect("020000000013", "Test Speaker", open_settings=opened.append)
    assert opened == []


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


# ---- steps, fail-fast veto, "done" waits for Windows' radio ----
def run_switch(monkeypatch, fake, **kw):
    steps = []
    now = [0.0]
    on_step = lambda text, step, of, label: steps.append((step, of, label, text))
    try:
        bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s), on_step=on_step, **kw)
    except bt.BtError as e:
        return steps, e
    return steps, None


def test_switch_reports_its_four_steps_in_order(monkeypatch):
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    steps, err = run_switch(monkeypatch, None)
    assert err is None and steps == [
        (1, 4, "Disconnecting your devices", "Disconnecting your devices…"),
        (2, 4, "Turning off the Unigen dongle radio", "Turning off the Unigen dongle radio…"),
        (3, 4, "Starting the Built-in MediaTek radio", "Starting the Built-in MediaTek radio…"),
        (4, 4, "Reconnecting your devices", "Reconnecting your devices…")]


def test_switch_skips_the_steps_that_have_nothing_to_do(monkeypatch):
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    monkeypatch.setattr(btwinrt, "paired", lambda: [buds(connected=False)])  # nothing connected: steps 1 and 4 never start
    steps, err = run_switch(monkeypatch, None)
    assert err is None and [s[0] for s in steps] == [2, 3]
    use_fake(monkeypatch, FakePs([flipped(False, False), flipped(False, True)]))  # no other radio is on: step 2 is skipped too
    steps, err = run_switch(monkeypatch, None)
    assert [s[0] for s in steps] == [3]


def test_a_failed_switch_has_reported_the_step_it_failed_at(monkeypatch):
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False)]))
    steps, err = run_switch(monkeypatch, fake, wait=3)
    assert isinstance(err, bt.BtError) and steps[-1][:3] == (3, 4, "Starting the Built-in MediaTek radio")  # rollback adds no step

    def stuck(dev_id, on, wait=30.0, abort=None):
        raise CmdError("The device didn't turn off.")
    fake = use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))
    monkeypatch.setattr(bt, "_set", stuck)
    steps, err = run_switch(monkeypatch, fake)
    assert isinstance(err, bt.StuckRadio) and steps[-1][:2] == (2, 4)


def test_switch_gives_the_old_radio_a_veto_probe_and_nothing_else_does(monkeypatch):
    seen = []
    use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    monkeypatch.setattr(bt, "_set", lambda dev_id, on, wait=30.0, abort=None: seen.append((dev_id[:21], on, wait, abort)))
    monkeypatch.setattr(bt, "_veto_probe", lambda instance_id: ("probe", instance_id))
    bt.switch("builtin", sleep=lambda s: None)
    off, on = seen
    assert off[:3] == (r"USB\VID_368B&PID_8D81", False, 45) and off[3] == ("probe", RADIOS_OK_UNIGEN[0]["id"])
    assert on[3] is None  # the target's enable has no abort


def test_a_veto_ends_the_wait_with_the_audio_message(monkeypatch):
    """Through the real pnp.set_enabled: the radio never turns off, Windows vetoes both calls, the probe sees it."""
    import pnp
    use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN]))
    now, calls = [0.0], []
    monkeypatch.setattr(pnp, "_status", lambda i: (pnp._DN_STARTED, 0))  # still running
    monkeypatch.setattr(pnp, "_change", lambda i, on: calls.append(on) or (_ for _ in ()).throw(CmdError("The data is invalid.")))
    vetoed = []
    monkeypatch.setattr(bt, "_veto_probe", lambda instance_id: lambda since: vetoed.append(since) or True)
    monkeypatch.setattr(bt, "_set", lambda i, on, wait=30.0, abort=None: pnp.set_enabled(
        i, on, wait, abort=abort, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0], wall=lambda: now[0]))
    with pytest.raises(bt.StuckRadio, match="audio is still playing"):
        bt.switch("builtin", sleep=lambda s: None)
    assert calls == [False, False] and now[0] == 3.0 and len(vetoed) == 1  # two calls, no extra, gave up at once; 45 s not waited


EVENT = r"""<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>
<Provider Name='Microsoft-Windows-Kernel-PnP'/><EventID>225</EventID>
<TimeCreated SystemTime='{when}'/></System><EventData>
<Data Name='ImageName'>\Device\HarddiskVolume3\Windows\System32\audiodg.exe</Data>
<Data Name='DeviceInstanceId'>{dev}</Data></EventData></Event>"""
OLD_RADIO = RADIOS_OK_UNIGEN[0]["id"]
OTHER_RADIO = RADIOS_OK_UNIGEN[1]["id"]
T0 = 1_760_000_000.0  # 2025-10-09 08:53:20 UTC


def stamp(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.1234567Z")


def probe_world(events, **kw):
    ran = []
    xml = "".join(EVENT.replace("{when}", stamp(t)).replace("{dev}", d.replace("&", "&amp;")) for t, d in events)

    def run(args, *, timeout):
        ran.append(args)
        return xml
    return ran, REAL_VETO_PROBE(OLD_RADIO, run=run, **kw)


def test_veto_probe_counts_only_a_225_for_this_radio_since_the_call_began():
    ran, probe = probe_world([(T0 - 50, OLD_RADIO), (T0 + 8, OTHER_RADIO)])
    assert probe(T0) is False  # an older veto and one for another device
    assert ran == [["wevtutil", "qe", "System", "/q:*[System[(EventID=225)]]", "/rd:true", "/c:5", "/f:xml"]]  # read-only, nothing else
    _, probe = probe_world([(T0 + 8, OLD_RADIO)])
    assert probe(T0) is True
    _, probe = probe_world([(T0 + 8, OLD_RADIO.lower())])  # case doesn't matter
    assert probe(T0) is True


def test_veto_probe_looks_at_most_every_two_seconds():
    now = [0.0]
    ran, probe = probe_world([(T0 - 50, OLD_RADIO)], clock=lambda: now[0])
    probe(T0), probe(T0)
    now[0] = 1.9
    probe(T0)
    assert len(ran) == 1
    now[0] = 2.1
    probe(T0)
    assert len(ran) == 2


def test_veto_probe_never_raises_when_the_log_cant_be_read():
    probe = REAL_VETO_PROBE(OLD_RADIO, run=lambda *a, **k: (_ for _ in ()).throw(CmdError("Access is denied.")))
    assert probe(T0) is False


def test_switch_isnt_done_until_windows_has_the_radio(monkeypatch):
    connected_world(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    states = iter(["unknown", "unknown", "on"])
    monkeypatch.setattr(bt, "power", lambda: next(states))
    steps, now = [], [0.0]
    bt.switch("builtin", clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s),
              on_step=lambda text, step, of, label: steps.append((step, now[0])))
    assert steps[-1][0] == 4 and steps[-1][1] >= bt._SETTLE + 2  # reconnecting began only after the two "unknown" polls (+ the drop settle)
    use_fake(monkeypatch, FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)]))
    monkeypatch.setattr(bt, "power", lambda: "unknown")  # Windows never gets a radio: the switch fails and rolls back
    with pytest.raises(bt.BtError, match="Built-in MediaTek radio didn't start. Switched back"):
        bt.switch("builtin", sleep=lambda s: None, clock=iter(range(100)).__next__)
