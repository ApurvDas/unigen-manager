import pytest
import btwinrt as w


def rec(id, name, le=False, present=True, connected=False, address="020000000010", major=None, minor=None, appearance=None):
    return {"id": id, "name": name, "le": le, "present": present, "connected": connected, "address": address,
            "major": major, "minor": minor, "appearance": appearance}


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
                     "kind": "Headphones", "connected": False, "address": "020000000011"}]


def test_merge_prefers_connected_record_and_sorts_by_name():
    rows = w.merge([rec("Bluetooth#b", "Den Beats Pill", major=4, minor=5, address="020000000012"),
                    rec("Bluetooth#a", "Den Beats Pill", major=4, minor=5, connected=True, address="020000000013"),
                    rec("Bluetooth#j", "armband", major=7, minor=1)])
    assert [r["name"] for r in rows] == ["armband", "Den Beats Pill"]
    assert rows[1]["id"] == "Bluetooth#a" and rows[1]["connected"] and rows[1]["address"] == "020000000013"


def test_le_only_row_and_unnamed_label():
    (row,) = w.merge([rec("BluetoothLE#m", "", le=True, appearance=0x03C2, address="7A0000006A44")])
    assert row["kind"] == "Mouse" and row["name"] == "Unknown device 6A44"


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
