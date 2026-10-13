"""Start Unigen Manager: elevate (radio switching needs it), log to app.log, open the window."""
import ctypes, logging, subprocess, sys
from pathlib import Path

from api import Api, DATA_DIR

ROOT = Path(__file__).resolve().parent
UI = ROOT / "ui" / "index.html"
_SHORTCUT = """
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Unigen Manager.lnk'))
$s.TargetPath = Join-Path $env:WINDIR 'pyw.exe'
$s.Arguments = '-3.10 "' + $p.script + '"'
$s.WorkingDirectory = $p.dir
$s.Description = 'Wi-Fi and Bluetooth manager for the Unigen dongle'
$s.Save()
'{"ok":true}'
"""


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def should_relaunch(argv, admin):
    return not admin and "--no-elevate" not in argv


def relaunch_as_admin(argv, *, shell_execute=None):
    """Start an elevated copy. Returns False if the user declined the Windows prompt."""
    shell_execute = shell_execute or ctypes.windll.shell32.ShellExecuteW
    params = subprocess.list2cmdline([str(ROOT / "UnigenManager.pyw"), *argv, "--no-elevate"])
    return shell_execute(None, "runas", sys.executable, params, None, 1) > 32


def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=DATA_DIR / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def install_shortcut(run=None):
    from winrun import ps
    (run or ps)(_SHORTCUT, {"script": str(ROOT / "UnigenManager.pyw"), "dir": str(ROOT)})


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--install-shortcut" in argv:
        install_shortcut()
        return 0
    admin = is_admin()
    if should_relaunch(argv, admin) and relaunch_as_admin(argv):
        return 0  # the elevated copy takes over; if declined, carry on without admin
    setup_logging()
    import webview
    api = Api(admin=admin)
    window = webview.create_window("Unigen Manager", url=str(UI), js_api=api, width=1180, height=780,
                                   min_size=(940, 620), background_color="#16202B")
    api._window = window
    webview.start(debug="--debug" in argv, private_mode=True)
    return 0
