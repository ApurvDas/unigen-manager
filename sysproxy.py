"""Point Windows at the merge proxy's PAC file and keep both adapters connected, saving the old values so they can
always be put back (merge off, quit, and the next start after a crash)."""
import ctypes
import json
import logging
import winreg
from pathlib import Path

PAC = (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", "AutoConfigURL")
WCM = (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WcmSvc\GroupPolicy", "fMinimizeConnections")
log = logging.getLogger("unigen")
ITEMS = (("pac", PAC), ("wcm", WCM))
KINDS = {"pac": winreg.REG_SZ, "wcm": winreg.REG_DWORD}  # fixed: restoring a value puts it back with its own kind


class Reg:
    """The real registry. Tests pass a dict-backed fake with the same three methods."""

    @staticmethod
    def _access(hive, base):
        # 64-bit view for HKLM, so a 32-bit build still hits the real policy key
        return base | (winreg.KEY_WOW64_64KEY if hive == winreg.HKEY_LOCAL_MACHINE else 0)

    def get(self, hive, path, name):
        try:
            with winreg.OpenKey(hive, path, 0, self._access(hive, winreg.KEY_READ)) as k:
                return winreg.QueryValueEx(k, name)[0]
        except FileNotFoundError:
            return None

    def put(self, hive, path, name, value, kind):
        # CreateKeyEx: the WcmSvc\GroupPolicy key often doesn't exist yet
        with winreg.CreateKeyEx(hive, path, 0, self._access(hive, winreg.KEY_SET_VALUE)) as k:
            winreg.SetValueEx(k, name, 0, kind, value)

    def delete(self, hive, path, name):
        try:
            with winreg.OpenKey(hive, path, 0, self._access(hive, winreg.KEY_SET_VALUE)) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass


def _refresh():
    """Tell running programs the proxy settings changed (SETTINGS_CHANGED, then REFRESH)."""
    for opt in (39, 37):
        ctypes.windll.wininet.InternetSetOptionW(None, opt, None, 0)


def _load(settings):
    try:
        data = json.loads(Path(settings).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(settings, data):
    settings = Path(settings)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data), encoding="utf-8")


def apply(pac_url, settings, reg=Reg()):
    """Save the originals (only the ones not already saved, so our own PAC never becomes the "original"), then set ours.
    The record goes to settings.json before the registry changes, so a crash between the two can still be undone."""
    data = _load(settings)
    saved = data["merge_saved"] if isinstance(data.get("merge_saved"), dict) else {}
    missing = {k: reg.get(*t) for k, t in ITEMS if k not in saved}
    if missing or "merge_saved" not in data:
        _save(settings, {**data, "merge_saved": {**saved, **missing}})
    reg.put(*PAC, pac_url, KINDS["pac"])
    reg.put(*WCM, 0, KINDS["wcm"])
    _refresh()


def restore(settings, reg=Reg()):
    """Put the saved values back (a saved None means it was absent, so delete it). False, touching nothing, with no record.
    Each item is done on its own and only writes if it differs: HKLM needs admin, so without it that item stays in the
    record for the next elevated start and startup never fails."""
    data = _load(settings)
    saved = data.get("merge_saved")
    if not isinstance(saved, dict):
        return False
    left, changed = {}, False
    for key, triple in ITEMS:
        if key not in saved:
            continue
        try:
            if reg.get(*triple) != saved[key]:
                if saved[key] is None:
                    reg.delete(*triple)
                else:
                    reg.put(*triple, saved[key], KINDS[key])
                changed = True
        except PermissionError as e:
            log.warning("couldn't restore %s (will retry next start): %s", triple[2], e)
            left[key] = saved[key]
    if left:
        data["merge_saved"] = left
    else:
        del data["merge_saved"]
    _save(settings, data)
    if changed:
        _refresh()
    return True
