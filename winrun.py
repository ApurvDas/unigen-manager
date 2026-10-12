"""The only place that starts processes: argument lists, no shell, no console flash."""
import base64, json, os, subprocess

CREATE_NO_WINDOW = 0x08000000
_PS_PRELUDE = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'\n"
               "trap { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }  # plain-text errors, never CLIXML\n"
               "$p = $env:UM_ARGS | ConvertFrom-Json\n")


class CmdError(Exception):
    """A command failed; str(e) is safe to show the user."""


def run(args, *, timeout=30, encoding="oem", env=None):
    if isinstance(args, str):
        raise TypeError("run() takes an argument list, not a string")
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, env=env, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise CmdError(f"{args[0]} took longer than {timeout:g} s.") from None
    except FileNotFoundError:
        raise CmdError(f"{args[0]} was not found on this PC.") from None
    out = p.stdout.decode(encoding, errors="replace")
    if p.returncode != 0:
        err = (p.stderr.decode(encoding, errors="replace") or out).strip()
        raise CmdError(err.splitlines()[-1].strip() if err else f"{args[0]} failed (exit {p.returncode}).")
    return out


def ps(script, params=None, *, timeout=60):
    """Run a fixed PowerShell 5.1 script. Inputs arrive as $p (from UM_ARGS JSON), never as script text."""
    encoded = base64.b64encode((_PS_PRELUDE + script).encode("utf-16-le")).decode("ascii")
    env = {**os.environ, "UM_ARGS": json.dumps(params or {})}
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
               timeout=timeout, encoding="utf-8", env=env)
