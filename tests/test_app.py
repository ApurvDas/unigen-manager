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


def test_main_opens_window_with_api(monkeypatch, tmp_path):
    made = {}
    fake = types.SimpleNamespace(
        create_window=lambda title, **kw: made.update(title=title, **kw) or "WINDOW",
        start=lambda **kw: made.update(start=kw))
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(app, "is_admin", lambda: False)
    monkeypatch.setattr(app, "setup_logging", lambda: None)
    assert app.main(["--no-elevate"]) == 0
    assert made["title"] == "Unigen Manager" and made["url"].endswith("index.html")
    assert made["js_api"]._admin is False and made["js_api"]._window == "WINDOW"
    assert made["background_color"] == "#16202B" and made["start"]["debug"] is False


def test_main_hands_over_to_elevated_copy(monkeypatch):
    monkeypatch.setattr(app, "is_admin", lambda: False)
    monkeypatch.setattr(app, "relaunch_as_admin", lambda argv: True)
    monkeypatch.setitem(sys.modules, "webview", None)  # importing webview would fail: main must return first
    assert app.main([]) == 0
