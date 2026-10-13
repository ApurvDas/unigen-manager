"""Bluetooth through Windows' device APIs (WinRT): paired devices, live search, pairing with PIN prompts,
unpairing and the radio's on/off switch. bt.py is the only caller. The pure helpers at the top test without hardware."""
import logging

log = logging.getLogger("unigen")


class BtError(Exception):
    pass


def kind(major, minor):
    """Classic Bluetooth class of device -> what the row says."""
    minor = minor or 0
    if major == 4:
        if minor in (14, 15):
            return "TV"
        return "Headphones" if minor in (1, 2, 6) else "Speaker" if minor in (5, 7, 8, 10) else "Audio"
    if major == 5:
        if (minor & 0x0F) in (1, 2):
            return "Controller"
        return {0x10: "Keyboard", 0x20: "Mouse", 0x30: "Keyboard"}.get(minor & 0x30, "Input device")
    return {1: "Computer", 2: "Phone", 7: "Wearable"}.get(major, "Device")


def le_kind(appearance):
    """Bluetooth LE GAP appearance -> what the row says (category = top 10 bits, subcategory = low 6)."""
    if not appearance:
        return "Device"
    cat, sub = appearance >> 6, appearance & 0x3F
    if cat == 15:
        return {1: "Keyboard", 2: "Mouse", 3: "Controller", 4: "Controller"}.get(sub, "Input device")
    return {1: "Phone", 2: "Computer", 3: "Wearable", 5: "TV", 10: "Audio", 33: "Speaker", 37: "Headphones"}.get(cat, "Device")


def record_kind(r):
    return kind(r["major"], r["minor"]) if r["major"] is not None else le_kind(r["appearance"])


def merge(records):
    """One row per device. A device's classic and LE records (same name) become one row that keeps every id;
    the classic, connected record leads, because pairing and audio go through it.
    ponytail: matching by name merges two different devices that share a name; random LE addresses leave nothing better."""
    rows = {}
    for r in sorted(records, key=lambda r: (r["le"], not r["connected"])):
        key = r["name"] or r["id"]
        k = record_kind(r)
        row = rows.get(key)
        if row is None:
            rows[key] = {"id": r["id"], "ids": [r["id"]], "name": r["name"] or f"Unknown device {r['address'][-4:]}",
                         "kind": k, "connected": r["connected"], "address": r["address"]}
        else:
            row["ids"].append(r["id"])
            row["connected"] = row["connected"] or r["connected"]
            if row["kind"] == "Device":
                row["kind"] = k
    return sorted(rows.values(), key=lambda row: row["name"].lower())


def nearby_rows(records):
    """Search results: devices really in range, with a name (Windows Settings hides nameless beacons too)."""
    return merge([r for r in records if r["present"] and r["name"]])


_REFUSED = "The device refused. Put it in pairing mode, and disconnect it from your phone first."
_NO_ANSWER = "The device didn't answer. Bring it closer and make sure it's in pairing mode."
_CANCELLED = "Pairing cancelled."
_MESSAGES = {
    "AUTHENTICATION_FAILURE": _REFUSED, "CONNECTION_REJECTED": _REFUSED, "REMOTE_DEVICE_HAS_ASSOCIATION": _REFUSED,
    "NOT_READY_TO_PAIR": _REFUSED,
    "AUTHENTICATION_TIMEOUT": _NO_ANSWER, "HARDWARE_FAILURE": _NO_ANSWER, "FAILED": _NO_ANSWER,
    "NO_SUPPORTED_PROFILES": _NO_ANSWER, "NOT_PAIRED": _NO_ANSWER,
    "REJECTED_BY_HANDLER": _CANCELLED, "PAIRING_CANCELED": _CANCELLED,
    "AUTHENTICATION_NOT_ALLOWED": "Wrong PIN. Try again.", "INVALID_CEREMONY_DATA": "Wrong PIN. Try again.",
    "OPERATION_ALREADY_IN_PROGRESS": "Windows is already pairing a device. Wait a moment and try again.",
    "TOO_MANY_CONNECTIONS": "Too many devices are connected. Disconnect one and try again.",
    "ACCESS_DENIED": "Windows didn't allow the pairing.",
}


def pair_message(status):
    return _MESSAGES.get(status, f"Pairing failed ({status.replace('_', ' ').lower()}).")


def answer(kind, pin, ask):
    """What to tell Windows for one pairing request: (accept, pin_to_send).
    kind None = confirm only (the Pair click was the consent); ask(kind, pin) -> (accepted, typed) shows the page prompt."""
    if kind is None:
        return True, None
    ok, typed = ask(kind, pin)
    if not ok:
        return False, None
    if kind == "provide":
        typed = (typed or "").strip()
        return (True, typed) if typed else (False, None)
    return True, None
