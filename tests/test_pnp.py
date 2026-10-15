import pnp


def test_address_from_instance():
    hfp = r"BTHENUM\{0000111E-0000-1000-8000-00805F9B34FB}_VID&0001004C_PID&201A\8&2538F730&0&020000000013_C00000000"
    assert pnp.address_from_instance(hfp) == "020000000013"
    assert pnp.address_from_instance(r"BTHENUM\{0000111E-0000-1000-8000-00805F9B34FB}_LOCALMFG&0046\7&1&0&000000000000_00000000") is None
    assert pnp.address_from_instance(r"USB\VID_368B&PID_8D81&MI_00\6&28B24B5D&0&0000") is None


# ---- set_enabled: success is the device's state, not the call's result ----
import pytest

from winrun import CmdError

DEV = r"USB\VID_0000&PID_0000\7&AAAA0001&0&0000"
STARTED, PROBLEM = pnp._DN_STARTED, pnp._DN_HAS_PROBLEM
ON, OFF = (STARTED, 0), (PROBLEM, pnp._CM_PROB_DISABLED)


class Dev:
    """Fakes pnp._change and pnp._status; `states` is what each status read sees (the last one repeats)."""

    def __init__(self, monkeypatch, states, change_error=None):
        self.states, self.reads, self.changes, self.now, self.change_error = list(states), 0, [], 0.0, change_error
        monkeypatch.setattr(pnp, "_change", self.change)
        monkeypatch.setattr(pnp, "_status", self.status)

    def change(self, instance_id, on):
        self.changes.append((instance_id, on))
        if self.change_error:
            raise self.change_error

    def status(self, instance_id):
        self.reads += 1
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def set(self, on, wait=30.0):
        pnp.set_enabled(DEV, on, wait, sleep=self.sleep, clock=lambda: self.now)

    def sleep(self, s):
        self.now += s


def test_reached_states():
    assert pnp._reached(ON, True) and not pnp._reached(OFF, True) and not pnp._reached((0, 0), True)
    assert pnp._reached(OFF, False) and not pnp._reached(ON, False)
    assert not pnp._reached((PROBLEM, 10), False) and not pnp._reached((STARTED | PROBLEM, 10), True)
    assert not pnp._reached(None, True) and not pnp._reached(None, False)


def test_set_enabled_returns_as_soon_as_the_state_is_reached(monkeypatch):
    d = Dev(monkeypatch, [OFF, OFF, OFF, ON])  # the first read is the check before changing anything
    d.set(True)
    assert d.changes == [(DEV, True)] and d.reads == 4 and d.now == 0.5  # polled every 0.25 s


def test_set_enabled_leaves_a_device_already_in_that_state_alone(monkeypatch):
    d = Dev(monkeypatch, [ON])
    d.set(True)
    assert d.changes == []


def test_set_enabled_trusts_the_state_when_the_call_fails(monkeypatch):
    d = Dev(monkeypatch, [ON, OFF], CmdError("The data is invalid."))
    d.set(False)  # the first read still shows the old state, the second the new one
    assert d.reads == 2


def test_set_enabled_ignores_need_restart_when_the_device_did_change(monkeypatch):
    d = Dev(monkeypatch, [OFF], CmdError("Windows needs a restart to finish changing that device."))
    d.set(False)


def test_set_enabled_reports_windows_sentence_when_state_never_arrives(monkeypatch):
    d = Dev(monkeypatch, [ON], CmdError("The data is invalid."))
    with pytest.raises(CmdError, match="The data is invalid."):
        d.set(False, wait=5)
    assert d.now == 5


def test_set_enabled_without_a_sentence_says_what_didnt_happen(monkeypatch):
    d = Dev(monkeypatch, [OFF])
    with pytest.raises(CmdError, match="The device didn't turn on."):
        d.set(True, wait=1)
    d = Dev(monkeypatch, [ON])
    with pytest.raises(CmdError, match="The device didn't turn off."):
        d.set(False, wait=1)


def test_set_enabled_asks_again_when_windows_refused(monkeypatch):
    # the radio's removal is vetoed (~7 s), Windows flags it "needs restart"; the next call goes through at once
    d = Dev(monkeypatch, [ON])
    def change(instance_id, on):
        d.changes.append((instance_id, on))
        if len(d.changes) == 1:
            raise CmdError("The data is invalid.")
        d.states = [OFF]
    monkeypatch.setattr(pnp, "_change", change)
    d.set(False)
    assert d.changes == [(DEV, False), (DEV, False)] and d.now == 3.0  # asked again after the 3 s retry window


def test_set_enabled_asks_twice_at_most_then_only_waits(monkeypatch):
    d = Dev(monkeypatch, [ON], CmdError("The data is invalid."))  # the radio never finishes turning off
    with pytest.raises(CmdError):
        d.set(False, wait=45)
    assert len(d.changes) == 2 and d.now == 45


def test_set_enabled_waits_for_a_device_windows_cant_find_yet(monkeypatch):
    d = Dev(monkeypatch, [None, None, ON])
    d.set(True)
    assert d.reads == 3
