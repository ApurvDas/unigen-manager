import threading, time, uuid
import pytest
import tray
from winrun import CmdError


def test_widget_position_bottom_right_in_logical_pixels():
    assert tray.widget_position((0, 0, 1920, 1040), 342, 480) == (1566, 548)
    # 125 % scaling: the work area comes in physical pixels, pywebview wants logical ones
    assert tray.widget_position((0, 0, 2400, 1300), 342, 480, scale=1.25) == (1566, 548)


def test_startup_task_commands(monkeypatch):
    calls, scripts = [], []
    def fake(args, **kw):
        calls.append(args)
        if args[1] == "/Query" and len(calls) == 1:
            raise CmdError("ERROR: The system cannot find the file specified.")
        return ""
    monkeypatch.setattr(tray, "_run", fake)
    monkeypatch.setattr(tray, "_ps", lambda script, params=None, **kw: scripts.append((script, params)))
    assert tray.startup_enabled() is False
    assert tray.startup_enabled() is True
    tray.set_startup(True, r"C:\My UM", frozen=False, windir=r"C:\Windows")
    script, params = scripts[-1]
    for needle in ("AllowStartIfOnBatteries", "DontStopIfGoingOnBatteries", "[TimeSpan]::Zero", "-RunLevel Highest", "Register-ScheduledTask"):
        assert needle in script
    assert "UnigenManager.pyw" not in script and "C:" not in script  # paths travel as $p, not script text
    assert params == {"name": "Unigen Manager", "exe": r"C:\Windows\pyw.exe", "dir": r"C:\My UM",
                      "args": r'-3.10 "C:\My UM\UnigenManager.pyw" --tray'}
    tray.set_startup(True, r"C:\Temp\_MEI123", frozen=True, executable=r"C:\Apps\Unigen Manager\UnigenManager.exe")
    assert scripts[-1][1] == {"name": "Unigen Manager", "exe": r"C:\Apps\Unigen Manager\UnigenManager.exe",
                              "dir": r"C:\Apps\Unigen Manager", "args": "--tray"}  # the .exe starts itself
    tray.set_startup(False, r"C:\UM")
    script, params = scripts[-1]
    assert "Unregister-ScheduledTask" in script and "-Confirm:$false" in script and params == {"name": "Unigen Manager"}


class FakeIcon:
    def __init__(self):
        self.notes, self.updates = [], 0

    def notify(self, message, title):
        self.notes.append((message, title))

    def update_menu(self):
        self.updates += 1


def _tray_with(monkeypatch, enabled):
    t = tray.Tray.__new__(tray.Tray)  # skip pystray: only the toggle logic is under test
    t._root, t.icon, t._startup = r"C:\UM", FakeIcon(), False
    state = {"on": enabled}
    monkeypatch.setattr(tray, "startup_enabled", lambda: state["on"])
    return t, state


def test_toggle_startup_refreshes_checkbox(monkeypatch):
    t, state = _tray_with(monkeypatch, False)
    monkeypatch.setattr(tray, "set_startup", lambda on, root: state.update(on=on))
    t._toggle_startup()
    assert t._startup is True and t.icon.updates == 1 and t.icon.notes == []


def test_toggle_startup_failure_is_visible(monkeypatch):
    t, state = _tray_with(monkeypatch, False)
    def boom(on, root):
        raise CmdError("Access is denied.")
    monkeypatch.setattr(tray, "set_startup", boom)
    t._toggle_startup()
    assert t._startup is False and t.icon.updates == 1
    assert t.icon.notes == [("Couldn't change Start with Windows: Access is denied.", "Unigen Manager")]


@pytest.fixture
def unique_names(monkeypatch):
    tag = uuid.uuid4().hex
    monkeypatch.setattr(tray, "MUTEX", f"Local\\UnigenManager.Test.{tag}")
    monkeypatch.setattr(tray, "SHOW_EVENT", f"Local\\UnigenManager.TestShow.{tag}")


def test_single_instance(unique_names):
    first = tray.claim_instance()
    assert first
    assert tray.claim_instance() is None  # a second copy sees the first
    tray.release(first)
    again = tray.claim_instance()
    assert again
    tray.release(again)


def test_second_copy_asks_first_to_show(unique_names):
    shown, stop = threading.Event(), threading.Event()
    t = threading.Thread(target=tray.watch_show, args=(shown.set, stop), daemon=True)
    t.start()
    time.sleep(0.2)
    assert tray.signal_show() is True
    assert shown.wait(2)
    stop.set()
    t.join(2)


def test_signal_show_without_running_copy(unique_names):
    assert tray.signal_show() is False


def test_icon_image():
    img = tray.icon_image(64)
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert img.getbbox() is not None  # something was drawn
