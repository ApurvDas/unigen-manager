"""Start Unigen Manager: elevate (radio switching needs it), log to app.log, open the window."""
import ctypes, logging, subprocess, sys, threading
from pathlib import Path

import tray
from api import Api, DATA_DIR

ROOT = Path(__file__).resolve().parent
UI = ROOT / "ui" / "index.html"
WIDGET = ROOT / "ui" / "widget.html"
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
    instance = tray.claim_instance()
    if instance is None:  # another copy is running: bring it forward instead
        if not tray.signal_show() and not admin:
            relaunch_as_admin(argv)  # it runs elevated; an elevated copy can reach it
        return 0
    if should_relaunch(argv, admin):
        tray.release(instance)  # let the elevated copy own the instance
        if relaunch_as_admin(argv):
            return 0
        instance = tray.claim_instance()  # declined: carry on without admin
    setup_logging()
    import webview
    api = Api(admin=admin)
    main_win = webview.create_window("Unigen Manager", url=str(UI), js_api=api, width=1180, height=780,
                                     min_size=(940, 620), background_color="#16202B", hidden="--tray" in argv)
    widget = webview.create_window("Unigen Manager widget", url=str(WIDGET), js_api=api, width=tray.WIDGET_W, height=480,
                                   frameless=True, easy_drag=False, resizable=False, on_top=True, hidden=True,
                                   background_color="#1F2C3A")
    api._window, api._widget = main_win, widget
    api._main_visible = "--tray" not in argv
    stop = threading.Event()

    def on_closing():  # closing only hides; Quit is in the tray menu
        if stop.is_set():
            return True
        api._main_visible = False
        main_win.hide()
        return False

    def on_widget_closing():  # Alt+F4 on the widget hides it too
        if stop.is_set():
            return True
        api.hide_widget()
        return False

    main_win.events.closing += on_closing
    widget.events.closing += on_widget_closing
    icon = None

    def quit_app():
        stop.set()
        if icon:
            icon.stop()
        widget.destroy()
        main_win.destroy()

    def after_start():
        nonlocal icon
        icon = tray.Tray(toggle_widget=api._toggle_widget, open_main=api._show_main, quit_app=quit_app,
                         root=ROOT, status=api._status)
        icon.start()
        threading.Thread(target=tray.watch_show, args=(api._show_main, stop), daemon=True).start()

    webview.start(after_start, debug="--debug" in argv, private_mode=True)
    tray.release(instance)
    return 0
