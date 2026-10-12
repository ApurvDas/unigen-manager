"""Bluetooth: radios (switch with rollback), devices (list, pair, remove), audio connect/disconnect."""
import ctypes, json, os, time, uuid
from ctypes import wintypes
from pathlib import Path

import winrun
from wifi import ADAPTER_NAMES

_ps = winrun.ps  # tests replace this
SERVICE_TOGGLE = True  # Task 1 spike result. False = Connect/Disconnect always open Windows Bluetooth settings.
_SCRIPT = Path(__file__).with_name("bt.ps1")
LMP = {6: "4.0", 7: "4.1", 8: "4.2", 9: "5.0", 10: "5.1", 11: "5.2", 12: "5.3", 13: "5.4", 14: "6.0"}
AUDIO_SERVICES = ["0000110B-0000-1000-8000-00805F9B34FB", "0000111E-0000-1000-8000-00805F9B34FB"]  # A2DP sink, Hands-free
_PAIR_ERRORS = {
    "AuthenticationTimeout": "The device didn't answer in time. Put it in pairing mode and try again.",
    "AuthenticationFailure": "Pairing failed. Check the code shown on the device.",
    "RejectedByHandler": "Pairing was cancelled.",
    "AccessDenied": "Windows didn't allow the pairing.",
}


class BtError(Exception):
    pass


def _call(action, **params):
    return json.loads(_ps(_SCRIPT.read_text(encoding="utf-8"), {"action": action, **params}, timeout=90))


def version(lmp):
    return LMP.get(lmp)


def kind(major, minor):
    if major == 4:
        return "Headphones" if minor in (1, 2, 6) else "Speaker" if minor in (5, 7) else "Audio"
    if major == 5:
        return "Controller" if minor in (1, 2) else "Input device"
    return {1: "Computer", 2: "Phone", 7: "Wearable"}.get(major, "Device")


def radio_key(instance_id, name):
    up = instance_id.upper()
    if "VID_368B&PID_8D81" in up:
        return "unigen"
    if "VID_13D3&PID_3563" in up or "MEDIATEK" in name.upper():
        return "builtin"
    return instance_id


def radios():
    return [{"key": radio_key(r["id"], r["name"]), "id": r["id"], "name": r["name"], "ok": r["status"] == "OK",
             "disabled": r["problem"] in ("CM_PROB_DISABLED", "22"), "version": version(r["lmp"])} for r in _call("radios")]


def _label(key):
    return ADAPTER_NAMES.get(key, key)


def switch(target, *, wait=10.0, clock=time.monotonic, sleep=time.sleep):
    rs = radios()
    tgt = next((r for r in rs if r["key"] == target), None)
    if tgt is None:
        raise BtError("That Bluetooth radio isn't connected to this PC.")
    others = [r for r in rs if r["ok"] and r["key"] != target]
    if tgt["ok"] and not others:
        return target
    for r in others:  # Windows runs one Bluetooth radio at a time
        _call("disable", id=r["id"])
    _call("enable", id=tgt["id"])
    deadline = clock() + wait
    while clock() < deadline:
        if any(r["key"] == target and r["ok"] for r in radios()):
            return target
        sleep(1)
    try:  # never leave the user without Bluetooth
        _call("disable", id=tgt["id"])
    except winrun.CmdError:
        pass
    for r in others:
        _call("enable", id=r["id"])
    back = f" Switched back to the {_label(others[0]['key'])}." if others else ""
    raise BtError(f"The {_label(target)} radio didn't start.{back}")


def devices(paired):
    return [{"id": d["id"], "name": d["name"], "connected": bool(d["connected"]), "kind": kind(d["major"], d["minor"]),
             "address": d["address"]} for d in _call("paired" if paired else "nearby")]


def pair(device_id):
    status = _call("pair", id=device_id)["status"]
    if status not in ("Paired", "AlreadyPaired"):
        raise BtError(_PAIR_ERRORS.get(status, f"Pairing failed ({status})."))


def remove(device_id):
    status = _call("unpair", id=device_id)["status"]
    if status not in ("Unpaired", "AlreadyUnpaired"):
        raise BtError(f"Couldn't remove the device ({status}).")


# ---- audio connect via bthprops.cpl (decided by the Task 1 spike) ----
class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in
                ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("Address", ctypes.c_ulonglong), ("ulClassofDevice", wintypes.ULONG),
                ("fConnected", wintypes.BOOL), ("fRemembered", wintypes.BOOL), ("fAuthenticated", wintypes.BOOL),
                ("stLastSeen", _SYSTEMTIME), ("stLastUsed", _SYSTEMTIME), ("szName", wintypes.WCHAR * 248)]


class _RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


def _set_audio(address_hex, flags):
    """Set the audio services of a paired device: [0, 1] makes Windows reconnect it, [0] disconnects it."""
    lib, k32 = ctypes.WinDLL("bthprops.cpl"), ctypes.WinDLL("kernel32")
    lib.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    radio, params = wintypes.HANDLE(), _RADIO_PARAMS(ctypes.sizeof(_RADIO_PARAMS))
    find = lib.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not find:
        raise BtError("No Bluetooth radio is on.")
    lib.BluetoothFindRadioClose(wintypes.HANDLE(find))
    try:
        info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO), Address=int(address_hex, 16))
        if lib.BluetoothGetDeviceInfo(radio, ctypes.byref(info)):
            raise BtError("Windows doesn't know that device.")
        for flag in flags:
            for g in AUDIO_SERVICES:
                guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(g).bytes_le)
                rc = lib.BluetoothSetServiceState(radio, ctypes.byref(info), ctypes.byref(guid), flag)
                if rc and rc != 1060:  # 1060 = the device doesn't offer this service (e.g. no hands-free)
                    raise BtError(f"Windows refused (error {rc}).")
    finally:
        k32.CloseHandle(radio)


def _toggle(address_hex, name, flags, verb, open_settings):
    if SERVICE_TOGGLE:
        try:
            _set_audio(address_hex, flags)
            return
        except (BtError, OSError, ValueError):
            pass
    open_settings("ms-settings:bluetooth")
    raise BtError(f"Windows didn't let the app {verb} {name}. Bluetooth settings are open so you can do it there.")


def connect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, [0, 1], "connect", open_settings)


def disconnect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, [0], "disconnect", open_settings)
