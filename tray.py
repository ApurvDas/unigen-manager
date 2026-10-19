"""Tray: notification-area icon, widget placement above the taskbar, start-with-Windows, one running copy."""
import ctypes, logging, os, subprocess, sys, threading
from ctypes import wintypes
from pathlib import Path

import winrun

_run, _ps = winrun.run, winrun.ps  # tests replace these
TASK = "Unigen Manager"
MUTEX = "Local\\UnigenManager.Instance"
SHOW_EVENT = "Local\\UnigenManager.Show"
WIDGET_W = 342
TOOLTIP_EVERY = 2  # seconds between tooltip refreshes: the live rate moves; api._status reuses its netsh part for 10 s


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def work_area():
    """The desktop minus the taskbar, in physical pixels (pywebview makes the process DPI-aware)."""
    r = _RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


def scale():
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96
    except AttributeError:
        return 1.0


def widget_position(area, width, height, scale=1.0, margin=12):
    """Bottom-right corner just above the taskbar, in the logical pixels pywebview expects."""
    left, top, right, bottom = area
    return round(right / scale - width - margin), round(bottom / scale - height - margin)


_REGISTER = """
$a = New-ScheduledTaskAction -Execute $p.exe -Argument $p.args -WorkingDirectory $p.dir
$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $p.name -Action $a -Trigger $t -Settings $s -RunLevel Highest -Force | Out-Null
"""
_UNREGISTER = "Unregister-ScheduledTask -TaskName $p.name -Confirm:$false"


def startup_enabled():
    try:
        _run(["schtasks", "/Query", "/TN", TASK])
        return True
    except winrun.CmdError:
        return False


def launch_target(root, *, frozen=None, executable=None, windir=None):
    """How to start this app: (program, leading arguments, working folder).
    Packaged as UnigenManager.exe: the exe itself. From source: pyw.exe -3.10 and the UnigenManager.pyw in root."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        exe = Path(executable or sys.executable)
        return str(exe), [], str(exe.parent)
    windir = windir or os.environ.get("WINDIR", r"C:\Windows")
    return str(Path(windir, "pyw.exe")), ["-3.10", str(Path(root, "UnigenManager.pyw"))], str(root)


def set_startup(on, root, **target):
    """At sign-in, start the tray with admin rights (no prompt), also on battery and with no time limit."""
    if on:
        exe, lead, workdir = launch_target(root, **target)
        _ps(_REGISTER, {"name": TASK, "exe": exe, "dir": workdir, "args": subprocess.list2cmdline([*lead, "--tray"])})
    else:
        _ps(_UNREGISTER, {"name": TASK})


_k32 = None


def _kernel32():
    global _k32
    if _k32 is None:
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for f in (_k32.CreateMutexW, _k32.CreateEventW, _k32.OpenEventW):
            f.restype = wintypes.HANDLE
    return _k32


def claim_instance():
    """A mutex handle if this is the only running copy; None if another copy owns it."""
    k = _kernel32()
    h = k.CreateMutexW(None, False, MUTEX)
    err = ctypes.get_last_error()
    if h and err != 183:  # 183 = ERROR_ALREADY_EXISTS
        return h
    if h:
        k.CloseHandle(h)
    return None  # it exists, or an elevated copy owns it and we may not open it (5 = access denied)


def release(handle):
    if handle:
        _kernel32().CloseHandle(handle)


def signal_show():
    """Ask the running copy to show its window. False if none can be reached."""
    k = _kernel32()
    ev = k.OpenEventW(0x0002, False, SHOW_EVENT)  # EVENT_MODIFY_STATE
    if not ev:
        return False
    k.SetEvent(ev)
    k.CloseHandle(ev)
    return True


def watch_show(on_show, stop):
    k = _kernel32()
    ev = k.CreateEventW(None, False, False, SHOW_EVENT)
    try:
        while not stop.is_set():
            if k.WaitForSingleObject(ev, 500) == 0:
                on_show()
    finally:
        k.CloseHandle(ev)


def icon_image(size=64):
    """The cyan signal arcs from the UI logo, drawn for the notification area."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d, s = ImageDraw.Draw(img), size / 18
    color, width = (79, 179, 200, 255), max(2, round(size / 11))  # --b5

    def box(r):
        cx, cy = 9 * s, 13.6 * s
        return [cx - r * s, cy - r * s, cx + r * s, cy + r * s]

    d.arc(box(9), 225, 315, fill=color, width=width)
    d.arc(box(5.4), 225, 315, fill=color, width=width)
    d.ellipse(box(1.7), fill=color)
    return img


class Tray:
    """Notification-area icon. Left-click toggles the widget; right-click shows the menu."""

    def __init__(self, *, toggle_widget, open_main, quit_app, root, status):
        import pystray
        self._status, self._root, self._stop = status, root, threading.Event()
        self._startup = startup_enabled()  # cached: the menu must not run schtasks on every click
        menu = pystray.Menu(
            pystray.MenuItem("Show widget", lambda: toggle_widget(), default=True, visible=False),
            pystray.MenuItem("Open Unigen Manager", lambda: open_main()),
            pystray.MenuItem("Start with Windows", self._toggle_startup, checked=lambda item: self._startup),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: quit_app()),
        )
        self.icon = pystray.Icon("UnigenManager", icon_image(), "Unigen Manager", menu)

    def _toggle_startup(self):
        try:
            set_startup(not self._startup, self._root)
        except Exception as e:
            logging.getLogger("unigen").warning("start with Windows toggle failed: %s: %s", type(e).__name__, e)
            self.icon.notify(f"Couldn't change Start with Windows: {e}", "Unigen Manager")
        finally:
            self._startup = startup_enabled()
            self.icon.update_menu()

    def start(self):
        self.icon.run_detached()
        threading.Thread(target=self._tooltip_loop, daemon=True).start()

    def _tooltip_loop(self):
        while True:
            try:
                self.icon.title = self._status()[:127]  # Windows caps tray tooltips at 128 characters
            except Exception:
                pass
            if self._stop.wait(TOOLTIP_EVERY):
                return

    def stop(self):
        self._stop.set()
        self.icon.stop()
