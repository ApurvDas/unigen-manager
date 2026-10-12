import base64, json, subprocess
import pytest
import winrun


class Done:
    def __init__(self, out=b"", err=b"", code=0):
        self.stdout, self.stderr, self.returncode = out, err, code


def test_rejects_string_commands():
    with pytest.raises(TypeError):
        winrun.run("netsh wlan show interfaces")


def test_runs_list_hidden_without_shell(monkeypatch):
    seen = {}
    def fake(args, **kw):
        seen.update(kw, args=args)
        return Done(b"hello\r\n")
    monkeypatch.setattr(subprocess, "run", fake)
    assert winrun.run(["netsh", "wlan", 'name=a "b" & c']) == "hello\r\n"
    assert seen["args"] == ["netsh", "wlan", 'name=a "b" & c']
    assert "shell" not in seen or seen["shell"] is False
    assert seen["creationflags"] & winrun.CREATE_NO_WINDOW
    assert seen["capture_output"] is True


def test_nonzero_exit_raises_last_line(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda a, **k: Done(b"", b"warning\r\nThe network is not available.\r\n", 1))
    with pytest.raises(winrun.CmdError, match="The network is not available."):
        winrun.run(["netsh"])


def test_timeout_and_missing_program(monkeypatch):
    def slow(a, **k): raise subprocess.TimeoutExpired(a, 5)
    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(winrun.CmdError, match="took longer than 5 s"):
        winrun.run(["ping"], timeout=5)
    def missing(a, **k): raise FileNotFoundError
    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(winrun.CmdError, match="was not found"):
        winrun.run(["nope.exe"])


def test_ps_passes_params_as_env_json_and_encoded_script(monkeypatch):
    seen = {}
    def fake(args, **kw):
        seen.update(kw, args=args)
        return Done('{"ok":true}'.encode("utf-8"))
    monkeypatch.setattr(subprocess, "run", fake)
    out = winrun.ps("Write-Output 1", {"id": 'x"; Remove-Item C:\\ -Recurse'})
    assert out == '{"ok":true}'
    assert seen["args"][:6] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand"]
    script = base64.b64decode(seen["args"][6]).decode("utf-16-le")
    assert script.endswith("Write-Output 1")
    assert "Remove-Item" not in script  # hostile params never reach script text
    assert json.loads(seen["env"]["UM_ARGS"]) == {"id": 'x"; Remove-Item C:\\ -Recurse'}


def test_real_command_round_trip():
    assert "ok" in winrun.run(["cmd", "/c", "echo", "ok"])
