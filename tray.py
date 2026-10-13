"""Tray: notification-area icon, widget placement above the taskbar, start-with-Windows, one running copy."""
import ctypes, os, threading
from ctypes import wintypes
from pathlib import Path

import winrun

_run = winrun.run  # tests replace this
TASK = "Unigen Manager"
MUTEX = "Local\\UnigenManager.Instance"
SHOW_EVENT = "Local\\UnigenManager.Show"
WIDGET_W = 342


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


def launch_command(root, windir=os.environ.get("WINDIR", r"C:\Windows")):
    return f'"{Path(windir, "pyw.exe")}" -3.10 "{Path(root, "UnigenManager.pyw")}" --tray'


def startup_enabled():
    try:
        _run(["schtasks", "/Query", "/TN", TASK])
        return True
    except winrun.CmdError:
        return False


def set_startup(on, root):
    """At sign-in, start the tray with admin rights (no prompt every time)."""
    if on:
        _run(["schtasks", "/Create", "/TN", TASK, "/TR", launch_command(root), "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"])
    else:
        _run(["schtasks", "/Delete", "/TN", TASK, "/F"])


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
        menu = pystray.Menu(
            pystray.MenuItem("Show widget", lambda: toggle_widget(), default=True, visible=False),
            pystray.MenuItem("Open Unigen Manager", lambda: open_main()),
            pystray.MenuItem("Start with Windows", self._toggle_startup, checked=lambda item: startup_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: quit_app()),
        )
        self.icon = pystray.Icon("UnigenManager", icon_image(), "Unigen Manager", menu)

    def _toggle_startup(self):
        set_startup(not startup_enabled(), self._root)

    def start(self):
        self.icon.run_detached()
        threading.Thread(target=self._tooltip_loop, daemon=True).start()

    def _tooltip_loop(self):
        while True:
            try:
                self.icon.title = self._status()[:127]  # Windows caps tray tooltips at 128 characters
            except Exception:
                pass
            if self._stop.wait(10):
                return

    def stop(self):
        self._stop.set()
        self.icon.stop()
