"""Start Unigen Manager: elevate (radio switching needs it), log to app.log, open the window."""
import ctypes, logging, logging.handlers, platform, subprocess, sys, threading
from pathlib import Path

import hw, traffic, tray
from api import Api, DATA_DIR
from version import VERSION

ROOT = Path(__file__).resolve().parent
UI = ROOT / "ui" / "index.html"
WIDGET = ROOT / "ui" / "widget.html"
_SHORTCUT = """
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Unigen Manager.lnk'))
$s.TargetPath = $p.target
$s.Arguments = $p.args
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


def relaunch_as_admin(argv, *, shell_execute=None, frozen=None):
    """Start an elevated copy. Returns False if the user declined the Windows prompt."""
    shell_execute = shell_execute or ctypes.windll.shell32.ShellExecuteW
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    lead = [] if frozen else [str(ROOT / "UnigenManager.pyw")]  # the .exe is its own program
    params = subprocess.list2cmdline([*lead, *argv, "--no-elevate"])
    return shell_execute(None, "runas", sys.executable, params, None, 1) > 32


def setup_logging(argv=(), admin=False):
    """app.log: every action the page asks for, every failure with where it happened. 1 MB, then app.log.1 … .3.
    --debug also logs the calls the page polls every few seconds."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(DATA_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(handlers=[handler], level=logging.DEBUG if "--debug" in argv else logging.INFO,
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(module)s:%(lineno)d: %(message)s")
    log = logging.getLogger("unigen")
    sys.excepthook = lambda *exc: log.critical("unhandled error", exc_info=exc)
    threading.excepthook = lambda a: log.critical("unhandled error in thread %s", a.thread and a.thread.name,
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    log.info("==== start: version %s, %s, admin=%s, args=%s, Windows %s", VERSION,
             "exe" if getattr(sys, "frozen", False) else "source", admin, argv, platform.version())


def install_shortcut(run=None, **target):
    from winrun import ps
    exe, lead, workdir = tray.launch_target(ROOT, **target)
    (run or ps)(_SHORTCUT, {"target": exe, "args": subprocess.list2cmdline(lead), "dir": workdir})


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
    setup_logging(argv, admin)
    import webview
    sampler = traffic.Sampler()
    api = Api(admin=admin, sampler=sampler)
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
        sampler.stop()  # writes today's totals
        if icon:
            icon.stop()
        widget.destroy()
        main_win.destroy()

    def after_start():
        nonlocal icon
        icon = tray.Tray(toggle_widget=api._toggle_widget, open_main=api._show_main, quit_app=quit_app,
                         root=ROOT, status=api._status)
        icon.start()
        api._notify = lambda text: icon.icon.notify(text, "Unigen Manager")
        threading.Thread(target=tray.watch_show, args=(api._show_main, stop), daemon=True).start()
        follower = hw.Follower(api._settings, api._follow_notify, admin=api._admin, push=api._push_step)

        def follow():  # a pass now (enforces the saved choice after a restart), then every 5 s
            while True:
                follower.step()
                if stop.wait(5):
                    return
        threading.Thread(target=follow, daemon=True).start()

    sampler.start()
    try:
        # a kept WebView2 profile starts faster than a fresh temp one each launch
        webview.start(after_start, debug="--debug" in argv, private_mode=False, storage_path=str(DATA_DIR / "webview"))
    finally:
        sampler.stop()  # also when the windows end some other way than Quit
    tray.release(instance)
    return 0
