import threading, time, uuid
import pytest
import tray
from winrun import CmdError


def test_widget_position_bottom_right_in_logical_pixels():
    assert tray.widget_position((0, 0, 1920, 1040), 342, 480) == (1566, 548)
    # 125 % scaling: the work area comes in physical pixels, pywebview wants logical ones
    assert tray.widget_position((0, 0, 2400, 1300), 342, 480, scale=1.25) == (1566, 548)


def test_launch_command_quotes_paths():
    cmd = tray.launch_command(r"C:\Users\Noisemaker\UnigenManager", windir=r"C:\Windows")
    assert cmd == r'"C:\Windows\pyw.exe" -3.10 "C:\Users\Noisemaker\UnigenManager\UnigenManager.pyw" --tray'


def test_startup_task_commands(monkeypatch):
    calls = []
    def fake(args, **kw):
        calls.append(args)
        if args[1] == "/Query" and len(calls) == 1:
            raise CmdError("ERROR: The system cannot find the file specified.")
        return ""
    monkeypatch.setattr(tray, "_run", fake)
    assert tray.startup_enabled() is False
    assert tray.startup_enabled() is True
    tray.set_startup(True, r"C:\UM")
    assert calls[-1][:3] == ["schtasks", "/Create", "/TN"] and calls[-1][3] == "Unigen Manager"
    assert calls[-1][calls[-1].index("/RL") + 1] == "HIGHEST" and calls[-1][calls[-1].index("/SC") + 1] == "ONLOGON"
    tray.set_startup(False, r"C:\UM")
    assert calls[-1] == ["schtasks", "/Delete", "/TN", "Unigen Manager", "/F"]


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
