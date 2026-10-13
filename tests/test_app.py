import sys, types
import pytest
import app


def test_should_relaunch():
    assert app.should_relaunch([], admin=False) is True
    assert app.should_relaunch([], admin=True) is False
    assert app.should_relaunch(["--no-elevate"], admin=False) is False  # the elevated copy never loops


def test_relaunch_builds_runas_call_and_reports_decline():
    seen = []
    def fake(hwnd, verb, exe, params, cwd, show):
        seen.append((verb, exe, params))
        return 5  # SE_ERR_ACCESSDENIED: the user said No
    assert app.relaunch_as_admin(["--debug"], shell_execute=fake) is False
    verb, exe, params = seen[0]
    assert verb == "runas" and exe == sys.executable
    assert params.endswith("--debug --no-elevate") and "UnigenManager.pyw" in params
    assert app.relaunch_as_admin([], shell_execute=lambda *a: 42) is True


def test_install_shortcut_passes_paths_as_params():
    seen = {}
    app.install_shortcut(run=lambda script, params: seen.update(script=script, params=params))
    assert seen["params"]["script"].endswith("UnigenManager.pyw")
    assert "UnigenManager.pyw" not in seen["script"]  # paths travel as $p, not script text
    assert "pyw.exe" in seen["script"] and "-3.10" in seen["script"]


def test_main_hands_over_to_elevated_copy(monkeypatch):
    monkeypatch.setattr(app.tray, "claim_instance", lambda: "HANDLE")
    monkeypatch.setattr(app.tray, "release", lambda h: None)
    monkeypatch.setattr(app, "is_admin", lambda: False)
    monkeypatch.setattr(app, "relaunch_as_admin", lambda argv: True)
    monkeypatch.setitem(sys.modules, "webview", None)  # importing webview would fail: main must return first
    assert app.main([]) == 0


class FakeWebview:
    def __init__(self):
        self.windows, self.started = [], None

    def create_window(self, title, **kw):
        w = types.SimpleNamespace(title=title, kw=kw, events=types.SimpleNamespace(closing=Handlers()))
        self.windows.append(w)
        return w

    def start(self, func=None, **kw):
        self.started = kw


class Handlers(list):
    def __iadd__(self, fn):
        self.append(fn)
        return self


@pytest.fixture
def single(monkeypatch):
    monkeypatch.setattr(app.tray, "claim_instance", lambda: "HANDLE")
    monkeypatch.setattr(app.tray, "release", lambda h: None)


def test_main_opens_window_and_widget(monkeypatch, single):
    fake = FakeWebview()
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(app, "is_admin", lambda: True)
    monkeypatch.setattr(app, "setup_logging", lambda: None)
    assert app.main(["--tray"]) == 0
    main_win, widget = fake.windows
    assert main_win.kw["url"].endswith("index.html") and main_win.kw["hidden"] is True  # --tray: start hidden
    assert widget.kw["url"].endswith("widget.html") and widget.kw["frameless"] and widget.kw["on_top"] and widget.kw["hidden"]
    assert main_win.kw["js_api"] is widget.kw["js_api"]  # one Api for both windows
    assert fake.started["debug"] is False


def test_closing_main_window_hides_it(monkeypatch, single):
    fake = FakeWebview()
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(app, "is_admin", lambda: True)
    monkeypatch.setattr(app, "setup_logging", lambda: None)
    app.main([])
    main_win = fake.windows[0]
    hidden = []
    main_win.hide = lambda: hidden.append(True)
    assert main_win.events.closing[0]() is False and hidden == [True]  # False cancels the close
    assert main_win.kw["js_api"]._main_visible is False  # hidden windows stop polling


def test_tray_start_is_not_visible_and_normal_start_is(monkeypatch, single):
    for argv, visible in (([], True), (["--tray"], False)):
        fake = FakeWebview()
        monkeypatch.setitem(sys.modules, "webview", fake)
        monkeypatch.setattr(app, "is_admin", lambda: True)
        monkeypatch.setattr(app, "setup_logging", lambda: None)
        app.main(argv)
        assert fake.windows[0].kw["js_api"]._main_visible is visible


def test_closing_widget_hides_it(monkeypatch, single):
    fake = FakeWebview()
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(app, "is_admin", lambda: True)
    monkeypatch.setattr(app, "setup_logging", lambda: None)
    app.main([])
    widget = fake.windows[1]
    api = widget.kw["js_api"]
    hidden = []
    widget.hide = lambda: hidden.append(True)
    api._widget, api._widget_shown = widget, True
    assert widget.events.closing[0]() is False and hidden == [True] and api._widget_shown is False


def test_second_copy_shows_the_first(monkeypatch):
    monkeypatch.setattr(app.tray, "claim_instance", lambda: None)
    monkeypatch.setattr(app.tray, "signal_show", lambda: True)
    monkeypatch.setattr(app, "is_admin", lambda: False)
    monkeypatch.setattr(app, "relaunch_as_admin", lambda argv: pytest.fail("should not elevate"))
    assert app.main([]) == 0


def test_second_copy_elevates_to_reach_an_elevated_first(monkeypatch):
    seen = []
    monkeypatch.setattr(app.tray, "claim_instance", lambda: None)
    monkeypatch.setattr(app.tray, "signal_show", lambda: False)  # medium integrity can't open the elevated copy's event
    monkeypatch.setattr(app, "is_admin", lambda: False)
    monkeypatch.setattr(app, "relaunch_as_admin", lambda argv: seen.append(argv) or True)
    assert app.main([]) == 0 and seen == [[]]
