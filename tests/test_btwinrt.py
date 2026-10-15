import pytest
import btwinrt as w


def rec(id, name, le=False, present=True, connected=False, address="020000000010", major=None, minor=None, appearance=None,
        radio=None):
    return {"id": id, "name": name, "le": le, "present": present, "connected": connected, "address": address,
            "major": major, "minor": minor, "appearance": appearance, "radio": radio}


def test_classic_kinds():
    assert w.kind(4, 5) == "Speaker" and w.kind(4, 6) == "Headphones" and w.kind(4, 1) == "Headphones"
    assert w.kind(4, 15) == "TV" and w.kind(4, 0) == "Audio"
    assert w.kind(5, 2) == "Controller" and w.kind(5, 0x10) == "Keyboard" and w.kind(5, 0x20) == "Mouse"
    assert w.kind(2, 3) == "Phone" and w.kind(1, 3) == "Computer" and w.kind(0, 0) == "Device" and w.kind(None, None) == "Device"


def test_le_kinds_from_appearance():
    assert w.le_kind(0x03C1) == "Keyboard" and w.le_kind(0x03C2) == "Mouse" and w.le_kind(0x03C4) == "Controller"
    assert w.le_kind(0x0941) == "Headphones" and w.le_kind(0x0841) == "Speaker" and w.le_kind(0x0040) == "Phone"
    assert w.le_kind(0) == "Device" and w.le_kind(None) == "Device"


def test_merge_twins_keeps_classic_id_and_every_id():
    rows = w.merge([rec("BluetoothLE#le-1", "Galaxy Buds2 Pro", le=True, appearance=0x0941, address="7A0000000001"),
                    rec("Bluetooth#c-1", "Galaxy Buds2 Pro", major=4, minor=6, address="020000000011")])
    assert rows == [{"id": "Bluetooth#c-1", "ids": ["Bluetooth#c-1", "BluetoothLE#le-1"], "name": "Galaxy Buds2 Pro",
                     "kind": "Headphones", "connected": False, "address": "020000000011", "here": True}]


def test_merge_prefers_connected_record_and_sorts_by_name():
    rows = w.merge([rec("Bluetooth#b", "Den Beats Pill", major=4, minor=5, address="020000000012"),
                    rec("Bluetooth#a", "Den Beats Pill", major=4, minor=5, connected=True, address="020000000013"),
                    rec("Bluetooth#j", "armband", major=7, minor=1)])
    assert [r["name"] for r in rows] == ["armband", "Den Beats Pill"]
    assert rows[1]["id"] == "Bluetooth#a" and rows[1]["connected"] and rows[1]["address"] == "020000000013"


def test_le_only_row_and_unnamed_label():
    (row,) = w.merge([rec("BluetoothLE#m", "", le=True, appearance=0x03C2, address="7A0000006A44")])
    assert row["kind"] == "Mouse" and row["name"] == "Unknown device 6A44"


def test_radio_parsed_from_classic_and_le_ids():
    assert w.radio_of("Bluetooth#Bluetooth02:00:00:00:00:a1-02:00:00:00:00:b2") == "0200000000a1"
    assert w.radio_of("BluetoothLE#BluetoothLE02:00:00:00:00:A1-02:00:00:00:00:b2") == "0200000000a1"
    assert w.radio_of("Bluetooth#nonsense") is None


A, B = "0200000000a1", "0200000000a2"  # the PC's two radios


def test_merge_marks_devices_paired_only_on_the_other_radio():
    rows = w.merge([rec("Bluetooth#b-buds", "Test Buds", major=4, minor=6, radio=B),
                    rec("Bluetooth#a-pill", "Test Pill", major=4, minor=5, radio=A)], local=A)
    assert {r["name"]: r["here"] for r in rows} == {"Test Buds": False, "Test Pill": True}


def test_merge_leads_with_the_record_on_this_radio():
    rows = w.merge([rec("Bluetooth#b-pill", "Test Pill", major=4, minor=5, connected=True, radio=B),
                    rec("Bluetooth#a-pill", "Test Pill", major=4, minor=5, radio=A)], local=A)
    assert len(rows) == 1 and rows[0]["here"] is True
    assert rows[0]["id"] == "Bluetooth#a-pill" and rows[0]["ids"] == ["Bluetooth#a-pill", "Bluetooth#b-pill"]


def test_merge_earbuds_with_only_their_le_record_here_need_a_re_pair():
    """The app.log case: LE record on the radio in use, classic (audio) record on the other one."""
    rows = w.merge([rec("BluetoothLE#a-buds", "Test Buds", le=True, appearance=0x0941, address="7A0000000001", radio=A),
                    rec("Bluetooth#b-buds", "Test Buds", major=4, minor=6, address="020000000011", radio=B)], local=A)
    assert rows[0]["here"] is False
    assert rows[0]["id"] == "Bluetooth#b-buds" and rows[0]["address"] == "020000000011"  # re-pair/connect use the classic one


def test_merge_classic_on_this_radio_is_here_and_le_only_devices_count_any_record():
    rows = w.merge([rec("BluetoothLE#b-buds", "Test Buds", le=True, address="7A0000000001", radio=B),
                    rec("Bluetooth#a-buds", "Test Buds", major=4, minor=6, address="020000000011", radio=A),
                    rec("BluetoothLE#a-mouse", "Test Mouse", le=True, appearance=0x03C2, radio=A)], local=A)
    assert {r["name"]: r["here"] for r in rows} == {"Test Buds": True, "Test Mouse": True}


def test_merge_without_a_local_radio_counts_every_row_here():
    rows = w.merge([rec("Bluetooth#b-buds", "Test Buds", major=4, minor=6, radio=B),
                    rec("Bluetooth#x", "Test Pill", major=4, minor=5, radio=None)])
    assert [r["here"] for r in rows] == [True, True]


def test_nearby_rows_drop_absent_and_unnamed():
    rows = w.nearby_rows([rec("Bluetooth#1", "Pixel 8", major=2, minor=3), rec("Bluetooth#2", "Gone", present=False),
                          rec("BluetoothLE#3", "", le=True)])
    assert [r["name"] for r in rows] == ["Pixel 8"]


@pytest.mark.parametrize("status, text", [
    ("AUTHENTICATION_FAILURE", "The device refused. Put it in pairing mode, and disconnect it from your phone first."),
    ("CONNECTION_REJECTED", "The device refused."),
    ("AUTHENTICATION_TIMEOUT", "The device didn't answer. Bring it closer and make sure it's in pairing mode."),
    ("FAILED", "The device didn't answer."),
    ("REJECTED_BY_HANDLER", "Pairing cancelled."),
    ("PAIRING_CANCELED", "Pairing cancelled."),
    ("AUTHENTICATION_NOT_ALLOWED", "Wrong PIN. Try again."),
    ("TOO_MANY_CONNECTIONS", "Too many devices are connected."),
    ("PROTECTION_LEVEL_COULD_NOT_BE_MET", "Pairing failed (protection level could not be met)."),
])
def test_pair_messages(status, text):
    assert w.pair_message(status).startswith(text)


def test_answer_for_each_ceremony():
    asked = []
    def ask(kind, pin, reply=(True, None)):
        asked.append((kind, pin)); return reply
    assert w.answer(None, "", ask) == (True, None) and asked == []          # confirm only: no prompt
    assert w.answer("confirm", "482913", ask) == (True, None)
    assert w.answer("confirm", "482913", lambda k, p: (False, None)) == (False, None)
    assert w.answer("display", "482913", ask) == (True, None)
    assert w.answer("provide", "", lambda k, p: (True, " 0000 ")) == (True, "0000")
    assert w.answer("provide", "", lambda k, p: (True, "  ")) == (False, None)  # blank PIN declines
    assert w.answer("provide", "", lambda k, p: (False, "0000")) == (False, None)
    assert asked == [("confirm", "482913"), ("display", "482913")]


import threading


class FakeWatcher:
    def __init__(self):
        self.cb, self.started, self.stopped = {}, False, 0
    def add_added(self, f): self.cb["added"] = f
    def add_updated(self, f): self.cb["updated"] = f
    def add_removed(self, f): self.cb["removed"] = f
    def add_stopped(self, f): self.cb["stopped"] = f
    def start(self): self.started = True
    def stop(self): self.stopped += 1


class Upd:
    def __init__(self, id): self.id = id


class Rec(dict):
    """A fake DeviceInformation that is already a record (record() is patched to return it)."""
    @property
    def id(self): return self["id"]


def make_search(monkeypatch, seconds=60):
    monkeypatch.setattr(w, "record", lambda di: dict(di))
    seen, fw = [], FakeWatcher()
    s = w.Search(lambda rows, done: seen.append(([r["name"] for r in rows], done)), seconds, watcher=fw)
    s.start()
    return s, fw, seen


def test_search_pushes_rows_as_devices_come_and_go(monkeypatch):
    s, fw, seen = make_search(monkeypatch)
    assert fw.started
    fw.cb["added"](None, Rec(rec("Bluetooth#1", "Pixel 8", major=2, minor=3)))
    fw.cb["added"](None, Rec(rec("BluetoothLE#2", "", le=True)))               # nameless: no change, no push
    fw.cb["added"](None, Rec(rec("Bluetooth#3", "Galaxy Buds2 Pro", major=4, minor=6)))
    fw.cb["removed"](None, Upd("Bluetooth#1"))
    s.stop(); s.stop()                                                          # second stop is a no-op
    assert seen == [(["Pixel 8"], False), (["Galaxy Buds2 Pro", "Pixel 8"], False), (["Galaxy Buds2 Pro"], False),
                    (["Galaxy Buds2 Pro"], True)]
    assert fw.stopped == 1


def test_search_stopped_by_windows_ends_search(monkeypatch):
    s, fw, seen = make_search(monkeypatch)
    fw.cb["stopped"](None, None)  # radio turned off or dongle unplugged
    assert seen == [([], True)]


def test_search_times_out(monkeypatch):
    s, fw, seen = make_search(monkeypatch, seconds=0.01)
    for _ in range(100):
        if seen: break
        threading.Event().wait(0.01)
    assert seen == [([], True)] and fw.stopped == 1


def test_pair_maps_status_and_stops_search(monkeypatch):
    stops = []
    monkeypatch.setattr(w, "search_stop", lambda: stops.append(1))
    async def fake(dev_id, ask): return "PAIRED"
    monkeypatch.setattr(w, "_pair", fake)
    w.pair("Bluetooth#1", None)
    async def refused(dev_id, ask): return "AUTHENTICATION_FAILURE"
    monkeypatch.setattr(w, "_pair", refused)
    with pytest.raises(w.BtError, match="The device refused"):
        w.pair("Bluetooth#1", None)
    assert stops == [1, 1]


def test_pair_turns_windows_errors_into_a_sentence(monkeypatch):
    monkeypatch.setattr(w, "search_stop", lambda: None)
    async def gone(dev_id, ask): raise OSError("element not found")
    monkeypatch.setattr(w, "_pair", gone)
    with pytest.raises(w.BtError, match="didn't answer"):
        w.pair("Bluetooth#1", None)


def test_second_pairing_is_refused(monkeypatch):
    w._pair_lock.acquire()
    try:
        with pytest.raises(w.BtError, match="Already pairing a device."):
            w.pair("Bluetooth#2", None)
    finally:
        w._pair_lock.release()


def test_here_id_needs_the_device_on_this_radio(monkeypatch):
    class Dev:
        device_information = type("DI", (), {"id": "Bluetooth#a-buds"})()
    async def found(addr): return Dev() if addr == 0x020000000011 else None
    monkeypatch.setattr(w.BluetoothDevice, "from_bluetooth_address_async", found, raising=False)
    assert w.here_id("020000000011") == "Bluetooth#a-buds"
    with pytest.raises(w.BtError, match="can't find that device on this radio"):
        w.here_id("020000000099")


def test_power_is_unknown_when_windows_refuses(monkeypatch):
    async def denied(): raise w.BtError("Windows didn't let the app control Bluetooth.")
    monkeypatch.setattr(w, "_radio", denied)
    assert w.power() == "unknown"
