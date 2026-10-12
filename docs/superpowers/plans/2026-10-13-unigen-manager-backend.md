# Unigen Manager Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved Unigen Manager prototypes (`ui/index.html` and the tray widget `ui/widget.html`) into a working Windows app with an always-on notification-area widget. A Python backend controls both Wi-Fi adapters, both Bluetooth radios and speed tests, and a full test suite covers it: unit, contract, UI, read-only hardware tests, and a manual checklist.

**Architecture:**
- **Python modules, one job each:**
  - `winrun.py` runs commands safely.
  - `wifi.py` handles netsh and wlanapi.
  - `bt.py` with `bt.ps1` handles Bluetooth through WinRT and PnP via PowerShell 5.1.
  - `speed.py` runs ping and the sampled HTTP throughput test.
- **`api.py` is the only file that knows both sides.** Its `Api` class turns every result into `{"ok": true, "data": …}` or `{"ok": false, "error": "<plain message>"}`.
- **`app.py`** handles elevation and opens the pywebview window. `UnigenManager.pyw` is a 3-line launcher.
- **`tray.py`** adds the notification-area icon (pystray), the frameless widget window above the taskbar, start-with-Windows (scheduled task) and the single running copy.
- **The page talks to `window.pywebview.api`.** Opened with `?mock`, it uses `ui/mock-api.js` instead, which has the same method names. That is how the prototype keeps working in a browser and how the UI tests run.

**Tech Stack:**
- Python 3.10 (`py -3.10`), pywebview 6.2.1 (WebView2), pystray 0.19.5 and Pillow 12.3.0 (tray icon)
- Windows tools: netsh, `wlanapi.dll` and `bthprops.cpl` via `ctypes`, and PowerShell 5.1 WinRT for Bluetooth
- `http.client` for speed tests
- pytest 9.1.1, and Playwright 1.63.0 driving the installed Microsoft Edge (`channel="msedge"`, no browser download)
- anime.js 4.5.0, already stored in `ui/vendor/`

**Spec:** `docs/superpowers/specs/2026-10-13-unigen-manager-design.md`. Read it alongside this plan.

**Deliberate deviations from the spec** (each one is noted where it applies):
1. **Speed test:** uses `http.client` with `source_address=(adapter_ip, 0)` instead of `curl.exe --interface`. That's the only way to get the per-sample Mbps that the "Last test" chart needs.
2. **`delete_profile(ssid)`** deletes the network from **every** adapter that has it, because each row in the Saved list stands for one SSID.
3. **New-network setup** supports WPA2-Personal and Open only. WPA3 and Enterprise networks get a plain message pointing to Windows settings.
4. **Polling:** `adapters()` is polled every **2 s** instead of the spec's 3 s, because the same poll feeds the 2-second signal chart.
5. **Extra files:** `winrun.py`, `api.py`, `app.py`, `ui/mock-api.js` and `tests/` are added beyond the spec's file list, to keep each file to one job and make it testable.

## Global Constraints

- **Python:** run everything with `py -3.10` (`C:\Users\Noisemaker\AppData\Local\Programs\Python\Python310`). Never use the MSYS2 `python` on PATH; it has no pip.
- **Pinned versions:** `pywebview==6.2.1`, `pystray==0.19.5`, `Pillow==12.3.0` (runtime); `pytest==9.1.1` and `playwright==1.63.0` (dev only). Playwright uses `channel="msedge"`, so do not run `playwright install`.
- **anime.js 4.5.0** stays vendored at `ui/vendor/anime.umd.min.js`. No CDN or remote scripts.
- **The approved dark design does not change.** Tokens: `--panel #16202B`, `--raised #1F2C3A`, `--line #2A3A4B`, `--ink #E6EDF3`, `--muted #8DA0B3`, `--b24 #E3A33B`, `--b5 #4FB3C8`, `--ok #5CC08A`, `--err #F07167`, `--uni #9085e9`, `--bi #d55181`. All copy is in sentence case.
- **Commands:** every subprocess call uses an argument list with `CREATE_NO_WINDOW` and never `shell=True`. SSIDs and device IDs go in as separate arguments, or as JSON in the `UM_ARGS` environment variable. They are never pasted into command or script text.
- **Passwords:** never logged, never written to disk except inside a `tempfile.TemporaryDirectory()` that is deleted before the function returns.
- **Page safety:** every string shown in the page goes through `esc()` or `textContent`.
- **Platform:** Windows 10 19045 with netsh output in English. Unrecognised output raises `ParseError("Couldn't read the Wi-Fi status. Is Windows set to English?")`.
- **Admin:** the app relaunches itself elevated on every start. If the user declines, it runs without Bluetooth radio switching.
- **Adapter keys:** `"unigen"` = description contains `AIC8800` (Bluetooth `USB\VID_368B&PID_8D81`). `"builtin"` = description contains `MT7921` (Bluetooth `USB\VID_13D3&PID_3563`, name contains `MediaTek`).
- **Standards:** Wi-Fi standard comes from `netsh wlan show drivers` radio types (`802.11ax` → `Wi-Fi 6`). Bluetooth version comes from `DEVPKEY_Bluetooth_RadioLmpVersion` (9→5.0, 10→5.1, 11→5.2, 12→5.3, 13→5.4, 14→6.0).
- **App data:** `%LOCALAPPDATA%\UnigenManager\` holds `results.json` and `app.log`.
- **Stopping processes:** stop only processes you started, by process ID. Never use `taskkill /IM python.exe`: it kills every Python program on the PC.

## Review Focus

1. **A nearby network names itself `<img src=x onerror=alert(1)>`.** It must show as plain text and never run. *Test: Task 8, `test_hostile_ssid_is_text`.*
2. **A new network's SSID contains `&`, `<` or `"`.** The profile XML must stay valid, the SSID bytes must be exact (hex), and the profile name must contain no `"`. *Test: Task 4, `test_profile_xml_escapes_and_hex`, `test_profile_name_has_no_quotes`.*
3. **Wrong password.** After at most 15 s the user sees "Couldn't connect to X. Check the password.", and the half-made profile is deleted. *Test: Task 4, `test_connect_wrong_password_deletes_profile`.*
4. **The Unigen dongle is unplugged while the app is open.** Calls naming `"unigen"` return "The Unigen dongle isn't plugged in." instead of crashing, and the side menu shows it as unplugged. *Tests: Task 7, `test_unplugged_adapter_message`; Task 8, `test_unplugged_adapter_in_rail`.*
5. **netsh output in another language.** A clear `ParseError` message, never wrong data. *Test: Task 3, `test_non_english_output_raises`.*

---

## File Structure

| File | Responsibility |
|---|---|
| `winrun.py` | `run(args)` and `ps(script, params)`: the only places that start processes |
| `wifi.py` | Parse netsh output; adapter identity; profile XML; connect, disconnect, scan, saved-profile actions |
| `bt.ps1` | PowerShell 5.1 script: list radios, enable/disable a radio, list paired and nearby devices, pair, unpair. Reads `$env:UM_ARGS`, writes JSON |
| `bt.py` | Runs `bt.ps1`; LMP→version; device-class→kind; radio switch with rollback; audio connect through `BluetoothSetServiceState` |
| `speed.py` | Adapter IP and gateway; ping; sampled download and upload; result averaging; `results.json` |
| `api.py` | `Api` class exposed to the page: envelopes, plain error messages, adapter keys, admin gating, live speed samples |
| `app.py` | Elevation, logging, pywebview window, `--install-shortcut` |
| `UnigenManager.pyw` | Double-click launcher: `import app; app.main()` |
| `tray.py` | Tray icon and menu, widget placement above the taskbar, start-with-Windows task, single running copy |
| `ui/shared.css`, `ui/shared.js` | Tokens, buttons, the Python bridge and the anime.js helpers, shared by both pages |
| `ui/widget.html` | The tray widget (approved prototype, wired to the API in Task 13) |
| `ui/index.html` | Approved UI. Mock arrays are removed, and every action calls `call(name, …)` |
| `ui/mock-api.js` | Same methods as `Api`, with the prototype's mock data, for `?mock` and the UI tests |
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore` | Tooling |
| `tests/fixtures/*.txt` | Real netsh output captured on this PC (password redacted) |
| `tests/test_*.py` | Unit and contract tests (run by default) |
| `tests/ui/test_ui.py` | Playwright UI tests against `?mock` (marker `ui`, run by default) |
| `tests/hardware/test_readonly.py` | Read-only checks against the real adapters (marker `hardware`, opt-in) |
| `docs/superpowers/test-reports/manual-checklist.md` | Steps and results for state-changing checks |

---

### Task 1: Spike: can the app connect Bluetooth audio devices? (throwaway)

The spec's first build step. The result decides one constant in Task 6 (`SERVICE_TOGGLE`). No product code is written here.

**Files:**
- Create (throwaway, outside the project): `%TEMP%\um-spike\spike_bt_connect.py`
- Modify: `docs/superpowers/specs/2026-10-13-unigen-manager-design.md` (record the result under "Risks")

**Interfaces:**
- Consumes: nothing.
- Produces: a recorded decision, `SERVICE_TOGGLE = True` or `False`, used in Task 6.

- [ ] **Step 1: Ask the user to prepare a device.** They need to turn on a paired speaker (for example JBL Go 3) **without** connecting it, and say which one. Wait for their answer.

- [ ] **Step 2: Write the spike script**

```python
# spike_bt_connect.py: throwaway. Run from an elevated prompt:  py -3.10 spike_bt_connect.py "JBL Go 3"
import ctypes, sys, time, uuid
from ctypes import wintypes

class SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in
                ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]

class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("Address", ctypes.c_ulonglong), ("ulClassofDevice", wintypes.ULONG),
                ("fConnected", wintypes.BOOL), ("fRemembered", wintypes.BOOL), ("fAuthenticated", wintypes.BOOL),
                ("stLastSeen", SYSTEMTIME), ("stLastUsed", SYSTEMTIME), ("szName", wintypes.WCHAR * 248)]

class SEARCH(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("fReturnAuthenticated", wintypes.BOOL), ("fReturnRemembered", wintypes.BOOL),
                ("fReturnUnknown", wintypes.BOOL), ("fReturnConnected", wintypes.BOOL), ("fIssueInquiry", wintypes.BOOL),
                ("cTimeoutMultiplier", ctypes.c_ubyte), ("hRadio", wintypes.HANDLE)]

class GUID(ctypes.Structure):
    _fields_ = [("b", ctypes.c_byte * 16)]
    @classmethod
    def of(cls, s): g = cls(); g.b[:] = list(uuid.UUID(s).bytes_le); return g

class RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]

AUDIO = ["0000110B-0000-1000-8000-00805F9B34FB", "0000111E-0000-1000-8000-00805F9B34FB"]  # A2DP sink, Hands-free
bt = ctypes.WinDLL("bthprops.cpl")
bt.BluetoothFindFirstRadio.restype = wintypes.HANDLE
radio = wintypes.HANDLE()
fr = bt.BluetoothFindFirstRadio(ctypes.byref(RADIO_PARAMS(ctypes.sizeof(RADIO_PARAMS))), ctypes.byref(radio))
print("radio handle:", bool(fr))
bt.BluetoothFindRadioClose(wintypes.HANDLE(fr))
print("sizeof BLUETOOTH_DEVICE_INFO =", ctypes.sizeof(BLUETOOTH_DEVICE_INFO), "(expect 560)")

s = SEARCH(dwSize=ctypes.sizeof(SEARCH), fReturnAuthenticated=1, fReturnRemembered=1, fReturnConnected=1)
info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO))
bt.BluetoothFindFirstDevice.restype = wintypes.HANDLE
h = bt.BluetoothFindFirstDevice(ctypes.byref(s), ctypes.byref(info))
found = None
while h:
    if info.szName == sys.argv[1]:
        found = BLUETOOTH_DEVICE_INFO.from_buffer_copy(info); break
    if not bt.BluetoothFindNextDevice(wintypes.HANDLE(h), ctypes.byref(info)): break
if h: bt.BluetoothFindDeviceClose(wintypes.HANDLE(h))
print("found:", bool(found), "connected before:", bool(found and found.fConnected))
for flag in (0, 1):  # disable then enable the audio services, which makes Windows reconnect
    for g in AUDIO:
        rc = bt.BluetoothSetServiceState(radio, ctypes.byref(found), ctypes.byref(GUID.of(g)), flag)
        print("SetServiceState", g[:8], "flag", flag, "->", rc)
time.sleep(8)
bt.BluetoothGetDeviceInfo(radio, ctypes.byref(found))
print("connected after:", bool(found.fConnected))
```

- [ ] **Step 3: Run it from an elevated terminal.** Use `py -3.10 "%TEMP%\um-spike\spike_bt_connect.py" "<device name>"`.
Expected for success: `sizeof … 560`, `radio handle: True`, `found: True`, every `rc` is `0` (or `1060` for a service the device doesn't have), `connected after: True`, and the speaker announces that it connected.

- [ ] **Step 4: Record the decision.** Under "Risks" in the spec, add the line: `Spike <today's date> on <device>: BluetoothSetServiceState reconnect = WORKS|FAILS (rc values …).`
  - If it **works**, Task 6 uses `SERVICE_TOGGLE = True`.
  - If it **fails** (any rc ≠ 0, or still not connected), use `SERVICE_TOGGLE = False`. Connect and Disconnect will then always open `ms-settings:bluetooth` and say so.

- [ ] **Step 5: Delete `%TEMP%\um-spike\`.** Nothing from the spike is committed except the spec line, which is committed in Task 2's first commit.

---

### Task 2: Repository, tooling and the safe command runner

**Files:**
- Create: `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `tests/__init__.py`, `tests/conftest.py`, `winrun.py`, `tests/test_winrun.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `winrun.CmdError(Exception)`: `str(e)` is safe to show the user.
  - `winrun.run(args: list[str], *, timeout: float = 30, encoding: str = "oem", env: dict | None = None) -> str`
  - `winrun.ps(script: str, params: dict | None = None, *, timeout: float = 60) -> str`: runs Windows PowerShell 5.1 with `$p` set to `params` and UTF-8 output.

- [ ] **Step 1: Initialise git and tooling.** Run in `C:\Users\Noisemaker\UnigenManager`:

```bash
git init
```

`.gitignore`:
```
__pycache__/
.pytest_cache/
*.pyc
.playwright-mcp/
```

`requirements.txt`:
```
pywebview==6.2.1
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==9.1.1
playwright==1.63.0
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
addopts = -m "not hardware" -q
markers =
    ui: Playwright tests of ui/index.html against the mock API (uses installed Microsoft Edge)
    hardware: read-only checks against the real adapters on this PC (run with: py -3.10 -m pytest -m hardware)
```

`tests/__init__.py`: empty file.

`tests/conftest.py`:
```python
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # import project modules (wifi, bt, ...) from tests
FIXTURES = ROOT / "tests" / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
```

Install: `py -3.10 -m pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests** in `tests/test_winrun.py`.

```python
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
```

- [ ] **Step 3: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_winrun.py`.
Expected: FAIL with `ModuleNotFoundError: No module named 'winrun'`.

- [ ] **Step 4: Implement `winrun.py`**

```python
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
```

- [ ] **Step 5: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/test_winrun.py`.
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt requirements-dev.txt pytest.ini tests/__init__.py tests/conftest.py winrun.py tests/test_winrun.py ui docs
git commit -m "chore: tooling, approved UI prototype, spec, and safe command runner"
```

---

### Task 3: Wi-Fi parsers (from real netsh output)

**Files:**
- Create: `tests/fixtures/interfaces.txt`, `tests/fixtures/networks.txt`, `tests/fixtures/profiles.txt`, `tests/fixtures/profile_key.txt`, `tests/fixtures/drivers.txt`
- Create: `wifi.py` (parsers only in this task)
- Test: `tests/test_wifi_parse.py`

**Interfaces:**
- Consumes: nothing.
- Produces (in `wifi.py`):
  - `class ParseError(Exception)` and `class WifiError(Exception)`
  - `parse_interfaces(text) -> list[dict]`. Keys: `name, description, guid, state, ssid, bssid, radio, auth, channel:int, rx:float, tx:float, signal:int, profile`. Missing keys are absent.
  - `parse_networks(text) -> list[dict]`: `{"ssid": str, "auth": str|None, "aps": [{"bssid", "signal": int, "radio", "channel": int, "band": 2.4|5}]}`
  - `parse_profiles(text) -> dict[str, list[str]]`: interface name → profile names
  - `parse_key(text) -> str | None`
  - `parse_drivers(text) -> dict[str, dict]`: interface name → `{"radio_types": list[str], "wpa3": bool}`
  - `band(channel:int) -> float`, `wifi_standard(radio_types) -> str | None`

- [ ] **Step 1: Create the fixtures.** Save each file as UTF-8 with exactly this content. It was captured from this PC on 2026-10-13, with the password redacted.

`tests/fixtures/interfaces.txt`:
```

There are 2 interfaces on the system: 

    Name                   : Wi-Fi
    Description            : MediaTek Wi-Fi 6 MT7921 Wireless LAN Card
    GUID                   : 11111111-2222-4333-8444-555555555551
    Physical address       : 02:00:00:00:00:12
    State                  : connected
    SSID                   : HOME-5G
    BSSID                  : 02:00:00:00:00:01
    Network type           : Infrastructure
    Radio type             : 802.11ac
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Profile
    Channel                : 36
    Receive rate (Mbps)    : 866.7
    Transmit rate (Mbps)   : 866.7
    Signal                 : 80% 
    Profile                : HOME-5G 

    Name                   : Wi-Fi 2
    Description            : AIC8800D80 USB WiFi
    GUID                   : 11111111-2222-4333-8444-555555555552
    Physical address       : 02:00:00:00:00:11
    State                  : disconnected
    Radio status           : Hardware On
                             Software On

    Hosted network status  : Not available
```

`tests/fixtures/networks.txt`:
```
 
Interface name : Wi-Fi 2 
There are 8 networks currently visible. 

SSID 1 : Maple House
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : 02:00:00:00:00:02
         Signal             : 100%  
         Radio type         : 802.11n
         Channel            : 6 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54
    BSSID 2                 : 02:00:00:00:00:03
         Signal             : 26%  
         Radio type         : 802.11ax
         Channel            : 1 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54
    BSSID 3                 : 02:00:00:00:00:04
         Signal             : 24%  
         Radio type         : 802.11ax
         Channel            : 36 
         Basic rates (Mbps) : 6 12 24
         Other rates (Mbps) : 9 18 36 48 54

SSID 2 : [Smart_Fridge]a1b2
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : 02:00:00:00:00:05
         Signal             : 52%  
         Radio type         : 802.11n
         Channel            : 11 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54

SSID 3 : Workshop12
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : 02:00:00:00:00:06
         Signal             : 10%  
         Radio type         : 802.11ax
         Channel            : 11 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54

SSID 4 : HOME-5G
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : 02:00:00:00:00:01
         Signal             : 100%  
         Radio type         : 802.11ac
         Channel            : 36 
         Basic rates (Mbps) : 6 12 24
         Other rates (Mbps) : 9 18 36 48 54

SSID 5 : CEDAR-12
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : 02:00:00:00:00:07
         Signal             : 10%  
         Radio type         : 802.11ax
         Channel            : 11 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54

SSID 6 : AirFiber-Cedar12
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : 02:00:00:00:00:08
         Signal             : 8%  
         Radio type         : 802.11ax
         Channel            : 157 
         Basic rates (Mbps) : 6 12 24
         Other rates (Mbps) : 9 18 36 48 54
    BSSID 2                 : 02:00:00:00:00:09
         Signal             : 32%  
         Radio type         : 802.11ax
         Channel            : 1 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54

SSID 7 : AirFiber-Maple House
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : 02:00:00:00:00:0a
         Signal             : 16%  
         Radio type         : 802.11ax
         Channel            : 157 
         Basic rates (Mbps) : 6 12 24
         Other rates (Mbps) : 9 18 36 48 54
    BSSID 2                 : 02:00:00:00:00:0b
         Signal             : 46%  
         Radio type         : 802.11ax
         Channel            : 11 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54

SSID 8 : 
    Network type            : Infrastructure
    Authentication          : Open
    Encryption              : None 
    BSSID 1                 : 02:00:00:00:00:0c
         Signal             : 6%  
         Radio type         : 802.11ax
         Channel            : 11 
         Basic rates (Mbps) : 1 2 5.5 11
         Other rates (Mbps) : 6 9 12 18 24 36 48 54
```
(SSID 8 has been edited from the capture into a hidden, open network so that case is covered.)

`tests/fixtures/profiles.txt`:
```

Profiles on interface Wi-Fi:

Group policy profiles (read only)
---------------------------------
    <None>

User profiles
-------------
    All User Profile     : HOME-5G
    All User Profile     : phone_hotspot
    All User Profile     : Cafe_wifi
    All User Profile     : Guest_net 2
    All User Profile     : Guest_net

Profiles on interface Wi-Fi 2:

Group policy profiles (read only)
---------------------------------
    <None>

User profiles
-------------
    All User Profile     : HOME-5G
    All User Profile     : Maple House
    All User Profile     : oldrouter
    All User Profile     : Guest_net 2
    All User Profile     : phone_hotspot
    All User Profile     : Cafe_wifi
    All User Profile     : Guest_net
```

`tests/fixtures/profile_key.txt`:
```

Profile HOME-5G on interface Wi-Fi 2: 
======================================================================= 

Applied: All User Profile    

Profile information 
------------------- 
    Version                : 1
    Type                   : Wireless LAN
    Name                   : HOME-5G
    Control options        : 
        Connection mode    : Connect automatically
        Network broadcast  : Connect only if this network is broadcasting
        AutoSwitch         : Do not switch to other networks
        MAC Randomization  : Disabled

Connectivity settings 
--------------------- 
    Number of SSIDs        : 1
    SSID name              : "HOME-5G"
    Network type           : Infrastructure
    Radio type             : [ Any Radio Type ]
    Vendor extension          : Not present

Security settings 
----------------- 
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Authentication         : WPA2-Personal
    Cipher                 : GCMP
    Security key           : Present
    Key Content            : REDACTED-PASS

Cost settings 
------------- 
    Cost                   : Unrestricted
    Congested              : No
    Approaching Data Limit : No
    Over Data Limit        : No
    Roaming                : No
    Cost Source            : Default
```

`tests/fixtures/drivers.txt`:
```

Interface name: Wi-Fi

    Driver                    : MediaTek Wi-Fi 6 MT7921 Wireless LAN Card
    Vendor                    : MediaTek, Inc.
    Provider                  : MediaTek, Inc.
    Date                      : 12-10-2023
    Version                   : 3.0.1.1314
    INF file                  : oem19.inf
    Type                      : Native Wi-Fi Driver
    Radio types supported     : 802.11b 802.11a 802.11g 802.11n 802.11ac 802.11ax
    FIPS 140-2 mode supported : Yes
    802.11w Management Frame Protection supported : Yes
    Hosted network supported  : No
    Authentication and cipher supported in infrastructure mode:
                                Open            None
                                WPA3-Personal   CCMP
                                WPA2-Personal   CCMP
    IHV service present       : Yes
    IHV extensibility DLL path: C:\Windows\system32\mtkihvx.dll

Interface name: Wi-Fi 2

    Driver                    : AIC8800D80 USB WiFi
    Vendor                    : Aic Corp
    Provider                  : AIC
    Date                      : 13-11-2024
    Version                   : 6.40.60.312
    INF file                  : oem65.inf
    Type                      : Native Wi-Fi Driver
    Radio types supported     : 802.11b 802.11b 802.11g 802.11a 802.11n 802.11ac 802.11ax
    Hosted network supported  : Yes
    Authentication and cipher supported in infrastructure mode:
                                Open            None
                                WPA2-Personal   TKIP
                                WPA2-Personal   CCMP
    Wireless Display Supported: Yes (Graphics Driver: Yes, Wi-Fi Driver: Yes)
```

- [ ] **Step 2: Write the failing tests** in `tests/test_wifi_parse.py`.

```python
import pytest
from tests.conftest import fixture
import wifi


def test_interfaces_both_adapters():
    a, b = wifi.parse_interfaces(fixture("interfaces.txt"))
    assert a["name"] == "Wi-Fi" and "MT7921" in a["description"]
    assert a["state"] == "connected" and a["ssid"] == "HOME-5G"
    assert a["channel"] == 36 and a["rx"] == 866.7 and a["signal"] == 80 and a["radio"] == "802.11ac"
    assert a["guid"] == "11111111-2222-4333-8444-555555555551"
    assert b["name"] == "Wi-Fi 2" and b["description"] == "AIC8800D80 USB WiFi"
    assert b["state"] == "disconnected" and "ssid" not in b and "signal" not in b


def test_interfaces_none_present():
    assert wifi.parse_interfaces("There is no wireless interface on the system.\r\n") == []


def test_non_english_output_raises():
    german = "\n    Name                   : WLAN\n    Beschreibung           : AIC8800D80 USB WiFi\n    Status                 : Verbunden\n"
    with pytest.raises(wifi.ParseError, match="Is Windows set to English"):
        wifi.parse_interfaces(german)


def test_networks_bands_and_hidden():
    nets = {n["ssid"]: n for n in wifi.parse_networks(fixture("networks.txt"))}
    assert len(nets) == 8
    bina = nets["Maple House"]
    assert bina["auth"] == "WPA2-Personal"
    assert [(a["channel"], a["signal"], a["band"]) for a in bina["aps"]] == [(6, 100, 2.4), (1, 26, 2.4), (36, 24, 5)]
    assert nets["AirFiber-Cedar12"]["aps"][0] == {"bssid": "02:00:00:00:00:08", "signal": 8, "radio": "802.11ax", "channel": 157, "band": 5}
    assert nets["[Smart_Fridge]a1b2"]["aps"][0]["channel"] == 11
    assert nets[""]["auth"] == "Open"  # hidden network keeps an empty SSID


def test_profiles_per_interface():
    p = wifi.parse_profiles(fixture("profiles.txt"))
    assert p["Wi-Fi"] == ["HOME-5G", "phone_hotspot", "Cafe_wifi", "Guest_net 2", "Guest_net"]
    assert len(p["Wi-Fi 2"]) == 7 and "oldrouter" in p["Wi-Fi 2"]


def test_key_present_and_absent():
    assert wifi.parse_key(fixture("profile_key.txt")) == "REDACTED-PASS"
    assert wifi.parse_key("    Security key           : Absent\n") is None


def test_drivers_standard_and_wpa3():
    d = wifi.parse_drivers(fixture("drivers.txt"))
    assert wifi.wifi_standard(d["Wi-Fi 2"]["radio_types"]) == "Wi-Fi 6"
    assert d["Wi-Fi"]["wpa3"] is True and d["Wi-Fi 2"]["wpa3"] is False
    assert wifi.wifi_standard(["802.11n", "802.11ac"]) == "Wi-Fi 5"
    assert wifi.wifi_standard(["802.11g"]) is None


def test_band_boundaries():
    assert wifi.band(1) == 2.4 and wifi.band(14) == 2.4 and wifi.band(36) == 5 and wifi.band(165) == 5


def test_replacement_characters_do_not_crash():
    text = fixture("networks.txt").replace("Maple House", "Caf\ufffd \ufffd\ufffd")
    assert any(n["ssid"] == "Caf\ufffd \ufffd\ufffd" for n in wifi.parse_networks(text))
```

- [ ] **Step 3: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_wifi_parse.py`.
Expected: FAIL with `ModuleNotFoundError: No module named 'wifi'`.

- [ ] **Step 4: Implement the parsers** at the top of `wifi.py`.

```python
"""Wi-Fi: parse netsh output, identify adapters, and act on networks and saved profiles."""
import re


class ParseError(Exception):
    pass


class WifiError(Exception):
    pass


NOT_ENGLISH = "Couldn't read the Wi-Fi status. Is Windows set to English?"


def _kv(line):
    """'    Key   : value' -> ('Key', 'value'); None when the line has no colon."""
    if ":" not in line:
        return None
    k, v = line.split(":", 1)
    return k.strip(), v.strip()


def _pct(v):
    return int(v.rstrip("%").strip())


_IFACE_FIELDS = {
    "Description": ("description", str), "GUID": ("guid", str), "State": ("state", str),
    "SSID": ("ssid", str), "BSSID": ("bssid", str), "Radio type": ("radio", str),
    "Authentication": ("auth", str), "Channel": ("channel", int), "Receive rate (Mbps)": ("rx", float),
    "Transmit rate (Mbps)": ("tx", float), "Signal": ("signal", _pct), "Profile": ("profile", str),
}


def parse_interfaces(text):
    out, cur = [], None
    for line in text.splitlines():
        kv = _kv(line)
        if not kv:
            continue
        k, v = kv
        if k == "Name":
            cur = {"name": v}
            out.append(cur)
        elif cur is not None and k in _IFACE_FIELDS:
            key, conv = _IFACE_FIELDS[k]
            cur[key] = conv(v)
    if any("description" not in i or "state" not in i for i in out):
        raise ParseError(NOT_ENGLISH)
    return out


def band(channel):
    return 2.4 if channel <= 14 else 5


def parse_networks(text):
    nets, net, ap = [], None, None
    for line in text.splitlines():
        kv = _kv(line)
        if not kv:
            continue
        k, v = kv
        if re.fullmatch(r"SSID \d+", k):
            net, ap = {"ssid": v, "auth": None, "aps": []}, None
            nets.append(net)
        elif net is None:
            continue
        elif k == "Authentication":
            net["auth"] = v
        elif re.fullmatch(r"BSSID \d+", k):
            ap = {"bssid": v}
            net["aps"].append(ap)
        elif ap is not None and k == "Signal":
            ap["signal"] = _pct(v)
        elif ap is not None and k == "Radio type":
            ap["radio"] = v
        elif ap is not None and k == "Channel":
            ap["channel"] = int(v)
            ap["band"] = band(ap["channel"])
    return nets


def parse_profiles(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.fullmatch(r"Profiles on interface (.+):", line.strip())
        if m:
            cur = out.setdefault(m.group(1), [])
            continue
        kv = _kv(line)
        if cur is not None and kv and kv[0] in ("All User Profile", "Current User Profile"):
            cur.append(kv[1])
    return out


def parse_key(text):
    for line in text.splitlines():
        kv = _kv(line)
        if kv and kv[0] == "Key Content":
            return kv[1]
    return None


def parse_drivers(text):
    out, cur = {}, None
    for line in text.splitlines():
        kv = _kv(line)
        if kv and kv[0] == "Interface name":
            cur = out[kv[1]] = {"radio_types": [], "wpa3": False}
        elif cur is None:
            continue
        elif kv and kv[0] == "Radio types supported":
            cur["radio_types"] = kv[1].split()
        elif "WPA3-Personal" in line:
            cur["wpa3"] = True
    return out


_STANDARDS = [("802.11be", "Wi-Fi 7"), ("802.11ax", "Wi-Fi 6"), ("802.11ac", "Wi-Fi 5"), ("802.11n", "Wi-Fi 4")]


def wifi_standard(radio_types):
    return next((name for std, name in _STANDARDS if std in radio_types), None)
```

- [ ] **Step 5: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/test_wifi_parse.py`.
Expected: `9 passed`.

- [ ] **Step 6: Commit**

```bash
git add wifi.py tests/test_wifi_parse.py tests/fixtures
git commit -m "feat(wifi): netsh parsers with real captured fixtures"
```

### Task 4: Wi-Fi actions (connect, disconnect, scan, saved profiles)

**Files:**
- Modify: `wifi.py` (append actions below the parsers)
- Test: `tests/test_wifi_actions.py`

**Interfaces:**
- Consumes: `winrun.run`, `winrun.CmdError`; the Task 3 parsers.
- Produces (in `wifi.py`):
  - `_run`: module-level alias of `winrun.run`. Tests replace it.
  - `adapter_key(description) -> str`: `"unigen"`, `"builtin"`, or the description itself.
  - `ADAPTER_NAMES = {"unigen": "Unigen dongle", "builtin": "Built-in MediaTek"}`
  - `security_kind(auth) -> "open" | "wpa2" | None`
  - `check_password(pw) -> None`: raises `WifiError("The password must be 8 to 63 characters.")`
  - `profile_name(ssid) -> str` and `profile_xml(ssid, kind, password, name) -> str`
  - `interfaces() -> list[dict]`, `networks(iface) -> list[dict]`, `profiles() -> dict[str, list[str]]`, `drivers() -> dict`
  - `trigger_scan(guid) -> None` (wlanapi; hardware only)
  - `scan(iface, guid, *, wait=4.0, sleep=time.sleep) -> list[dict]`
  - `connect(iface, ssid, *, auth=None, password=None, saved=False, timeout=15.0, clock=time.monotonic, sleep=time.sleep) -> dict`: returns the interface dict once connected
  - `disconnect(iface) -> None`
  - `password(iface, ssid) -> str | None`
  - `delete_profile(ssid, ifaces: list[str]) -> None`
  - `copy_profile(ssid, src_iface, dst_iface) -> None`

- [ ] **Step 1: Write the failing tests** in `tests/test_wifi_actions.py`.

```python
import pathlib, xml.etree.ElementTree as ET
import pytest
from tests.conftest import fixture
import wifi
from winrun import CmdError

NS = {"w": "http://www.microsoft.com/networking/WLAN/profile/v1"}


class FakeNetsh:
    """Records every argv; answers 'show interfaces' from a queue of texts."""
    def __init__(self, iface_texts=()):
        self.calls, self.iface_texts, self.files_seen = [], list(iface_texts), []

    def __call__(self, args, **kw):
        self.calls.append(args)
        if args[:4] == ["netsh", "wlan", "show", "interfaces"]:
            return self.iface_texts.pop(0) if len(self.iface_texts) > 1 else self.iface_texts[0]
        for a in args:
            if a.startswith("filename="):
                p = pathlib.Path(a[len("filename="):])
                self.files_seen.append((p, p.exists(), p.read_text(encoding="utf-8") if p.exists() else None))
        return ""


def connected_text(ssid):
    return fixture("interfaces.txt").replace("State                  : disconnected", f"State                  : connected\n    SSID                   : {ssid}")


def test_adapter_keys():
    assert wifi.adapter_key("AIC8800D80 USB WiFi") == "unigen"
    assert wifi.adapter_key("MediaTek Wi-Fi 6 MT7921 Wireless LAN Card") == "builtin"
    assert wifi.adapter_key("Intel Wi-Fi 6 AX201") == "Intel Wi-Fi 6 AX201"


def test_security_kinds():
    assert wifi.security_kind("WPA2-Personal") == "wpa2"
    assert wifi.security_kind("Open") == "open"
    assert wifi.security_kind("WPA3-Personal") is None and wifi.security_kind("WPA2-Enterprise") is None


@pytest.mark.parametrize("pw, ok", [("short", False), ("12345678", True), ("x" * 63, True), ("x" * 64, False),
                                    ("A" * 64, True), ("ünïcödé-pass", False)])
def test_password_rules(pw, ok):
    if ok:
        wifi.check_password(pw)
    else:
        with pytest.raises(wifi.WifiError, match="8 to 63 characters"):
            wifi.check_password(pw)


def test_profile_xml_escapes_and_hex():
    ssid = 'Cafe & "Bar" <5G>'
    xml = wifi.profile_xml(ssid, "wpa2", 'p<a>&ss"word', wifi.profile_name(ssid))
    root = ET.fromstring(xml)  # must be well-formed
    assert root.find("w:SSIDConfig/w:SSID/w:hex", NS).text == ssid.encode("utf-8").hex().upper()
    assert root.find("w:SSIDConfig/w:SSID/w:name", NS).text == ssid
    assert root.find("w:MSM/w:security/w:sharedKey/w:keyMaterial", NS).text == 'p<a>&ss"word'
    assert root.find("w:MSM/w:security/w:authEncryption/w:authentication", NS).text == "WPA2PSK"


def test_open_profile_has_no_key():
    root = ET.fromstring(wifi.profile_xml("Guest", "open", None, "Guest"))
    assert root.find("w:MSM/w:security/w:sharedKey", NS) is None
    assert root.find("w:MSM/w:security/w:authEncryption/w:encryption", NS).text == "none"


def test_profile_name_has_no_quotes():
    assert '"' not in wifi.profile_name('say "hi"')
    assert wifi.profile_name("HOME-5G") == "HOME-5G"


def test_connect_new_network_writes_temp_profile_then_deletes_it(monkeypatch):
    fake = FakeNetsh([connected_text("Maple House")])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.connect("Wi-Fi 2", "Maple House", auth="WPA2-Personal", password="12345678", sleep=lambda s: None)
    add = next(c for c in fake.calls if c[2] == "add")
    assert add[:4] == ["netsh", "wlan", "add", "profile"] and "interface=Wi-Fi 2" in add and "user=all" in add
    path, existed, text = fake.files_seen[0]
    assert existed and "12345678" in text
    assert not path.exists() and not path.parent.exists()  # password file gone
    assert ["netsh", "wlan", "connect", "name=Maple House", "interface=Wi-Fi 2"] in fake.calls


def test_connect_saved_network_skips_profile(monkeypatch):
    fake = FakeNetsh([connected_text("HOME-5G")])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.connect("Wi-Fi 2", "HOME-5G", saved=True, sleep=lambda s: None)
    assert not any(c[2] == "add" for c in fake.calls)


def test_connect_wrong_password_deletes_profile(monkeypatch):
    fake = FakeNetsh([fixture("interfaces.txt")])  # never connects
    monkeypatch.setattr(wifi, "_run", fake)
    t = iter(range(0, 100))
    with pytest.raises(wifi.WifiError, match="Couldn't connect to Maple House. Check the password."):
        wifi.connect("Wi-Fi 2", "Maple House", auth="WPA2-Personal", password="wrongpass",
                     timeout=15, clock=lambda: next(t), sleep=lambda s: None)
    assert ["netsh", "wlan", "delete", "profile", "name=Maple House", "interface=Wi-Fi 2"] in fake.calls


def test_connect_rejects_unsupported_security_before_running_anything(monkeypatch):
    fake = FakeNetsh([fixture("interfaces.txt")])
    monkeypatch.setattr(wifi, "_run", fake)
    with pytest.raises(wifi.WifiError, match="WPA3-Personal.*Windows settings"):
        wifi.connect("Wi-Fi 2", "Lab", auth="WPA3-Personal", password="12345678")
    assert fake.calls == []


def test_hostile_ssid_stays_one_argument(monkeypatch):
    fake = FakeNetsh([connected_text('x" & del C:\\ "')])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.connect("Wi-Fi 2", 'x" & del C:\\ "', auth="Open", sleep=lambda s: None)
    connect = next(c for c in fake.calls if c[2] == "connect")
    assert connect[3] == "name=" + wifi.profile_name('x" & del C:\\ "') and len(connect) == 5


def test_disconnect_password_delete_copy(monkeypatch):
    fake = FakeNetsh(["x"])
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.disconnect("Wi-Fi 2")
    assert fake.calls[-1] == ["netsh", "wlan", "disconnect", "interface=Wi-Fi 2"]
    monkeypatch.setattr(wifi, "_run", lambda a, **k: fixture("profile_key.txt"))
    assert wifi.password("Wi-Fi 2", "HOME-5G") == "REDACTED-PASS"
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.delete_profile("oldrouter", ["Wi-Fi", "Wi-Fi 2"])
    assert fake.calls[-2:] == [["netsh", "wlan", "delete", "profile", "name=oldrouter", "interface=Wi-Fi"],
                               ["netsh", "wlan", "delete", "profile", "name=oldrouter", "interface=Wi-Fi 2"]]


def test_copy_profile_exports_to_temp_and_imports(monkeypatch):
    calls = []
    def fake(args, **kw):
        calls.append(args)
        if args[2] == "export":
            folder = pathlib.Path(next(a for a in args if a.startswith("folder="))[7:])
            (folder / "Wi-Fi 2-Maple House.xml").write_text("<WLANProfile/>", encoding="utf-8")
        if args[2] == "add":
            p = pathlib.Path(next(a for a in args if a.startswith("filename="))[9:])
            assert p.exists()
            calls.append(("folder", p.parent))
        return ""
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.copy_profile("Maple House", "Wi-Fi 2", "Wi-Fi")
    assert calls[0][:4] == ["netsh", "wlan", "export", "profile"] and "key=clear" in calls[0]
    assert "interface=Wi-Fi" in calls[1]
    assert not calls[2][1].exists()  # exported file with the clear key is gone


def test_delete_ignores_adapter_without_profile(monkeypatch):
    def fake(args, **kw):
        if "interface=Wi-Fi" in args:
            raise CmdError('Profile "oldrouter" is not found on interface "Wi-Fi".')
        return ""
    monkeypatch.setattr(wifi, "_run", fake)
    wifi.delete_profile("oldrouter", ["Wi-Fi", "Wi-Fi 2"])  # no exception
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_wifi_actions.py`.
Expected: FAIL with `AttributeError: module 'wifi' has no attribute 'adapter_key'`.

- [ ] **Step 3: Implement by appending to `wifi.py`**

```python
import pathlib, tempfile, time
from xml.sax.saxutils import escape

import winrun

_run = winrun.run  # tests replace this
NETSH = "netsh"
ADAPTER_NAMES = {"unigen": "Unigen dongle", "builtin": "Built-in MediaTek"}


def adapter_key(description):
    if "AIC8800" in description:
        return "unigen"
    if "MT7921" in description:
        return "builtin"
    return description


def security_kind(auth):
    return {"Open": "open", "WPA2-Personal": "wpa2"}.get(auth)


def check_password(pw):
    if re.fullmatch(r"[0-9A-Fa-f]{64}", pw or "") or (pw and 8 <= len(pw) <= 63 and all(32 <= ord(c) <= 126 for c in pw)):
        return
    raise WifiError("The password must be 8 to 63 characters.")


def profile_name(ssid):
    return ssid.replace('"', "'")  # netsh can't take a quote inside name=


def profile_xml(ssid, kind, password, name):
    if kind == "open":
        security = ("<authEncryption><authentication>open</authentication><encryption>none</encryption>"
                    "<useOneX>false</useOneX></authEncryption>")
    else:
        security = ("<authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption>"
                    "<useOneX>false</useOneX></authEncryption>"
                    "<sharedKey><keyType>passPhrase</keyType><protected>false</protected>"
                    f"<keyMaterial>{escape(password)}</keyMaterial></sharedKey>")
    return ('<?xml version="1.0"?>\n'
            '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
            f"<name>{escape(name)}</name>"
            f"<SSIDConfig><SSID><hex>{ssid.encode('utf-8').hex().upper()}</hex><name>{escape(ssid)}</name></SSID></SSIDConfig>"
            "<connectionType>ESS</connectionType><connectionMode>auto</connectionMode>"
            f"<MSM><security>{security}</security></MSM></WLANProfile>")


def interfaces():
    return parse_interfaces(_run([NETSH, "wlan", "show", "interfaces"]))


def networks(iface):
    return parse_networks(_run([NETSH, "wlan", "show", "networks", "mode=bssid", f"interface={iface}"]))


def profiles():
    return parse_profiles(_run([NETSH, "wlan", "show", "profiles"]))


def drivers():
    return parse_drivers(_run([NETSH, "wlan", "show", "drivers"]))


def trigger_scan(guid):
    """Ask the adapter for a fresh scan (netsh only shows Windows' cached list)."""
    import ctypes, uuid
    from ctypes import wintypes
    wlan = ctypes.WinDLL("wlanapi")
    handle, version = wintypes.HANDLE(), wintypes.DWORD()
    if wlan.WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(handle)):
        raise WifiError("Couldn't start a Wi-Fi scan.")
    try:
        g = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
        rc = wlan.WlanScan(handle, ctypes.byref(g), None, None, None)
        if rc:
            raise WifiError(f"Couldn't start a Wi-Fi scan (error {rc}).")
    finally:
        wlan.WlanCloseHandle(handle, None)


def scan(iface, guid, *, wait=4.0, sleep=time.sleep):
    trigger_scan(guid)
    sleep(wait)  # results arrive asynchronously; then show whatever netsh has
    return networks(iface)


def _state(iface):
    return next((i for i in interfaces() if i["name"] == iface), {})


def connect(iface, ssid, *, auth=None, password=None, saved=False, timeout=15.0, clock=time.monotonic, sleep=time.sleep):
    name, created = profile_name(ssid), False
    if not saved:
        kind = security_kind(auth)
        if kind is None:
            raise WifiError(f"{ssid} uses {auth}, which this app can't set up yet. Use Windows settings.")
        if kind != "open":
            check_password(password)
        with tempfile.TemporaryDirectory() as d:  # the password file never outlives this block
            path = pathlib.Path(d, "profile.xml")
            path.write_text(profile_xml(ssid, kind, password, name), encoding="utf-8")
            _run([NETSH, "wlan", "add", "profile", f"filename={path}", f"interface={iface}", "user=all"])
        created = True
    _run([NETSH, "wlan", "connect", f"name={name}", f"interface={iface}"])
    deadline = clock() + timeout
    while clock() < deadline:
        st = _state(iface)
        if st.get("state") == "connected" and st.get("ssid") == ssid:
            return st
        sleep(1)
    if created:
        try:
            _run([NETSH, "wlan", "delete", "profile", f"name={name}", f"interface={iface}"])
        except winrun.CmdError:
            pass
    raise WifiError(f"Couldn't connect to {ssid}. Check the password.")


def disconnect(iface):
    _run([NETSH, "wlan", "disconnect", f"interface={iface}"])


def password(iface, ssid):
    return parse_key(_run([NETSH, "wlan", "show", "profile", f"name={ssid}", f"interface={iface}", "key=clear"]))


def delete_profile(ssid, ifaces):
    for iface in ifaces:
        try:
            _run([NETSH, "wlan", "delete", "profile", f"name={ssid}", f"interface={iface}"])
        except winrun.CmdError:
            pass  # not saved on this adapter


def copy_profile(ssid, src_iface, dst_iface):
    with tempfile.TemporaryDirectory() as d:  # the exported file holds the clear key
        _run([NETSH, "wlan", "export", "profile", f"name={ssid}", f"interface={src_iface}", f"folder={d}", "key=clear"])
        files = list(pathlib.Path(d).glob("*.xml"))
        if len(files) != 1:
            raise WifiError(f"Couldn't export {ssid} from the {src_iface} adapter.")
        _run([NETSH, "wlan", "add", "profile", f"filename={files[0]}", f"interface={dst_iface}", "user=all"])
```

Move the new `import` lines to the top of `wifi.py`, next to `import re`.

- [ ] **Step 4: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/test_wifi_actions.py tests/test_wifi_parse.py`.
Expected: `28 passed` (19 action tests, with the password test parametrized 6 ways, plus 9 parser tests).

- [ ] **Step 5: Commit**

```bash
git add wifi.py tests/test_wifi_actions.py
git commit -m "feat(wifi): connect/disconnect/scan/saved-profile actions with safe temp profiles"
```

---

### Task 5: Speed test (sampled, per adapter)

**Files:**
- Create: `speed.py`
- Test: `tests/test_speed.py`

**Interfaces:**
- Consumes: `winrun.run`, `winrun.ps`, `winrun.CmdError`.
- Produces (in `speed.py`):
  - `class SpeedError(Exception)`
  - `addresses(alias) -> {"ip": str, "gateway": str}`
  - `parse_ping(text) -> int` (average ms)
  - `ping(ip, gateway, count=10) -> int`
  - `download_samples(ip, *, host, port, tls, path, rounds=3, interval=0.2, max_samples=28, on_sample=None, clock=time.monotonic) -> list[float]` (Mbps per sample)
  - `upload_samples(ip, *, host, port, tls, path, size=25_000_000, interval=0.2, max_samples=12, on_sample=None, clock=time.monotonic) -> list[float]`
  - `average(samples, skip=3) -> int`
  - `run_test(ip, gateway, *, on_sample=None, server=CLOUDFLARE) -> {"ping", "down", "up", "samples", "split", "at"}`
  - `load_results(path) -> dict` and `save_result(path, key, result) -> None`
  - `CLOUDFLARE = {"host": "speed.cloudflare.com", "port": 443, "tls": True, "down": "/__down?bytes=25000000", "up": "/__up"}`

- [ ] **Step 1: Write the failing tests** in `tests/test_speed.py`.

```python
import http.server, json, threading
import pytest
import speed

PING_EN = """
Pinging 192.168.0.1 from 192.168.0.111 with 32 bytes of data:
Reply from 192.168.0.1: bytes=32 time=1ms TTL=64
Reply from 192.168.0.1: bytes=32 time=16ms TTL=64

Ping statistics for 192.168.0.1:
    Packets: Sent = 10, Received = 10, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 1ms, Maximum = 16ms, Average = 2ms
"""


class Handler(http.server.BaseHTTPRequestHandler):
    received = 0

    def do_GET(self):
        n = 3_000_000
        self.send_response(200)
        self.send_header("Content-Length", str(n))
        self.end_headers()
        left = n
        while left:
            k = min(65536, left)
            self.wfile.write(b"\0" * k)
            left -= k

    def do_POST(self):
        left = int(self.headers["Content-Length"])
        while left:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)
            Handler.received += len(chunk)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def local_server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"host": "127.0.0.1", "port": httpd.server_port, "tls": False, "down": "/down", "up": "/up"}
    httpd.shutdown()


def fast_clock():
    t = [0.0]
    def clock():
        t[0] += 0.05  # each read/send "takes" 50 ms, so samples come quickly
        return t[0]
    return clock


def test_parse_ping():
    assert speed.parse_ping(PING_EN) == 2
    with pytest.raises(speed.SpeedError, match="router didn't answer"):
        speed.parse_ping("Request timed out.\nRequest timed out.\n")


def test_download_samples_bound_to_adapter_ip(local_server):
    seen = []
    s = speed.download_samples("127.0.0.1", host=local_server["host"], port=local_server["port"], tls=False,
                               path=local_server["down"], rounds=1, on_sample=seen.append, clock=fast_clock())
    assert 1 <= len(s) <= 28 and all(v > 0 for v in s)
    assert seen == s


def test_download_stops_at_max_samples(local_server):
    s = speed.download_samples("127.0.0.1", host=local_server["host"], port=local_server["port"], tls=False,
                               path=local_server["down"], rounds=3, max_samples=5, clock=fast_clock())
    assert len(s) == 5


def test_upload_samples(local_server):
    Handler.received = 0
    s = speed.upload_samples("127.0.0.1", host=local_server["host"], port=local_server["port"], tls=False,
                             path=local_server["up"], size=2_000_000, clock=fast_clock())
    assert s and all(v > 0 for v in s)
    assert Handler.received == 2_000_000


def test_average_skips_ramp_up():
    assert speed.average([1, 2, 3, 50, 52, 48]) == 50
    assert speed.average([]) == 0
    assert speed.average([10, 20]) == 15  # too short to skip


def test_results_round_trip_and_corrupt_file(tmp_path):
    f = tmp_path / "results.json"
    assert speed.load_results(f) == {}
    speed.save_result(f, "unigen", {"down": 50})
    speed.save_result(f, "builtin", {"down": 53})
    assert speed.load_results(f) == {"unigen": {"down": 50}, "builtin": {"down": 53}}
    f.write_text("{not json", encoding="utf-8")
    assert speed.load_results(f) == {}


def test_addresses_passes_alias_as_param(monkeypatch):
    seen = {}
    def fake_ps(script, params, **kw):
        seen.update(script=script, params=params)
        return '{"ip":"192.168.0.111","gateway":"192.168.0.1"}'
    monkeypatch.setattr(speed, "_ps", fake_ps)
    assert speed.addresses("Wi-Fi 2") == {"ip": "192.168.0.111", "gateway": "192.168.0.1"}
    assert seen["params"] == {"alias": "Wi-Fi 2"} and "Wi-Fi 2" not in seen["script"]


def test_addresses_without_ip(monkeypatch):
    monkeypatch.setattr(speed, "_ps", lambda s, p, **k: '{"ip":null,"gateway":null}')
    with pytest.raises(speed.SpeedError, match="isn't connected"):
        speed.addresses("Wi-Fi 2")
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_speed.py`.
Expected: FAIL with `ModuleNotFoundError: No module named 'speed'`.

- [ ] **Step 3: Implement `speed.py`**

```python
"""Speed test bound to one adapter: ping the router, then sampled download and upload."""
import http.client, json, os, re, ssl, tempfile, time
from pathlib import Path

import winrun

_run, _ps = winrun.run, winrun.ps  # tests replace these
CLOUDFLARE = {"host": "speed.cloudflare.com", "port": 443, "tls": True, "down": "/__down?bytes=25000000", "up": "/__up"}
_ADDR_SCRIPT = """
$c = Get-NetIPConfiguration -InterfaceAlias $p.alias
@{ ip = ($c.IPv4Address | Select-Object -First 1).IPAddress; gateway = ($c.IPv4DefaultGateway | Select-Object -First 1).NextHop } | ConvertTo-Json -Compress
"""


class SpeedError(Exception):
    pass


def addresses(alias):
    a = json.loads(_ps(_ADDR_SCRIPT, {"alias": alias}))
    if not a.get("ip") or not a.get("gateway"):
        raise SpeedError("That adapter isn't connected to a network.")
    return a


def parse_ping(text):
    m = re.search(r"Average = (\d+)ms", text)
    if not m:
        raise SpeedError("The router didn't answer pings.")
    return int(m.group(1))


def ping(ip, gateway, count=10):
    try:
        out = _run(["ping", "-n", str(count), "-S", ip, gateway], timeout=count * 2 + 5)
    except winrun.CmdError:
        raise SpeedError("The router didn't answer pings.") from None
    return parse_ping(out)


def _conn(ip, host, port, tls):
    if tls:
        return http.client.HTTPSConnection(host, port, timeout=15, source_address=(ip, 0), context=ssl.create_default_context())
    return http.client.HTTPConnection(host, port, timeout=15, source_address=(ip, 0))


class _Sampler:
    """Turns byte counts into one Mbps sample per interval."""
    def __init__(self, interval, max_samples, on_sample, clock):
        self.interval, self.max, self.on, self.clock = interval, max_samples, on_sample, clock
        self.samples, self.bytes, self.t0 = [], 0, clock()

    def add(self, n):
        self.bytes += n
        now = self.clock()
        if now - self.t0 >= self.interval:
            self.samples.append(round(self.bytes * 8 / (now - self.t0) / 1e6, 1))
            self.bytes, self.t0 = 0, now
            if self.on:
                self.on(self.samples[-1])
        return len(self.samples) >= self.max


def download_samples(ip, *, host, port, tls, path, rounds=3, interval=0.2, max_samples=28, on_sample=None, clock=time.monotonic):
    s = _Sampler(interval, max_samples, on_sample, clock)
    for _ in range(rounds):
        c = _conn(ip, host, port, tls)
        try:
            c.request("GET", path)
            r = c.getresponse()
            if r.status != 200:
                raise SpeedError(f"The speed server answered {r.status}.")
            while chunk := r.read(65536):
                if s.add(len(chunk)):
                    return s.samples
        except OSError as e:
            raise SpeedError(f"The download stopped: {e.strerror or e}.") from None
        finally:
            c.close()
    return s.samples


def upload_samples(ip, *, host, port, tls, path, size=25_000_000, interval=0.2, max_samples=12, on_sample=None, clock=time.monotonic):
    s, block, sent = _Sampler(interval, max_samples, on_sample, clock), b"\0" * 65536, 0
    c = _conn(ip, host, port, tls)
    try:
        c.putrequest("POST", path)
        c.putheader("Content-Type", "application/octet-stream")
        c.putheader("Content-Length", str(size))
        c.endheaders()
        while sent < size:
            n = min(len(block), size - sent)
            c.send(block[:n])
            sent += n
            if s.add(n):
                break
        if sent == size:
            c.getresponse().read()
    except OSError as e:
        raise SpeedError(f"The upload stopped: {e.strerror or e}.") from None
    finally:
        c.close()
    return s.samples


def average(samples, skip=3):
    xs = samples[skip:] if len(samples) > skip else samples
    return round(sum(xs) / len(xs)) if xs else 0


def run_test(ip, gateway, *, on_sample=None, server=CLOUDFLARE):
    on = on_sample or (lambda phase, v: None)
    ping_ms = ping(ip, gateway)
    common = {"host": server["host"], "port": server["port"], "tls": server["tls"]}
    down = download_samples(ip, path=server["down"], on_sample=lambda v: on("down", v), **common)
    up = upload_samples(ip, path=server["up"], on_sample=lambda v: on("up", v), **common)
    return {"ping": ping_ms, "down": average(down), "up": average(up), "samples": down + up,
            "split": len(down), "at": time.strftime("%Y-%m-%d %H:%M")}


def load_results(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_result(path, key, result):
    path = Path(path)
    data = load_results(path)
    data[key] = result
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")  # write-then-replace: never a half file
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
```

- [ ] **Step 4: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/test_speed.py`.
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add speed.py tests/test_speed.py
git commit -m "feat(speed): per-adapter sampled download/upload, ping, results file"
```

### Task 6: Bluetooth (radios, devices, switch with rollback, audio connect)

**Files:**
- Create: `bt.ps1`, `bt.py`
- Test: `tests/test_bt.py`

**Interfaces:**
- Consumes: `winrun.ps`, `winrun.CmdError`; `wifi.ADAPTER_NAMES`; the Task 1 decision (`SERVICE_TOGGLE`).
- Produces (in `bt.py`):
  - `class BtError(Exception)`
  - `SERVICE_TOGGLE: bool`
  - `version(lmp:int) -> str | None`, `kind(major:int, minor:int) -> str`, `radio_key(instance_id, name) -> str`
  - `radios() -> list[{"key", "id", "name", "ok": bool, "disabled": bool, "version"}]`
  - `switch(target_key, *, wait=10.0, clock=time.monotonic, sleep=time.sleep) -> str`: returns the active key
  - `devices(paired: bool) -> list[{"id", "name", "connected": bool, "kind", "address"}]`
  - `pair(device_id) -> None` and `remove(device_id) -> None`
  - `connect(address_hex, name, *, open_settings=os.startfile) -> None` and `disconnect(address_hex, name, *, open_settings=os.startfile) -> None`
  - `BLUETOOTH_DEVICE_INFO`: the ctypes structure; `ctypes.sizeof` is 560 on 64-bit Python

- [ ] **Step 1: Write the failing tests** in `tests/test_bt.py`.

```python
import ctypes, json
import pytest
import bt
from winrun import CmdError

RADIOS_OK_UNIGEN = [
    {"id": "USB\\VID_368B&PID_8D81&MI_00\\6&28B24B5D&0&0000", "name": "Generic Bluetooth Adapter", "status": "OK", "problem": "CM_PROB_NONE", "lmp": 13},
    {"id": "USB\\VID_13D3&PID_3563&MI_00\\6&1D754FA2&0&0000", "name": "MediaTek Bluetooth Adapter", "status": "Error", "problem": "CM_PROB_DISABLED", "lmp": 11},
]


class FakePs:
    """Answers bt.ps1 actions; radio states follow a script of 'radios' answers."""
    def __init__(self, radio_states, answers=None):
        self.calls, self.states, self.answers = [], list(radio_states), answers or {}

    def __call__(self, script, params, **kw):
        assert "$p.action" in script  # the fixed bt.ps1 text, never built from inputs
        self.calls.append(params)
        a = params["action"]
        if a == "radios":
            return json.dumps(self.states.pop(0) if len(self.states) > 1 else self.states[0])
        return json.dumps(self.answers.get(a, {"ok": True}))


def flipped(unigen_ok, builtin_ok):
    a, b = (dict(r) for r in RADIOS_OK_UNIGEN)
    a["status"], a["problem"] = ("OK", "CM_PROB_NONE") if unigen_ok else ("Error", "CM_PROB_DISABLED")
    b["status"], b["problem"] = ("OK", "CM_PROB_NONE") if builtin_ok else ("Error", "CM_PROB_DISABLED")
    return [a, b]


def test_versions_and_kinds():
    assert bt.version(13) == "5.4" and bt.version(11) == "5.2" and bt.version(9) == "5.0" and bt.version(3) is None
    assert bt.kind(4, 5) == "Speaker" and bt.kind(4, 6) == "Headphones" and bt.kind(4, 0) == "Audio"
    assert bt.kind(5, 2) == "Controller" and bt.kind(2, 3) == "Phone" and bt.kind(0, 0) == "Device"


def test_radios_keys_and_state(monkeypatch):
    monkeypatch.setattr(bt, "_ps", FakePs([RADIOS_OK_UNIGEN]))
    uni, bi = bt.radios()
    assert (uni["key"], uni["ok"], uni["version"]) == ("unigen", True, "5.4")
    assert (bi["key"], bi["ok"], bi["disabled"], bi["version"]) == ("builtin", False, True, "5.2")


def test_switch_success_disables_current_then_enables_target(monkeypatch):
    fake = FakePs([RADIOS_OK_UNIGEN, flipped(False, False), flipped(False, True)])
    monkeypatch.setattr(bt, "_ps", fake)
    assert bt.switch("builtin", sleep=lambda s: None) == "builtin"
    acts = [(c["action"], c.get("id", "")[:21]) for c in fake.calls if c["action"] != "radios"]
    assert acts == [("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563")]


def test_switch_rolls_back_when_target_never_starts(monkeypatch):
    fake = FakePs([RADIOS_OK_UNIGEN, flipped(False, False)])
    monkeypatch.setattr(bt, "_ps", fake)
    t = iter(range(100))
    with pytest.raises(bt.BtError, match="Built-in MediaTek radio didn't start. Switched back to the Unigen dongle."):
        bt.switch("builtin", wait=10, clock=lambda: next(t), sleep=lambda s: None)
    acts = [(c["action"], c["id"][:21]) for c in fake.calls if c["action"] != "radios"]
    assert acts == [("disable", "USB\\VID_368B&PID_8D81"), ("enable", "USB\\VID_13D3&PID_3563"),
                    ("disable", "USB\\VID_13D3&PID_3563"), ("enable", "USB\\VID_368B&PID_8D81")]


def test_switch_to_missing_radio(monkeypatch):
    monkeypatch.setattr(bt, "_ps", FakePs([RADIOS_OK_UNIGEN[:1]]))
    with pytest.raises(bt.BtError, match="isn't connected to this PC"):
        bt.switch("builtin")


def test_devices_map_kind_and_keep_ids_as_params(monkeypatch):
    devs = [{"id": "Bluetooth#Bluetooth02:00:00:00:00:10-11:22:33:44:55:66", "name": "JBL Go 3", "connected": False, "major": 4, "minor": 5, "address": "112233445566"}]
    fake = FakePs([RADIOS_OK_UNIGEN], {"paired": devs})
    monkeypatch.setattr(bt, "_ps", fake)
    assert bt.devices(paired=True) == [{"id": devs[0]["id"], "name": "JBL Go 3", "connected": False, "kind": "Speaker", "address": "112233445566"}]
    assert fake.calls[-1] == {"action": "paired"}


@pytest.mark.parametrize("status, ok", [("Paired", True), ("AlreadyPaired", True), ("AuthenticationTimeout", False), ("Failed", False)])
def test_pair_statuses(monkeypatch, status, ok):
    fake = FakePs([RADIOS_OK_UNIGEN], {"pair": {"status": status}})
    monkeypatch.setattr(bt, "_ps", fake)
    if ok:
        bt.pair('Bluetooth#x"; rm -rf')
        assert fake.calls[-1] == {"action": "pair", "id": 'Bluetooth#x"; rm -rf'}
    else:
        with pytest.raises(bt.BtError):
            bt.pair("Bluetooth#x")


def test_remove(monkeypatch):
    monkeypatch.setattr(bt, "_ps", FakePs([RADIOS_OK_UNIGEN], {"unpair": {"status": "Unpaired"}}))
    bt.remove("Bluetooth#x")


def test_device_info_struct_size():
    assert ctypes.sizeof(bt.BLUETOOTH_DEVICE_INFO) == 560


def test_connect_falls_back_to_settings(monkeypatch):
    opened = []
    def boom(address, flags):
        raise bt.BtError("rc 87")
    monkeypatch.setattr(bt, "_set_audio", boom)
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", True)
    with pytest.raises(bt.BtError, match="Bluetooth settings are open"):
        bt.connect("112233445566", "JBL Go 3", open_settings=opened.append)
    assert opened == ["ms-settings:bluetooth"]


def test_connect_uses_service_toggle(monkeypatch):
    seen = []
    monkeypatch.setattr(bt, "_set_audio", lambda address, flags: seen.append((address, flags)))
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", True)
    bt.connect("112233445566", "JBL Go 3", open_settings=lambda u: pytest.fail("should not open settings"))
    bt.disconnect("112233445566", "JBL Go 3", open_settings=lambda u: pytest.fail("should not open settings"))
    assert seen == [("112233445566", [0, 1]), ("112233445566", [0])]


def test_connect_disabled_by_spike(monkeypatch):
    opened = []
    monkeypatch.setattr(bt, "SERVICE_TOGGLE", False)
    with pytest.raises(bt.BtError, match="Bluetooth settings are open"):
        bt.disconnect("112233445566", "JBL Go 3", open_settings=opened.append)
    assert opened == ["ms-settings:bluetooth"]
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_bt.py`.
Expected: FAIL with `ModuleNotFoundError: No module named 'bt'`.

- [ ] **Step 3: Write `bt.ps1`**

```powershell
# Bluetooth helper for Unigen Manager. bt.py runs this text through winrun.ps(); inputs arrive in $p (UM_ARGS JSON).
# $p.action: radios | enable | disable | paired | nearby | pair | unpair. Output: one JSON document.

function Radios {
  $out = @(foreach ($d in Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match '^(USB|PCI)\\' }) {
    $lmp = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName DEVPKEY_Bluetooth_RadioLmpVersion -ErrorAction SilentlyContinue).Data
    if ($null -eq $lmp) { continue }  # not a radio (e.g. a USB composite child)
    [pscustomobject]@{ id = $d.InstanceId; name = $d.FriendlyName; status = "$($d.Status)"; problem = "$($d.Problem)"; lmp = [int]$lmp }
  })
  ConvertTo-Json -InputObject $out -Compress
}

function Winrt {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $script:asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  $null = [Windows.Devices.Enumeration.DeviceInformation, Windows.Devices.Enumeration, ContentType = WindowsRuntime]
  $null = [Windows.Devices.Bluetooth.BluetoothDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
}

function Await($op, [Type]$type) {
  $t = $script:asTask.MakeGenericMethod($type).Invoke($null, @($op))
  $null = $t.Wait(-1)
  $t.Result
}

function List([bool]$paired) {
  Winrt
  $sel = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($paired)
  $all = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($sel)) ([Windows.Devices.Enumeration.DeviceInformationCollection])
  $out = @(foreach ($di in $all) {
    $dev = $null
    try { $dev = Await ([Windows.Devices.Bluetooth.BluetoothDevice]::FromIdAsync($di.Id)) ([Windows.Devices.Bluetooth.BluetoothDevice]) } catch { }
    [pscustomobject]@{
      id        = $di.Id
      name      = $di.Name
      connected = [bool]($dev -and "$($dev.ConnectionStatus)" -eq 'Connected')
      major     = if ($dev) { [int]$dev.ClassOfDevice.MajorClass } else { 0 }
      minor     = if ($dev) { [int]$dev.ClassOfDevice.MinorClass } else { 0 }
      address   = if ($dev) { '{0:X12}' -f $dev.BluetoothAddress } else { '' }
    }
  })
  ConvertTo-Json -InputObject $out -Compress
}

function Pairing([string]$action) {
  Winrt
  $di = Await ([Windows.Devices.Enumeration.DeviceInformation]::CreateFromIdAsync($p.id)) ([Windows.Devices.Enumeration.DeviceInformation])
  if ($action -eq 'pair') { $r = Await ($di.Pairing.PairAsync()) ([Windows.Devices.Enumeration.DevicePairingResult]) }
  else { $r = Await ($di.Pairing.UnpairAsync()) ([Windows.Devices.Enumeration.DeviceUnpairingResult]) }
  @{ status = "$($r.Status)" } | ConvertTo-Json -Compress
}

switch ($p.action) {
  'radios'  { Radios }
  'enable'  { Enable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  'disable' { Disable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  'paired'  { List $true }
  'nearby'  { List $false }
  'pair'    { Pairing 'pair' }
  'unpair'  { Pairing 'unpair' }
  default   { throw "Unknown action: $($p.action)" }
}
```

- [ ] **Step 4: Implement `bt.py`.** Set `SERVICE_TOGGLE` to the value recorded in Task 1.

```python
"""Bluetooth: radios (switch with rollback), devices (list, pair, remove), audio connect/disconnect."""
import ctypes, json, os, time, uuid
from ctypes import wintypes
from pathlib import Path

import winrun
from wifi import ADAPTER_NAMES

_ps = winrun.ps  # tests replace this
SERVICE_TOGGLE = True  # Task 1 spike result. False = Connect/Disconnect always open Windows Bluetooth settings.
_SCRIPT = Path(__file__).with_name("bt.ps1")
LMP = {6: "4.0", 7: "4.1", 8: "4.2", 9: "5.0", 10: "5.1", 11: "5.2", 12: "5.3", 13: "5.4", 14: "6.0"}
AUDIO_SERVICES = ["0000110B-0000-1000-8000-00805F9B34FB", "0000111E-0000-1000-8000-00805F9B34FB"]  # A2DP sink, Hands-free
_PAIR_ERRORS = {
    "AuthenticationTimeout": "The device didn't answer in time. Put it in pairing mode and try again.",
    "AuthenticationFailure": "Pairing failed. Check the code shown on the device.",
    "RejectedByHandler": "Pairing was cancelled.",
    "AccessDenied": "Windows didn't allow the pairing.",
}


class BtError(Exception):
    pass


def _call(action, **params):
    return json.loads(_ps(_SCRIPT.read_text(encoding="utf-8"), {"action": action, **params}, timeout=90))


def version(lmp):
    return LMP.get(lmp)


def kind(major, minor):
    if major == 4:
        return "Headphones" if minor in (1, 2, 6) else "Speaker" if minor in (5, 7) else "Audio"
    if major == 5:
        return "Controller" if minor in (1, 2) else "Input device"
    return {1: "Computer", 2: "Phone", 7: "Wearable"}.get(major, "Device")


def radio_key(instance_id, name):
    up = instance_id.upper()
    if "VID_368B&PID_8D81" in up:
        return "unigen"
    if "VID_13D3&PID_3563" in up or "MEDIATEK" in name.upper():
        return "builtin"
    return instance_id


def radios():
    return [{"key": radio_key(r["id"], r["name"]), "id": r["id"], "name": r["name"], "ok": r["status"] == "OK",
             "disabled": r["problem"] in ("CM_PROB_DISABLED", "22"), "version": version(r["lmp"])} for r in _call("radios")]


def _label(key):
    return ADAPTER_NAMES.get(key, key)


def switch(target, *, wait=10.0, clock=time.monotonic, sleep=time.sleep):
    rs = radios()
    tgt = next((r for r in rs if r["key"] == target), None)
    if tgt is None:
        raise BtError("That Bluetooth radio isn't connected to this PC.")
    others = [r for r in rs if r["ok"] and r["key"] != target]
    if tgt["ok"] and not others:
        return target
    for r in others:  # Windows runs one Bluetooth radio at a time
        _call("disable", id=r["id"])
    _call("enable", id=tgt["id"])
    deadline = clock() + wait
    while clock() < deadline:
        if any(r["key"] == target and r["ok"] for r in radios()):
            return target
        sleep(1)
    try:  # never leave the user without Bluetooth
        _call("disable", id=tgt["id"])
    except winrun.CmdError:
        pass
    for r in others:
        _call("enable", id=r["id"])
    back = f" Switched back to the {_label(others[0]['key'])}." if others else ""
    raise BtError(f"The {_label(target)} radio didn't start.{back}")


def devices(paired):
    return [{"id": d["id"], "name": d["name"], "connected": bool(d["connected"]), "kind": kind(d["major"], d["minor"]),
             "address": d["address"]} for d in _call("paired" if paired else "nearby")]


def pair(device_id):
    status = _call("pair", id=device_id)["status"]
    if status not in ("Paired", "AlreadyPaired"):
        raise BtError(_PAIR_ERRORS.get(status, f"Pairing failed ({status})."))


def remove(device_id):
    status = _call("unpair", id=device_id)["status"]
    if status not in ("Unpaired", "AlreadyUnpaired"):
        raise BtError(f"Couldn't remove the device ({status}).")


# ---- audio connect via bthprops.cpl (decided by the Task 1 spike) ----
class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in
                ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("Address", ctypes.c_ulonglong), ("ulClassofDevice", wintypes.ULONG),
                ("fConnected", wintypes.BOOL), ("fRemembered", wintypes.BOOL), ("fAuthenticated", wintypes.BOOL),
                ("stLastSeen", _SYSTEMTIME), ("stLastUsed", _SYSTEMTIME), ("szName", wintypes.WCHAR * 248)]


class _RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


def _set_audio(address_hex, flags):
    """Set the audio services of a paired device: [0, 1] makes Windows reconnect it, [0] disconnects it."""
    lib, k32 = ctypes.WinDLL("bthprops.cpl"), ctypes.WinDLL("kernel32")
    lib.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    radio, params = wintypes.HANDLE(), _RADIO_PARAMS(ctypes.sizeof(_RADIO_PARAMS))
    find = lib.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not find:
        raise BtError("No Bluetooth radio is on.")
    lib.BluetoothFindRadioClose(wintypes.HANDLE(find))
    try:
        info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO), Address=int(address_hex, 16))
        if lib.BluetoothGetDeviceInfo(radio, ctypes.byref(info)):
            raise BtError("Windows doesn't know that device.")
        for flag in flags:
            for g in AUDIO_SERVICES:
                guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(g).bytes_le)
                rc = lib.BluetoothSetServiceState(radio, ctypes.byref(info), ctypes.byref(guid), flag)
                if rc and rc != 1060:  # 1060 = the device doesn't offer this service (e.g. no hands-free)
                    raise BtError(f"Windows refused (error {rc}).")
    finally:
        k32.CloseHandle(radio)


def _toggle(address_hex, name, flags, verb, open_settings):
    if SERVICE_TOGGLE:
        try:
            _set_audio(address_hex, flags)
            return
        except (BtError, OSError, ValueError):
            pass
    open_settings("ms-settings:bluetooth")
    raise BtError(f"Windows didn't let the app {verb} {name}. Bluetooth settings are open so you can do it there.")


def connect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, [0, 1], "connect", open_settings)


def disconnect(address_hex, name, *, open_settings=os.startfile):
    _toggle(address_hex, name, [0], "disconnect", open_settings)
```

- [ ] **Step 5: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/test_bt.py`.
Expected: `15 passed` (12 tests, with the pair-status test parametrized 4 ways).

- [ ] **Step 6: Commit**

```bash
git add bt.ps1 bt.py tests/test_bt.py
git commit -m "feat(bt): radios with LMP versions, switch with rollback, pair/remove, audio connect"
```

---

### Task 7: The `Api` the page calls

**Files:**
- Create: `api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: everything in `wifi`, `bt` and `speed` listed above.
- Produces: `api.Api(*, admin: bool = False, results_path: Path = DATA_DIR / "results.json")`, with attribute `_window` (set by `app.py`) and these public methods. Each returns `{"ok": True, "data": …}` or `{"ok": False, "error": str}`:

| Method | `data` |
|---|---|
| `app_info()` | `{"admin": bool, "adapters": [{"key", "name", "wifi": "Wi-Fi 6", "bt": "5.4"}]}` |
| `adapters()` | `[{"key", "name", "state", "ssid", "signal", "rate", "channel", "band"}]` |
| `networks(key)` / `scan(key)` | `{"networks": [{"ssid", "sec", "auth", "state": "Connected"/"Saved"/"", "hidden": bool, "aps": [{"b", "ch", "s"}]}], "scanned_at": float}` |
| `connect(key, ssid, password=None)` | `{"ssid", "rate"}` |
| `disconnect(key)` | `None` |
| `saved()` | `[{"ssid", "on": ["unigen", "builtin"]}]` |
| `password(ssid)` | `str` or `None` |
| `copy_profile(ssid, src_key, dst_key)` / `delete_profile(ssid)` | `None` |
| `bt_radio()` | `{"active": key or None, "can_switch": bool, "radios": [{"key", "name", "ok", "disabled", "version"}]}` |
| `bt_switch(key)` | `{"active": key}` |
| `bt_paired()` / `bt_nearby()` | `[{"id", "name", "connected", "kind", "address"}]` |
| `bt_pair(id)` / `bt_remove(id)` / `bt_connect(id)` / `bt_disconnect(id)` | `None` |
| `speed_test(key)` | `{"ping", "down", "up", "samples", "split", "at", "link"}`. While it runs, it pushes `window.onSpeedSample({"phase": "down"/"up", "v": float})` |
| `speed_results()` | `{key: result}` |

- [ ] **Step 1: Write the failing tests** in `tests/test_api.py`.

```python
import json, pathlib, re, threading
import pytest
from tests.conftest import fixture, ROOT
import api, bt, speed, wifi


def raising(exc):
    def f(*a, **k):
        raise exc
    return f


@pytest.fixture
def hw(monkeypatch):
    """Fixture-backed adapters: built-in connected to HOME-5G, Unigen disconnected."""
    monkeypatch.setattr(wifi, "interfaces", lambda: wifi.parse_interfaces(fixture("interfaces.txt")))
    monkeypatch.setattr(wifi, "networks", lambda iface: wifi.parse_networks(fixture("networks.txt")))
    monkeypatch.setattr(wifi, "profiles", lambda: wifi.parse_profiles(fixture("profiles.txt")))
    monkeypatch.setattr(wifi, "drivers", lambda: wifi.parse_drivers(fixture("drivers.txt")))
    monkeypatch.setattr(bt, "radios", lambda: [
        {"key": "unigen", "id": "U", "name": "Generic Bluetooth Adapter", "ok": True, "disabled": False, "version": "5.4"},
        {"key": "builtin", "id": "M", "name": "MediaTek Bluetooth Adapter", "ok": False, "disabled": True, "version": "5.2"}])


def test_envelopes(hw, monkeypatch, caplog):
    a = api.Api()
    assert a.adapters()["ok"] is True
    monkeypatch.setattr(wifi, "interfaces", raising(wifi.ParseError("Couldn't read the Wi-Fi status. Is Windows set to English?")))
    assert a.adapters() == {"ok": False, "error": "Couldn't read the Wi-Fi status. Is Windows set to English?"}
    monkeypatch.setattr(wifi, "interfaces", raising(ZeroDivisionError("boom")))
    r = a.adapters()
    assert r == {"ok": False, "error": "Something went wrong. Details are in app.log."}
    assert "ZeroDivisionError" in caplog.text


def test_app_info_versions(hw):
    info = api.Api(admin=True).app_info()["data"]
    assert info["admin"] is True
    assert {a["key"]: (a["name"], a["wifi"], a["bt"]) for a in info["adapters"]} == {
        "unigen": ("Unigen dongle", "Wi-Fi 6", "5.4"), "builtin": ("Built-in MediaTek", "Wi-Fi 6", "5.2")}


def test_adapters_shape(hw):
    ads = {a["key"]: a for a in api.Api().adapters()["data"]}
    assert ads["builtin"] == {"key": "builtin", "name": "Built-in MediaTek", "state": "connected", "ssid": "HOME-5G",
                              "signal": 80, "rate": 867, "channel": 36, "band": 5}
    assert ads["unigen"]["state"] == "disconnected" and ads["unigen"]["ssid"] is None


def test_networks_states_order_and_hidden(hw):
    nets = api.Api().networks("builtin")["data"]["networks"]
    assert nets[0]["ssid"] == "HOME-5G" and nets[0]["state"] == "Connected"  # connected is pinned first
    by = {n["ssid"]: n for n in nets}
    assert by["Maple House"]["state"] == "" and by["Maple House"]["sec"] == "WPA2"
    assert by[""]["hidden"] is True and by[""]["sec"] == "Open"
    rest = [max(a["s"] for a in n["aps"]) for n in nets[1:]]
    assert rest == sorted(rest, reverse=True)
    uni = {n["ssid"]: n["state"] for n in api.Api().networks("unigen")["data"]["networks"]}
    assert uni["Maple House"] == "Saved" and uni["HOME-5G"] == "Saved"


def test_unplugged_adapter_message(hw, monkeypatch):
    monkeypatch.setattr(wifi, "interfaces", lambda: [i for i in wifi.parse_interfaces(fixture("interfaces.txt")) if i["name"] == "Wi-Fi"])
    assert api.Api().networks("unigen") == {"ok": False, "error": "The Unigen dongle isn't plugged in."}


def test_connect_new_network_uses_scanned_auth(hw, monkeypatch):
    seen = {}
    def fake_connect(iface, ssid, **kw):
        seen.update(kw, iface=iface, ssid=ssid)
        return {"rx": 144.0}
    monkeypatch.setattr(wifi, "connect", fake_connect)
    r = api.Api().connect("unigen", "AirFiber-Maple House", "12345678")
    assert r == {"ok": True, "data": {"ssid": "AirFiber-Maple House", "rate": 144}}
    assert seen == {"iface": "Wi-Fi 2", "ssid": "AirFiber-Maple House", "auth": "WPA2-Personal", "password": "12345678", "saved": False}
    api.Api().connect("unigen", "Maple House")
    assert seen["saved"] is True
    assert api.Api().connect("unigen", "Far Away", "12345678") == {"ok": False, "error": "Far Away is out of range."}


def test_saved_merge_password_copy_delete(hw, monkeypatch):
    a = api.Api()
    saved = {s["ssid"]: s["on"] for s in a.saved()["data"]}
    assert saved["HOME-5G"] == ["builtin", "unigen"] and saved["oldrouter"] == ["unigen"]
    monkeypatch.setattr(wifi, "password", lambda iface, ssid: f"{iface}:{ssid}")
    assert a.password("oldrouter")["data"] == "Wi-Fi 2:oldrouter"
    assert a.password("nope")["ok"] is False
    calls = []
    monkeypatch.setattr(wifi, "copy_profile", lambda *args: calls.append(("copy",) + args))
    monkeypatch.setattr(wifi, "delete_profile", lambda *args: calls.append(("delete",) + args))
    a.copy_profile("oldrouter", "unigen", "builtin")
    a.delete_profile("oldrouter")
    assert calls == [("copy", "oldrouter", "Wi-Fi 2", "Wi-Fi"), ("delete", "oldrouter", ["Wi-Fi 2"])]


def test_bt_switch_needs_admin(hw, monkeypatch):
    monkeypatch.setattr(bt, "switch", lambda key: key)
    assert api.Api(admin=False).bt_switch("builtin") == {"ok": False, "error": "Bluetooth radio switching needs administrator rights. Restart the app and choose Yes."}
    assert api.Api(admin=True).bt_switch("builtin") == {"ok": True, "data": {"active": "builtin"}}
    r = api.Api(admin=False).bt_radio()["data"]
    assert r["active"] == "unigen" and r["can_switch"] is False and r["radios"][1]["name"] == "Built-in MediaTek"


def test_bt_connect_looks_up_address(hw, monkeypatch):
    monkeypatch.setattr(bt, "devices", lambda paired: [{"id": "D1", "name": "JBL Go 3", "connected": False, "kind": "Speaker", "address": "112233445566"}])
    seen = []
    monkeypatch.setattr(bt, "connect", lambda address, name: seen.append((address, name)))
    assert api.Api().bt_connect("D1")["ok"] is True and seen == [("112233445566", "JBL Go 3")]
    assert api.Api().bt_connect("gone")["error"] == "That device isn't paired any more."


class FakeWindow:
    def __init__(self):
        self.scripts = []

    def evaluate_js(self, s):
        self.scripts.append(s)


def test_speed_test_pushes_samples_and_saves(hw, monkeypatch, tmp_path):
    monkeypatch.setattr(speed, "addresses", lambda alias: {"ip": "192.168.0.143", "gateway": "192.168.0.1"})
    def fake_run(ip, gw, on_sample):
        on_sample("down", 12.5)
        on_sample("up", 3.0)
        return {"ping": 2, "down": 50, "up": 12, "samples": [12.5, 3.0], "split": 1, "at": "2026-10-13 10:00"}
    monkeypatch.setattr(speed, "run_test", fake_run)
    a = api.Api(results_path=tmp_path / "r.json")
    a._window = FakeWindow()
    r = a.speed_test("builtin")["data"]
    assert r["link"] == 867 and r["down"] == 50
    assert a._window.scripts[0].endswith('window.onSpeedSample({"phase": "down", "v": 12.5})')
    assert a.speed_results()["data"]["builtin"]["down"] == 50


def test_only_one_speed_test_at_a_time(hw, tmp_path):
    a = api.Api(results_path=tmp_path / "r.json")
    a._speed_lock.acquire()
    assert a.speed_test("builtin") == {"ok": False, "error": "A speed test is already running."}


def test_mock_api_matches_python_api():
    js = (ROOT / "ui" / "mock-api.js").read_text(encoding="utf-8")
    mock = set(re.findall(r'def\("(\w+)"', js))
    real = {n for n in dir(api.Api) if not n.startswith("_") and callable(getattr(api.Api, n))}
    assert mock == real
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_api.py`.
Expected: FAIL with `ModuleNotFoundError: No module named 'api'`. `test_mock_api_matches_python_api` keeps failing until Task 8 creates `ui/mock-api.js`, which is expected.

- [ ] **Step 3: Implement `api.py`**

```python
"""What the page calls (window.pywebview.api). Every public method returns {"ok", "data"} or {"ok", "error"}.
pywebview runs each call on its own thread, so slow work never blocks the window."""
import functools, json, logging, os, threading, time
from pathlib import Path

import bt, speed, wifi, winrun

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "UnigenManager"
log = logging.getLogger("unigen")
_KNOWN = (wifi.WifiError, wifi.ParseError, bt.BtError, speed.SpeedError, winrun.CmdError)
_SEC = {"WPA2-Personal": "WPA2", "WPA3-Personal": "WPA3", "Open": "Open", "WPA-Personal": "WPA", "WPA2-Enterprise": "WPA2-Ent"}


def _envelope(fn):
    @functools.wraps(fn)
    def wrapper(self, *args):
        try:
            return {"ok": True, "data": fn(self, *args)}
        except _KNOWN as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            log.exception("%s failed", fn.__name__)  # traceback only: argument values (passwords) are never logged
            return {"ok": False, "error": "Something went wrong. Details are in app.log."}
    return wrapper


class Api:
    def __init__(self, *, admin=False, results_path=DATA_DIR / "results.json"):
        self._admin, self._results, self._window = admin, Path(results_path), None
        self._speed_lock = threading.Lock()

    # ---- helpers (underscore: pywebview does not expose these) ----
    def _ifaces(self):
        return {wifi.adapter_key(i["description"]): i for i in wifi.interfaces()}

    def _iface(self, key):
        i = self._ifaces().get(key)
        if i is None:
            raise wifi.WifiError(f"The {wifi.ADAPTER_NAMES.get(key, key)} isn't plugged in.")
        return i

    @staticmethod
    def _name(key, fallback):
        return wifi.ADAPTER_NAMES.get(key, fallback)

    def _shape(self, iface, nets):
        saved = set(wifi.profiles().get(iface["name"], []))
        current = iface.get("ssid") if iface.get("state") == "connected" else None
        out = []
        for n in nets:
            ssid = n["ssid"]
            state = "Connected" if ssid and ssid == current else "Saved" if ssid in saved or wifi.profile_name(ssid) in saved else ""
            out.append({"ssid": ssid, "sec": _SEC.get(n["auth"], n["auth"] or "?"), "auth": n["auth"], "state": state,
                        "hidden": not ssid, "aps": [{"b": a["band"], "ch": a["channel"], "s": a["signal"]}
                                                    for a in n["aps"] if "channel" in a and "signal" in a]})
        out.sort(key=lambda n: (n["state"] != "Connected", -max([a["s"] for a in n["aps"]] or [0])))
        return {"networks": out, "scanned_at": time.time()}

    def _device(self, dev_id):
        d = next((d for d in bt.devices(paired=True) if d["id"] == dev_id), None)
        if d is None:
            raise bt.BtError("That device isn't paired any more.")
        return d

    def _push_sample(self, phase, value):
        if self._window is not None:
            self._window.evaluate_js("window.onSpeedSample && window.onSpeedSample(" + json.dumps({"phase": phase, "v": value}) + ")")

    # ---- app ----
    @_envelope
    def app_info(self):
        ifs, drv = self._ifaces(), wifi.drivers()
        radios = {r["key"]: r for r in bt.radios()}
        return {"admin": self._admin, "adapters": [
            {"key": k, "name": self._name(k, i["description"]),
             "wifi": wifi.wifi_standard(drv.get(i["name"], {}).get("radio_types", [])),
             "bt": radios.get(k, {}).get("version")} for k, i in ifs.items()]}

    # ---- Wi-Fi ----
    @_envelope
    def adapters(self):
        return [{"key": k, "name": self._name(k, i["description"]), "state": i["state"], "ssid": i.get("ssid"),
                 "signal": i.get("signal"), "rate": round(i["rx"]) if "rx" in i else None, "channel": i.get("channel"),
                 "band": wifi.band(i["channel"]) if "channel" in i else None} for k, i in self._ifaces().items()]

    @_envelope
    def networks(self, key):
        i = self._iface(key)
        return self._shape(i, wifi.networks(i["name"]))

    @_envelope
    def scan(self, key):
        i = self._iface(key)
        return self._shape(i, wifi.scan(i["name"], i["guid"]))

    @_envelope
    def connect(self, key, ssid, password=None):
        i = self._iface(key)
        names = wifi.profiles().get(i["name"], [])
        saved = ssid in names or wifi.profile_name(ssid) in names
        auth = None
        if not saved:
            auth = next((n["auth"] for n in wifi.networks(i["name"]) if n["ssid"] == ssid), None)
            if auth is None:
                raise wifi.WifiError(f"{ssid} is out of range.")
        st = wifi.connect(i["name"], ssid, auth=auth, password=password, saved=saved)
        return {"ssid": ssid, "rate": round(st["rx"]) if "rx" in st else None}

    @_envelope
    def disconnect(self, key):
        wifi.disconnect(self._iface(key)["name"])

    @_envelope
    def saved(self):
        by_name = {i["name"]: k for k, i in self._ifaces().items()}
        out = {}
        for iname, names in wifi.profiles().items():
            if iname in by_name:
                for n in names:
                    out.setdefault(n, []).append(by_name[iname])
        return [{"ssid": s, "on": on} for s, on in out.items()]

    @_envelope
    def password(self, ssid):
        prof = wifi.profiles()
        for i in self._ifaces().values():
            if ssid in prof.get(i["name"], []):
                return wifi.password(i["name"], ssid)
        raise wifi.WifiError(f"{ssid} isn't saved on this PC.")

    @_envelope
    def copy_profile(self, ssid, src, dst):
        wifi.copy_profile(ssid, self._iface(src)["name"], self._iface(dst)["name"])

    @_envelope
    def delete_profile(self, ssid):
        prof = wifi.profiles()
        wifi.delete_profile(ssid, [i["name"] for i in self._ifaces().values() if ssid in prof.get(i["name"], [])])

    # ---- Bluetooth ----
    @_envelope
    def bt_radio(self):
        rs = bt.radios()
        return {"active": next((r["key"] for r in rs if r["ok"]), None), "can_switch": self._admin,
                "radios": [{"key": r["key"], "name": self._name(r["key"], r["name"]), "ok": r["ok"],
                            "disabled": r["disabled"], "version": r["version"]} for r in rs]}

    @_envelope
    def bt_switch(self, key):
        if not self._admin:
            raise bt.BtError("Bluetooth radio switching needs administrator rights. Restart the app and choose Yes.")
        return {"active": bt.switch(key)}

    @_envelope
    def bt_paired(self):
        return bt.devices(paired=True)

    @_envelope
    def bt_nearby(self):
        return bt.devices(paired=False)

    @_envelope
    def bt_pair(self, dev_id):
        bt.pair(dev_id)

    @_envelope
    def bt_remove(self, dev_id):
        bt.remove(dev_id)

    @_envelope
    def bt_connect(self, dev_id):
        d = self._device(dev_id)
        bt.connect(d["address"], d["name"])

    @_envelope
    def bt_disconnect(self, dev_id):
        d = self._device(dev_id)
        bt.disconnect(d["address"], d["name"])

    # ---- speed ----
    @_envelope
    def speed_test(self, key):
        if not self._speed_lock.acquire(blocking=False):
            raise speed.SpeedError("A speed test is already running.")
        try:
            i = self._iface(key)
            addr = speed.addresses(i["name"])
            result = speed.run_test(addr["ip"], addr["gateway"], on_sample=self._push_sample)
            result["link"] = round(i["rx"]) if "rx" in i else None
            speed.save_result(self._results, key, result)
            return result
        finally:
            self._speed_lock.release()

    @_envelope
    def speed_results(self):
        return speed.load_results(self._results)
```

- [ ] **Step 4: Run the tests and check they pass, except the contract test.** Run `py -3.10 -m pytest tests/test_api.py --deselect tests/test_api.py::test_mock_api_matches_python_api`.
Expected: `11 passed, 1 deselected`.

- [ ] **Step 5: Commit**

```bash
git add api.py tests/test_api.py
git commit -m "feat(api): page-facing Api with plain-language envelopes, admin gating, live speed samples"
```

### Task 8: Wire the page to the API (mock for preview and tests) and add UI tests

**Files:**
- Create: `ui/mock-api.js`, `tests/ui/__init__.py`, `tests/ui/test_ui.py`
- Modify: `ui/index.html` (a handful of HTML edits and one CSS rule; the main `<script>` block is replaced entirely)

**Interfaces:**
- Consumes: every `Api` method and data shape from Task 7.
- Produces:
  - `window.mockApi`: same 20 methods as `Api`, each defined with `def("<name>", …)` so the Task 7 contract test can read the names.
  - Page entry points: `window.onSpeedSample({phase, v})`, which Python calls during a speed test.
  - `?mock` in the URL selects the mock. Without it, the page waits for `pywebviewready`.
  - Test hooks for the mock, set before the page loads: `MOCK_FAST`, `MOCK_FAIL = {method: "message"}`, `MOCK_UNPLUG = "<key>"`, `MOCK_ADMIN = false`, `MOCK_HOSTILE`.

- [ ] **Step 1: Write the failing UI tests.** Create `tests/ui/__init__.py` (empty) and `tests/ui/test_ui.py`.

```python
"""UI tests: ui/index.html against ui/mock-api.js, in the installed Microsoft Edge (no browser download)."""
import functools, http.server, threading
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.ui
UI = Path(__file__).resolve().parents[2] / "ui"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="session")
def base_url():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(UI)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/index.html?mock"
    httpd.shutdown()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        yield b
        b.close()


@pytest.fixture
def open_page(browser, base_url):
    pages = []

    def _open(hooks=""):
        pg = browser.new_page(viewport={"width": 1100, "height": 800})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("dialog", lambda d: (pg.errors.append("unexpected dialog: " + d.message), d.dismiss()))
        pg.add_init_script("window.MOCK_FAST = true;" + hooks)
        pg.goto(base_url)
        expect(pg.locator("#netRows .row").first).to_be_visible()
        pages.append(pg)
        return pg

    yield _open
    for pg in pages:
        assert pg.errors == []
        pg.close()


def hold(page, locator, ms=1700):
    box = locator.bounding_box()
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.mouse.down()
    page.wait_for_timeout(ms)
    page.mouse.up()


def net(page, ssid):
    return page.locator("#netRows .row").filter(has=page.get_by_text(ssid, exact=True))


def saved_row(page, ssid):
    return page.locator("#savedList .row").filter(has=page.get_by_text(ssid, exact=True))


def test_loads_networks_rail_and_versions(open_page):
    pg = open_page()
    expect(pg.locator("#netRows .row")).to_have_count(8)  # 7 named + 1 hidden
    expect(pg.locator(".adapter")).to_have_count(2)
    expect(pg.locator(".adapter").nth(0).locator(".caps")).to_have_text("Wi-Fi 6, Bluetooth 5.4")
    expect(pg.locator(".adapter").nth(1).locator(".caps")).to_have_text("Wi-Fi 6, Bluetooth 5.2")
    expect(pg.locator(".adapter").nth(0).locator(".meta b")).to_have_text("HOME-5G")
    expect(pg.locator("#wifiLabel")).to_have_text("Wi-Fi 6")
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.4")


def test_hostile_ssid_is_text(open_page):
    pg = open_page("window.MOCK_HOSTILE = true;")
    expect(net(pg, "<img src=x onerror=alert(1)>")).to_be_visible()
    assert pg.locator("#netRows img, .map img, #tip img").count() == 0


def test_hidden_network_cannot_connect(open_page):
    pg = open_page()
    net(pg, "(hidden network)").click()
    expect(pg.locator("#connect")).to_be_disabled()


def test_connect_saved_network(open_page):
    pg = open_page()
    net(pg, "Maple House").click()
    pg.locator("#connect").click()
    expect(net(pg, "Maple House").locator(".state")).to_have_text("Connected")
    expect(pg.locator("#wifiMsg")).to_have_text("Connected to Maple House.")
    expect(pg.locator(".adapter").nth(0).locator(".meta b")).to_have_text("Maple House")


def test_new_network_password_rules_and_wrong_password(open_page):
    pg = open_page()
    net(pg, "AirFiber-Maple House").click()
    pg.locator("#connect").click()
    expect(pg.locator("#pw")).to_be_visible()
    pg.fill("#pwInput", "short")
    pg.keyboard.press("Enter")
    expect(pg.locator("#pwErr")).to_have_text("The password must be 8 to 63 characters.")
    pg.fill("#pwInput", "wrongpass")
    pg.keyboard.press("Enter")
    expect(pg.locator("#pw")).to_be_hidden()
    expect(pg.locator("#wifiMsg")).to_have_text("Couldn't connect to AirFiber-Maple House. Check the password.")
    expect(pg.locator("#wifiMsg")).to_have_class("msg err")


def test_saved_show_copy_delete(open_page):
    pg = open_page()
    pg.locator('.tabs button[data-view="saved"]').click()
    r = saved_row(pg, "Maple House")
    r.locator(".reveal").click()
    expect(r.locator(".secret")).to_have_text("mock-pass-1234")
    r.locator(".copy").click()
    expect(r.locator(".where")).to_have_text("Both adapters")
    hold(pg, saved_row(pg, "oldrouter").locator(".hold"))
    expect(saved_row(pg, "oldrouter")).to_have_count(0)
    expect(pg.locator("#savedCount")).to_have_text("6")


def test_short_hold_does_not_delete(open_page):
    pg = open_page()
    pg.locator('.tabs button[data-view="saved"]').click()
    hold(pg, saved_row(pg, "oldrouter").locator(".hold"), ms=300)
    pg.wait_for_timeout(1500)
    expect(saved_row(pg, "oldrouter")).to_have_count(1)


def test_delete_failure_keeps_row(open_page):
    pg = open_page('window.MOCK_FAIL = { delete_profile: "Windows refused to delete it." };')
    pg.locator('.tabs button[data-view="saved"]').click()
    hold(pg, saved_row(pg, "oldrouter").locator(".hold"))
    expect(pg.locator("#savedMsg")).to_have_text("Windows refused to delete it.")
    expect(saved_row(pg, "oldrouter")).to_have_count(1)


def test_bt_radio_switch_changes_label(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.4")
    pg.locator("#tryRadio").click()
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.2")
    expect(pg.locator("#btRadio")).to_have_text("Built-in MediaTek")


def test_bt_switch_needs_admin(open_page):
    pg = open_page("window.MOCK_ADMIN = false;")
    pg.keyboard.press("Control+2")
    expect(pg.locator("#tryRadio")).to_be_disabled()
    expect(pg.locator("#btMsg")).to_contain_text("needs administrator rights")


def test_bt_search_pair_remove(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    expect(pg.locator("#paired .row")).to_have_count(6)
    pg.locator("#btSearch").click()
    expect(pg.locator("#nearby .row")).to_have_count(3)
    pg.locator("#nearby .pair").first.click()
    expect(pg.locator("#paired .row")).to_have_count(7)
    expect(pg.locator("#pairedCount")).to_have_text("7")
    hold(pg, pg.locator("#paired .row").nth(1).locator(".hold"))
    expect(pg.locator("#paired .row")).to_have_count(6)


def test_bt_connect_toggles(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    jbl = pg.locator("#paired .row").filter(has=pg.get_by_text("JBL Go 3", exact=True))
    jbl.locator(".conn").click()
    expect(jbl.locator(".st")).to_have_text("Connected")
    expect(jbl.locator(".conn .label")).to_have_text("Disconnect")


def test_speed_test_draws_and_saves(open_page):
    pg = open_page()
    pg.keyboard.press("Control+3")
    pg.locator("#runTest").click()
    expect(pg.locator("#runTest .label")).to_have_text("Run test", timeout=10000)
    expect(pg.locator("#runTest")).to_be_enabled()
    assert pg.evaluate("document.querySelector('#tp')._m.n") == 40
    expect(pg.locator('#results tr[data-adapter="unigen"] td').nth(3)).not_to_have_text("–")
    expect(pg.locator("#bars .bar")).to_have_count(8)


def test_unplugged_adapter_in_rail(open_page):
    pg = open_page()
    pg.evaluate("window.MOCK_UNPLUG = 'builtin'")
    expect(pg.locator(".adapter").nth(1).locator(".meta b")).to_have_text("Unplugged", timeout=5000)
    pg.locator(".adapter").nth(1).click()
    expect(pg.locator("#wifiMsg")).to_have_text("The Built-in MediaTek isn't plugged in.")


def test_signal_chart_fills_from_polling(open_page):
    pg = open_page()
    pg.keyboard.press("Control+3")
    pg.wait_for_timeout(4500)
    expect(pg.locator("#sig .line")).to_have_count(2)
    assert pg.evaluate("document.querySelector('#sig .line').getAttribute('d').length") > 10
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/ui`.
Expected: FAIL. `#netRows .row` never appears, because `?mock` and `mock-api.js` don't exist yet.

- [ ] **Step 3: Create `ui/mock-api.js`**

```js
// Stand-in for api.py when the page is opened as index.html?mock (browser preview and UI tests).
// Same method names and data shapes as the Python Api; tests/test_api.py checks that the names match.
// Test hooks (set before the page loads): MOCK_FAST (no delays), MOCK_FAIL = { method: "message" },
// MOCK_UNPLUG = "unigen" | "builtin", MOCK_ADMIN = false, MOCK_HOSTILE (adds a network named like an HTML tag).
window.mockApi = (() => {
  const wait = ms => new Promise(r => setTimeout(r, window.MOCK_FAST ? 0 : ms));
  const api = {};
  function def(name, ms, fn) {
    api[name] = async (...args) => {
      await wait(ms);
      const fail = (window.MOCK_FAIL || {})[name];
      if (fail) return { ok: false, error: fail };
      try { return { ok: true, data: (await fn(...args)) ?? null }; }
      catch (e) { return { ok: false, error: e.message }; }
    };
  }

  const NAMES = { unigen: "Unigen dongle", builtin: "Built-in MediaTek" };
  const ADAPTERS = [
    { key: "unigen", name: NAMES.unigen, bt: "5.4", state: "connected", ssid: "HOME-5G", signal: 97, rate: 433, channel: 36, band: 5 },
    { key: "builtin", name: NAMES.builtin, bt: "5.2", state: "connected", ssid: "HOME-5G", signal: 80, rate: 866, channel: 36, band: 5 },
  ];
  const NETS = [
    { ssid: "HOME-5G", auth: "WPA2-Personal", aps: [{ b: 5, ch: 36, s: 96 }] },
    { ssid: "Maple House", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 6, s: 92 }, { b: 2.4, ch: 1, s: 38 }] },
    { ssid: "AirFiber-Maple House", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 48 }, { b: 5, ch: 157, s: 18 }] },
    { ssid: "AirFiber-Cedar12", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 1, s: 46 }, { b: 5, ch: 157, s: 14 }] },
    { ssid: "[Smart_Fridge]a1b2", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 32 }] },
    { ssid: "Workshop12", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 14 }, { b: 5, ch: 149, s: 14 }] },
    { ssid: "CEDAR-12", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 14 }, { b: 5, ch: 149, s: 14 }] },
    { ssid: "", auth: "WPA2-Personal", aps: [{ b: 5, ch: 149, s: 6 }] },
  ];
  if (window.MOCK_HOSTILE) NETS.push({ ssid: "<img src=x onerror=alert(1)>", auth: "Open", aps: [{ b: 2.4, ch: 1, s: 9 }] });
  const PROFILES = {
    unigen: new Set(["HOME-5G", "Maple House", "oldrouter", "Guest_net 2", "phone_hotspot", "Cafe_wifi", "Guest_net"]),
    builtin: new Set(["HOME-5G", "phone_hotspot", "Cafe_wifi", "Guest_net 2", "Guest_net"]),
  };
  const SEC = { "WPA2-Personal": "WPA2", "Open": "Open" };
  const RADIOS = [
    { key: "unigen", name: NAMES.unigen, ok: true, disabled: false, version: "5.4" },
    { key: "builtin", name: NAMES.builtin, ok: false, disabled: true, version: "5.2" },
  ];
  const PAIRED = [
    { id: "BT-beats", name: "Den Beats Pill", connected: true, kind: "Speaker", address: "A1B2C3D4E5F1" },
    { id: "BT-nord", name: "OnePlus Nord Buds 3r", connected: false, kind: "Headphones", address: "A1B2C3D4E5F2" },
    { id: "BT-jbl", name: "JBL Go 3", connected: false, kind: "Speaker", address: "A1B2C3D4E5F3" },
    { id: "BT-tribit", name: "Tribit StormBox Mini+", connected: false, kind: "Speaker", address: "A1B2C3D4E5F4" },
    { id: "BT-mhx", name: "MHX-BT88", connected: false, kind: "Audio", address: "A1B2C3D4E5F5" },
    { id: "BT-dualsense", name: "DualSense Wireless Controller", connected: false, kind: "Controller", address: "A1B2C3D4E5F6" },
  ];
  const NEARBY = [
    { id: "BT-buds2", name: "Galaxy Buds2 Pro", connected: false, kind: "Headphones", address: "B1B2C3D4E5F1" },
    { id: "BT-boat", name: "boAt Stone 350", connected: false, kind: "Speaker", address: "B1B2C3D4E5F2" },
    { id: "BT-mi", name: "Mi Portable Speaker", connected: false, kind: "Speaker", address: "B1B2C3D4E5F3" },
  ];

  // speed: 28 download + 12 upload samples, ramping up at the start of each phase (like speed.py)
  const sample = (i, dl, ul) => {
    const up = i >= 28, k = up ? i - 28 : i;
    return +((up ? ul : dl) * Math.min(1, (k + 1) / 5) * (0.85 + Math.random() * 0.3)).toFixed(1);
  };
  const avg = xs => Math.round(xs.slice(3).reduce((a, b) => a + b, 0) / Math.max(1, xs.length - 3));
  const stamp = () => { const d = new Date(), p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
  const result = (samples, link, at) => ({ ping: 2, down: avg(samples.slice(0, 28)), up: avg(samples.slice(28)), samples, split: 28, at, link });
  const BASE = { unigen: [50, 12], builtin: [53, 31] };
  const RESULTS = {};
  for (const k of ["unigen", "builtin"]) RESULTS[k] = result(Array.from({ length: 40 }, (_, i) => sample(i, ...BASE[k])), k === "unigen" ? 433 : 866, "2026-10-12 23:00");

  const plugged = () => ADAPTERS.filter(a => a.key !== window.MOCK_UNPLUG);
  const adapter = key => {
    const a = plugged().find(x => x.key === key);
    if (!a) throw new Error(`The ${NAMES[key] || key} isn't plugged in.`);
    return a;
  };
  const shape = a => {
    const nets = NETS.map(n => ({
      ssid: n.ssid, sec: SEC[n.auth] || n.auth, auth: n.auth, hidden: !n.ssid,
      state: n.ssid && a.state === "connected" && a.ssid === n.ssid ? "Connected" : PROFILES[a.key].has(n.ssid) ? "Saved" : "",
      aps: n.aps.map(x => ({ ...x, s: Math.max(1, x.s - (a.key === "builtin" ? 12 : 0)) })),
    }));
    const best = n => Math.max(0, ...n.aps.map(x => x.s));
    nets.sort((x, y) => (x.state !== "Connected") - (y.state !== "Connected") || best(y) - best(x));
    return { networks: nets, scanned_at: Date.now() / 1000 };
  };

  def("app_info", 0, () => ({ admin: window.MOCK_ADMIN !== false, adapters: plugged().map(a => ({ key: a.key, name: a.name, wifi: "Wi-Fi 6", bt: a.bt })) }));
  def("adapters", 0, () => plugged().map(a => {
    const on = a.state === "connected";
    return { key: a.key, name: a.name, state: a.state, ssid: on ? a.ssid : null, rate: on ? a.rate : null, channel: a.channel, band: a.band,
             signal: on ? Math.max(50, Math.min(100, a.signal + Math.round(Math.random() * 4 - 2))) : null };
  }));
  def("networks", 200, key => shape(adapter(key)));
  def("scan", 1600, key => shape(adapter(key)));
  def("connect", 1600, (key, ssid, password) => {
    const a = adapter(key), n = NETS.find(x => x.ssid === ssid);
    if (!n) throw new Error(`${ssid} is out of range.`);
    if (!PROFILES[key].has(ssid)) {
      if (n.auth !== "Open" && !(typeof password === "string" && password.length >= 8 && password.length <= 63)) throw new Error("The password must be 8 to 63 characters.");
      if (password === "wrongpass") throw new Error(`Couldn't connect to ${ssid}. Check the password.`);
      PROFILES[key].add(ssid);
    }
    const five = n.aps.some(x => x.b === 5);
    Object.assign(a, { state: "connected", ssid, rate: five ? (key === "unigen" ? 433 : 866) : (key === "unigen" ? 144 : 287) });
    return { ssid, rate: a.rate };
  });
  def("disconnect", 1000, key => { adapter(key).state = "disconnected"; });
  def("saved", 100, () => {
    const out = new Map();
    for (const a of plugged()) for (const s of PROFILES[a.key]) out.set(s, [...(out.get(s) || []), a.key]);
    return [...out].map(([ssid, on]) => ({ ssid, on }));
  });
  def("password", 150, ssid => {
    if (!Object.values(PROFILES).some(p => p.has(ssid))) throw new Error(`${ssid} isn't saved on this PC.`);
    return "mock-pass-1234";
  });
  def("copy_profile", 1200, (ssid, src, dst) => { adapter(src); adapter(dst); PROFILES[dst].add(ssid); });
  def("delete_profile", 300, ssid => { Object.values(PROFILES).forEach(p => p.delete(ssid)); });
  def("bt_radio", 100, () => ({ active: (RADIOS.find(r => r.ok) || {}).key ?? null, can_switch: window.MOCK_ADMIN !== false, radios: RADIOS.map(r => ({ ...r })) }));
  def("bt_switch", 2500, key => {
    if (window.MOCK_ADMIN === false) throw new Error("Bluetooth radio switching needs administrator rights. Restart the app and choose Yes.");
    RADIOS.forEach(r => { r.ok = r.key === key; r.disabled = !r.ok; });
    return { active: key };
  });
  def("bt_paired", 200, () => PAIRED.map(d => ({ ...d })));
  def("bt_nearby", 3000, () => NEARBY.filter(d => !PAIRED.some(p => p.id === d.id)).map(d => ({ ...d })));
  def("bt_pair", 1400, id => {
    const d = NEARBY.find(x => x.id === id);
    if (!d) throw new Error("The device didn't answer in time. Put it in pairing mode and try again.");
    PAIRED.push({ ...d, connected: false });
  });
  def("bt_remove", 500, id => { const i = PAIRED.findIndex(d => d.id === id); if (i >= 0) PAIRED.splice(i, 1); });
  def("bt_connect", 1400, id => { const d = PAIRED.find(x => x.id === id); if (!d) throw new Error("That device isn't paired any more."); d.connected = true; });
  def("bt_disconnect", 1000, id => { const d = PAIRED.find(x => x.id === id); if (!d) throw new Error("That device isn't paired any more."); d.connected = false; });
  def("speed_test", 0, async key => {
    const a = adapter(key);
    if (a.state !== "connected") throw new Error("That adapter isn't connected to a network.");
    const samples = [];
    for (let i = 0; i < 40; i++) {
      const v = sample(i, ...BASE[key]);
      samples.push(v);
      if (window.onSpeedSample) window.onSpeedSample({ phase: i >= 28 ? "up" : "down", v });
      await wait(75);
    }
    return (RESULTS[key] = result(samples, a.rate, stamp()));
  });
  def("speed_results", 0, () => JSON.parse(JSON.stringify(RESULTS)));
  return api;
})();
```

- [ ] **Step 4: Make the HTML edits in `ui/index.html`**

4a. Side menu labels. Replace:
```html
    <button aria-current="page" data-go="wifi">Wi-Fi 6 <kbd>Ctrl 1</kbd></button>
    <button data-go="bt"><span id="btLabel">Bluetooth 5.4</span> <kbd>Ctrl 2</kbd></button>
```
with:
```html
    <button aria-current="page" data-go="wifi"><span id="wifiLabel">Wi-Fi</span> <kbd>Ctrl 1</kbd></button>
    <button data-go="bt"><span id="btLabel">Bluetooth</span> <kbd>Ctrl 2</kbd></button>
```

4b. Adapters are now rendered from `app_info()`. Replace the whole `<div class="adapters"> … </div>` block (the comment plus both `<button class="adapter">` elements) with:
```html
    <div class="adapters"><span class="ind ad-ind" aria-hidden="true"></span></div>
```

4c. Saved count. Replace `<span class="count" id="savedCount">7</span>` with `<span class="count" id="savedCount"></span>`.

4d. Nearby heading. Replace:
```html
        <h1>7 networks nearby</h1>
        <span class="sub" id="scanAge">Scanned 12 seconds ago</span>
```
with:
```html
        <h1 id="wifiTitle">Looking for networks…</h1>
        <span class="sub" id="scanAge"></span>
```

4e. Saved message line. Replace:
```html
      <div class="head"><h1>Saved networks</h1><span class="sub">Stored by Windows on this PC</span></div>
```
with:
```html
      <div class="head"><h1>Saved networks</h1><span class="sub">Stored by Windows on this PC</span><span class="grow"></span><span class="msg" id="savedMsg"></span></div>
```

4f. Bluetooth note. Replace:
```html
      <p>Bluetooth is running on the <b id="btRadio">Unigen dongle</b>. <span id="btOther">The built-in MediaTek radio is turned off.</span>
```
with:
```html
      <p>Bluetooth is running on the <b id="btRadio">…</b>. <span id="btOther"></span>
```
and replace `<h2>Paired devices <span id="pairedCount">6</span></h2>` with `<h2>Paired devices <span id="pairedCount"></span></h2>`.

4g. Speed screen. Replace:
```html
      <h1>Speed on Unigen dongle</h1>
      <span class="grow"></span>
```
with:
```html
      <h1>Speed</h1>
      <span class="msg" id="speedMsg"></span>
      <span class="grow"></span>
```
In the three `.readout` blocks, replace the values `<span class="big">2</span>`, `<span class="big">50</span>` and `<span class="big">12</span>` with `<span class="big">–</span>`. Then replace the whole `<tbody> … </tbody>` of the results table with `<tbody id="results"></tbody>`, and `<span id="measured">measured 12 Oct 2026</span>` with `<span id="measured"></span>`.

4h. Password error line. Replace:
```html
    <input type="password" id="pwInput" aria-label="Password" autocomplete="off" autofocus>
```
with:
```html
    <input type="password" id="pwInput" aria-label="Password" autocomplete="off" autofocus>
    <p class="msg err" id="pwErr" aria-live="polite"></p>
```
and add this CSS rule after `dialog .ops { … }`:
```css
  dialog .msg { margin: 8px 0 0; min-height: 1.2em; }
```

4i. Scripts. Replace `<script src="vendor/anime.umd.min.js"></script>` with:
```html
<script src="vendor/anime.umd.min.js"></script>
<script src="mock-api.js"></script>
```

- [ ] **Step 5: Replace the main `<script>` block.** Replace everything from the `<script>` line after `mock-api.js` to its closing `</script>` with this script.

```html
<script>
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ================= bridge to Python (api.py) =================
// Inside the app, pywebview injects window.pywebview.api. Opened as index.html?mock (browser preview, UI tests),
// the page uses window.mockApi from mock-api.js. Inside the app it never falls back to mock data.
const MOCK = new URLSearchParams(location.search).has("mock");
const apiReady = new Promise(resolve => {
  if (MOCK) return resolve(window.mockApi);
  if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
  addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
});
// call: resolves to data, or throws an Error whose message is safe to show
async function call(name, ...args) {
  const api = await apiReady;
  const r = await api[name](...args);
  if (!r || !r.ok) throw new Error(r && r.error ? r.error : "No answer from the app.");
  return r.data;
}

// ================= motion components (anime.js) =================
// Every click gets a response, sized to how often it happens:
// constant actions get near-invisible motion, rare ones get the most.
const ease = anime.cubicBezier(0.23, 1, 0.32, 1); // same curve as CSS --ease-out
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches; // reduced motion: fades only
const HOLD_MS = 1500;

// press: any clickable dips while the pointer is down, eases back on release
const PRESSABLE = ".btn, .adapter, nav button, .tabs button, .link";
let pressed = null;
document.addEventListener("pointerdown", e => {
  const el = e.target.closest(PRESSABLE);
  if (!el || el.disabled || reduce) return;
  pressed = el;
  anime.animate(el, { scale: 0.97, duration: 120, ease });
});
["pointerup", "pointercancel"].forEach(t => document.addEventListener(t, () => {
  if (pressed) anime.animate(pressed, { scale: 1, duration: 200, ease });
  pressed = null;
}));

// slide: one highlight per group travels to the chosen item
function slide(ind, to, instant) {
  if (!to) return;
  const at = ind.dataset.axis === "x" ? { x: to.offsetLeft, width: to.offsetWidth } : { y: to.offsetTop, height: to.offsetHeight };
  if (instant || reduce) anime.set(ind, at);
  else anime.animate(ind, { ...at, duration: 200, ease });
}

// swap: a label changes with a short blur, so it reads as one control changing
function swap(btn, text) {
  const l = $(".label", btn);
  if (l.textContent === text) return;
  if (reduce) { l.textContent = text; return; }
  anime.animate(l, { opacity: 0.6, filter: "blur(2px)", duration: 100, ease, onComplete: () => {
    l.textContent = text;
    anime.animate(l, { opacity: 1, filter: "blur(0px)", duration: 140, ease });
  } });
}

// busy: the shared shape of every slow action. Disable, swap the label, show progress, await the work,
// then settle on `after` if it worked or the original label if it failed.
async function busy(btn, label, work, { prog, after } = {}) {
  const was = $(".label", btn).textContent;
  let ok = false;
  btn.disabled = true; swap(btn, label);
  if (prog) prog.hidden = false;
  try { const r = await work; ok = true; return r; }
  finally {
    btn.disabled = false; swap(btn, ok ? (after ?? was) : was);
    if (prog) prog.hidden = true;
  }
}

// arrive: a changed value settles in so the eye catches what changed
function arrive(el) {
  anime.animate(el, reduce ? { opacity: [0, 1], duration: 150, ease }
    : { opacity: [0, 1], y: [3, 0], duration: 200, ease });
}
function setText(el, text) {
  if (el.textContent === String(text)) return;
  el.textContent = text; arrive(el);
}
// replays the fade every time, even for identical text
function setMsg(el, text, isErr) {
  el.textContent = text;
  el.classList.toggle("err", !!isErr);
  anime.waapi.animate(el, { opacity: [0, 1], duration: 150, ease });
}

// scramble: password reveal/hide (scrambleText writes innerHTML, so the text is escaped first)
function scramble(el, text) {
  if (reduce) { el.textContent = text; return arrive(el); }
  anime.animate(el, { innerHTML: anime.scrambleText({ text: esc(text) }), duration: 300 });
}

// pop: a status dot changes state
function pop(dot, on) {
  dot.classList.toggle("on", on);
  if (!reduce) anime.animate(dot, { scale: [1.8, 1], duration: 250, ease });
}

// layout transition on a list: mutate runs between record() and animate()
const layouts = new WeakMap();
function relayout(list, mutate, params) {
  let l = layouts.get(list);
  if (!l) layouts.set(list, l = anime.createLayout(list, { duration: 200, ease }));
  l.record(); mutate(); l.animate(params);
}
// removeEl: fades out while the rest slides into the gap
function removeEl(el, done) {
  const fin = () => { el.remove(); if (done) done(); };
  if (reduce) return anime.animate(el, { opacity: 0, duration: 150, ease, onComplete: fin });
  // the layout treats display:none as leaving, fades it out, then we drop it
  relayout(el.parentElement, () => el.style.display = "none", { onComplete: fin });
}
// addEl: appends a row that settles in
function addEl(list, html) {
  relayout(list, () => list.insertAdjacentHTML("beforeend", html),
    { enterFrom: reduce ? { opacity: 0 } : { opacity: 0, transform: "translateY(4px)" } });
}

// ================= state =================
let INFO = null;     // app_info(): admin flag + each adapter's name and standards
let ADS = [];        // latest adapters() poll
let NETS = [];       // networks seen by the chosen adapter
let SAVED = [];      // saved(): [{ssid, on: [keys]}]
let BT = null;       // bt_radio()
let RESULTS = {};    // speed_results(): key -> {ping, down, up, link, samples, split, at}
let selected = 0, selSsid = null, scannedAt = null;
const activeAdapter = () => $(".adapter[aria-pressed='true']");
const activeKey = () => activeAdapter()?.dataset.adapter;
const adapterEl = k => $$(".adapter").find(a => a.dataset.adapter === k);
const NAME = k => (INFO && INFO.adapters.find(a => a.key === k) || {}).name || k;
const SHORT = k => ({ unigen: "Unigen", builtin: "Built-in" })[k] || NAME(k);
const COLOR = k => ({ unigen: "var(--uni)", builtin: "var(--bi)" })[k] || "var(--muted)";

// ================= channel map =================
const CH5 = [36,40,44,48,52,56,60,64,100,104,108,112,116,120,124,128,132,136,140,144,149,153,157,161,165];
const H = 92, ROOM = 18; // baseline y; headroom for the name label at 100%
const peak = sig => H - (sig / 100) * (H - ROOM);
function hump(x, half, sig) {
  const top = peak(sig);
  return `M${x - half},${H} C${x - half * 0.45},${top} ${x + half * 0.45},${top} ${x + half},${H}`;
}
// Drawn at the SVG's real pixel width so text and curves never stretch.
function drawMaps() {
  const s24 = $("#map24"), s5 = $("#map5");
  const W24 = s24.clientWidth, W5 = s5.clientWidth;
  if (!W24 || !W5) return;
  const u24 = W24 / 16, u5 = W5 / 27;           // padded so edge humps fit
  const x24 = ch => (ch + 1) * u24;            // channels -1..15
  const x5 = i => (i + 1.5) * u5;              // slots -1.5..25.5
  let a = "", b = "";
  NETS.forEach((n, ni) => n.aps.forEach(ap => {
    const cls = `hump ${n.state === "Connected" ? "connected" : "dim"}`;
    const top = peak(ap.s) - 6;
    let x, half;
    if (ap.b === 2.4) { x = x24(ap.ch); half = 2 * u24; }
    else { const i = CH5.indexOf(ap.ch); if (i < 0) return; x = x5(Math.floor(i / 4) * 4 + 1.5); half = 2 * u5; } // 80 MHz block
    const out = `<path class="${cls}" data-net="${ni}" d="${hump(x, half, ap.s)}"/>
           <text class="tag" data-net="${ni}" x="${x}" y="${top}" text-anchor="middle">${n.hidden ? "(hidden network)" : esc(n.ssid)}</text>`;
    if (ap.b === 2.4) a += out; else b += out;
  }));
  a += [1, 6, 11, 13].map(c => `<text class="axis" x="${x24(c)}" y="106" text-anchor="middle">${c}</text>`).join("");
  b += [36, 52, 100, 116, 132, 149, 165].map(c => `<text class="axis" x="${x5(CH5.indexOf(c))}" y="106" text-anchor="middle">${c}</text>`).join("");
  s24.setAttribute("viewBox", `0 0 ${W24} 110`);
  s5.setAttribute("viewBox", `0 0 ${W5} 110`);
  s24.innerHTML = `<line x1="0" x2="${W24}" y1="${H}" y2="${H}" stroke="#2A3A4B"/>` + a;
  s5.innerHTML = `<line x1="0" x2="${W5}" y1="${H}" y2="${H}" stroke="#2A3A4B"/>` + b;
}
// the newly connected network fills in on the map
function fillIn() {
  if (reduce) return;
  $$(".hump.connected").forEach(p => anime.animate(p, {
    fillOpacity: [0, 0.55], duration: 250, ease, onComplete: () => p.style.fillOpacity = "",
  }));
}

// ================= Wi-Fi: nearby networks =================
const best = n => Math.max(0, ...n.aps.map(a => a.s));
function drawNets() {
  setText($("#wifiTitle"), `${NETS.length} network${NETS.length === 1 ? "" : "s"} nearby`);
  $("#netRows").innerHTML = NETS.map((n, i) => `<div class="row" role="option" data-i="${i}" aria-selected="false">
      <span class="title${n.hidden ? " muted" : ""}">${n.hidden ? "(hidden network)" : esc(n.ssid)}</span>
      <span class="signal"><span class="num">${best(n)}%</span><span class="meter"><i style="transform:scaleX(${best(n) / 100})"></i></span></span>
      <span class="chips">${n.aps.map(a => `<span class="chip ${a.b === 5 ? "b5" : "b24"}">${a.b} GHz, ch ${a.ch}</span>`).join("")}</span>
      <span class="muted">${esc(n.sec)}</span>
      <span class="state ${n.state === "Connected" ? "ok" : "muted"}">${esc(n.state)}</span>
    </div>`).join("");
  markSel(true); syncButtons();
}
function markSel(instant) {
  const i = NETS.findIndex(n => n.ssid === selSsid);
  selected = i < 0 ? 0 : i;
  selSsid = NETS[selected] ? NETS[selected].ssid : null;
  $$("#netRows .row").forEach(r => r.setAttribute("aria-selected", r.dataset.i == selected));
  slide($(".sel-ind"), $(`#netRows .row[data-i="${selected}"]`), instant);
}
function highlight(i) {
  $$(".map [data-net]").forEach(p => p.classList.toggle("hot", p.dataset.net == i));
}
function syncButtons() {
  const n = NETS[selected];
  $("#connect").disabled = !n || n.hidden || n.state === "Connected";
  $("#disconnect").disabled = !n || n.state !== "Connected";
}
$("#netRows").addEventListener("click", e => {
  const r = e.target.closest(".row"); if (!r) return;
  selSsid = NETS[+r.dataset.i].ssid; markSel(); highlight(+r.dataset.i); syncButtons();
});
$("#netRows").addEventListener("dblclick", () => $("#connect").click());
$("#netRows").addEventListener("mouseover", e => { const r = e.target.closest(".row"); if (r) highlight(r.dataset.i); });
$("#netRows").addEventListener("mouseleave", () => highlight(selected));

async function loadNetworks(fresh) {
  const key = activeKey(); if (!key) return;
  const r = await call(fresh ? "scan" : "networks", key);
  let nets = r.networks;
  if ($("#netRows").matches(":hover") && NETS.length) { // never reorder rows under the pointer
    const pos = new Map(NETS.map((n, i) => [n.ssid, i]));
    const at = n => pos.has(n.ssid) ? pos.get(n.ssid) : 1e9;
    nets = [...nets].sort((a, b) => at(a) - at(b));
  }
  NETS = nets; scannedAt = r.scanned_at;
  drawNets();
  if (nearbyShown()) { drawMaps(); highlight(selected); }
  tickAge();
}
// ticks every second, so plain text: no animation
function tickAge() {
  if (scannedAt == null) return;
  const s = Math.max(0, Math.round(Date.now() / 1000 - scannedAt));
  $("#scanAge").textContent = s < 5 ? "Scanned just now" : s < 60 ? `Scanned ${s} seconds ago` : `Scanned ${Math.round(s / 60)} min ago`;
}

async function doConnect(password) {
  const n = NETS[selected]; if (!n) return;
  try {
    await busy($("#connect"), "Connecting…", call("connect", activeKey(), n.ssid, password ?? null), { after: "Connect" });
    setMsg($("#wifiMsg"), `Connected to ${n.ssid}.`);
    await Promise.all([loadNetworks(false), poll()]);
    fillIn();
  } catch (e) { setMsg($("#wifiMsg"), e.message, true); syncButtons(); }
}
$("#connect").addEventListener("click", function () {
  if (this.disabled) return;
  const n = NETS[selected];
  if (n.state || n.sec !== "WPA2") doConnect(); // saved, open, or a type the backend will explain
  else openPw(n);
});
$("#disconnect").addEventListener("click", async function () {
  const n = NETS[selected];
  if (this.disabled || !n) return;
  try {
    await busy(this, "Disconnecting…", call("disconnect", activeKey()));
    setMsg($("#wifiMsg"), `Disconnected from ${n.ssid}.`);
    await Promise.all([loadNetworks(false), poll()]);
  } catch (e) { setMsg($("#wifiMsg"), e.message, true); }
});
$("#scan").addEventListener("click", async function () {
  const old = new Map(NETS.map(n => [n.ssid, best(n)]));
  try { await busy(this, "Scanning…", loadNetworks(true), { after: "Scan again" }); }
  catch (e) { return setMsg($("#wifiMsg"), e.message, true); }
  if (reduce) return;
  $$("#netRows .row").forEach(r => { // meters ease from their previous value to the new one
    const n = NETS[r.dataset.i];
    if (old.has(n.ssid)) anime.animate($(".meter i", r), { scaleX: [old.get(n.ssid) / 100, best(n) / 100], duration: 300, ease });
  });
});

// ================= adapters rail + polling =================
function renderRail() {
  $(".adapters").innerHTML = `<span class="ind ad-ind" aria-hidden="true"></span>` + INFO.adapters.map((a, i) => `
    <button class="adapter" aria-pressed="${i === 0}" data-adapter="${esc(a.key)}" data-bt="${esc(a.bt || "")}">
      <span class="dot"></span><span class="name">${esc(a.name)}</span>
      <span class="meta"><b>Checking…</b><br><span class="rate"></span></span>
      <span class="caps">${esc([a.wifi, a.bt && `Bluetooth ${a.bt}`].filter(Boolean).join(", "))}</span>
    </button>`).join("");
  $$(".adapter").forEach(a => a.addEventListener("click", () => pickAdapter(a)));
  slide($(".ad-ind"), activeAdapter(), true);
  setText($("#wifiLabel"), (INFO.adapters[0] || {}).wifi || "Wi-Fi");
}
function updateRail() {
  $$(".adapter").forEach(a => {
    const d = ADS.find(x => x.key === a.dataset.adapter), on = !!d && d.state === "connected";
    setText($(".meta b", a), !d ? "Unplugged" : on ? d.ssid : "Not connected");
    setText($(".rate", a), on ? `${d.rate} Mbps link` : "No link");
    const dot = $(".dot", a);
    if (dot.classList.contains("on") !== on) pop(dot, on);
  });
}
function pickAdapter(a) {
  $$(".adapter").forEach(x => x.setAttribute("aria-pressed", x === a));
  slide($(".ad-ind"), a);
  setText($("#wifiLabel"), (INFO.adapters.find(x => x.key === a.dataset.adapter) || {}).wifi || "Wi-Fi");
  setText($("#speed h1"), `Speed on ${$(".name", a).textContent}`);
  setText($("#tpSub"), `${$(".name", a).textContent}, Mbps`);
  showReadouts();
  const r = RESULTS[a.dataset.adapter];
  if (!$("#speed").hidden) drawTp(r ? r.samples : [], a.dataset.adapter, { draw: true, split: r && r.split });
  selSsid = null;
  loadNetworks(false).catch(e => setMsg($("#wifiMsg"), e.message, true));
}

const SIG_N = 60;  // 2 minutes of readings, one every 2 s
const sig = {};    // adapter key -> readings; null while not connected
const trimSig = () => Object.values(sig).forEach(a => { while (a.length > SIG_N) a.shift(); });
async function poll() {
  try { ADS = await call("adapters"); }
  catch (e) { return setMsg($("#wifiMsg"), e.message, true); }
  updateRail();
  for (const a of INFO.adapters) {
    const d = ADS.find(x => x.key === a.key);
    (sig[a.key] = sig[a.key] || []).push(d && d.state === "connected" ? d.signal : null);
  }
  const visible = !$("#speed").hidden && !busyChart($("#sig"));
  if (visible && !reduce && Object.values(sig).some(a => a.length > SIG_N)) return drawSig(true); // slides, then trims
  trimSig();
  if (visible) drawSig();
}

// ================= password dialog =================
const pw = $("#pw");
function openPw(n) {
  if (pw.open) return;
  $("#pwTitle").innerHTML = `Connect to ${esc(n.ssid)}`;
  $("#pwInput").value = "";
  $("#pwErr").textContent = "";
  pw.classList.remove("closing");
  pw.showModal();
  anime.animate(pw, reduce ? { opacity: [0, 1], duration: 150, ease }
    : { opacity: [0, 1], scale: [0.96, 1], duration: 200, ease });
}
function closePw(then) {
  if (pw.classList.contains("closing")) return;
  pw.classList.add("closing");
  anime.animate(pw, reduce ? { opacity: 0, duration: 150, ease, onComplete: done }
    : { opacity: 0, scale: 0.96, duration: 150, ease, onComplete: done });
  function done() { pw.close(); pw.classList.remove("closing"); if (then) then(); }
}
const validPassword = p => /^[0-9A-Fa-f]{64}$/.test(p) || (p.length >= 8 && p.length <= 63 && /^[\x20-\x7E]+$/.test(p));
$("#pwCancel").addEventListener("click", () => closePw());
pw.addEventListener("cancel", e => { e.preventDefault(); closePw(); }); // Escape
$("#pwForm").addEventListener("submit", e => {
  e.preventDefault();
  const value = $("#pwInput").value;
  if (!validPassword(value)) return setMsg($("#pwErr"), "The password must be 8 to 63 characters.", true);
  closePw(() => doConnect(value));
});

// ================= Bluetooth =================
const pairedRow = d => `<div class="row" data-id="${esc(d.id)}" data-kind="${esc(d.kind)}">
  <span class="title">${esc(d.name)}</span>
  <span class="st ${d.connected ? "state ok" : "muted"}">${d.connected ? "Connected" : esc(d.kind)}</span>
  <span class="ops">
    <button class="btn small conn"><span class="label">${d.connected ? "Disconnect" : "Connect"}</span></button>
    <button class="btn small hold"><span class="label">Hold to remove</span><span class="fill"></span></button>
  </span></div>`;
const nearbyRow = d => `<div class="row" data-id="${esc(d.id)}" data-name="${esc(d.name)}" data-kind="${esc(d.kind)}">
  <span class="title">${esc(d.name || "Unnamed device")}</span>
  <span class="muted">${esc(d.kind)}</span>
  <span class="ops"><button class="btn small pair"><span class="label">Pair</span></button></span></div>`;
const visibleRows = list => $$(".row", list).filter(r => r.style.display !== "none").length;
const countPaired = () => setText($("#pairedCount"), visibleRows($("#paired")));
const countSaved = () => setText($("#savedCount"), visibleRows($("#savedList")));

async function loadBt() {
  try {
    const [radio, paired] = await Promise.all([call("bt_radio"), call("bt_paired")]);
    BT = radio; renderRadio();
    $("#paired").innerHTML = paired.map(pairedRow).join("");
    countPaired();
  } catch (e) { setMsg($("#btMsg"), e.message, true); }
}
// the Bluetooth tab label follows whichever radio is in use
function renderRadio() {
  const act = BT.radios.find(r => r.key === BT.active), other = BT.radios.find(r => r.key !== BT.active);
  setText($("#btRadio"), act ? act.name : "no radio");
  setText($("#btOther"), other ? `The ${other.name} radio is turned off.` : "");
  setText($("#btLabel"), act && act.version ? `Bluetooth ${act.version}` : "Bluetooth");
  const b = $("#tryRadio");
  b.hidden = !other;
  if (other) swap(b, `Use ${other.key === "builtin" ? "built-in" : SHORT(other.key)} radio`);
  b.disabled = !BT.can_switch;
  if (!BT.can_switch) setMsg($("#btMsg"), "Bluetooth radio switching needs administrator rights.");
}
$("#tryRadio").addEventListener("click", async function () {
  const other = BT && BT.radios.find(r => r.key !== BT.active);
  if (!other || this.disabled) return;
  try {
    await busy(this, "Switching…", call("bt_switch", other.key));
    setMsg($("#btMsg"), `Switched to the ${other.name} radio. Paired devices reconnect on their own.`);
  } catch (e) { setMsg($("#btMsg"), e.message, true); }
  try { BT = await call("bt_radio"); renderRadio(); } catch (e) { setMsg($("#btMsg"), e.message, true); }
});
$("#paired").addEventListener("click", async e => {
  const b = e.target.closest(".conn"); if (!b || b.disabled) return;
  const r = b.closest(".row"), on = $(".st", r).classList.contains("ok");
  try {
    await busy(b, on ? "Disconnecting…" : "Connecting…", call(on ? "bt_disconnect" : "bt_connect", r.dataset.id), { after: on ? "Connect" : "Disconnect" });
    const st = $(".st", r);
    st.className = `st ${on ? "muted" : "state ok"}`;
    setText(st, on ? r.dataset.kind : "Connected");
  } catch (err) { setMsg($("#btMsg"), err.message, true); }
});
$("#btSearch").addEventListener("click", async function () {
  try {
    const found = await busy(this, "Searching…", call("bt_nearby"), { prog: $("#btProg") });
    const have = new Set($$("#nearby .row").map(r => r.dataset.id));
    found.filter(d => !have.has(d.id)).forEach((d, i) => setTimeout(() => addEl($("#nearby"), nearbyRow(d)), reduce ? 0 : i * 60));
    if (!found.length) setMsg($("#btMsg"), "No devices in pairing mode were found.");
  } catch (e) { setMsg($("#btMsg"), e.message, true); }
});
// pairing moves the device from Nearby into Paired
$("#nearby").addEventListener("click", async e => {
  const b = e.target.closest(".pair"); if (!b || b.disabled) return;
  const r = b.closest(".row");
  try { await busy(b, "Pairing…", call("bt_pair", r.dataset.id)); }
  catch (err) { return setMsg($("#btMsg"), err.message, true); }
  removeEl(r);
  let d = { id: r.dataset.id, name: r.dataset.name, kind: r.dataset.kind, connected: false };
  try {
    const paired = await call("bt_paired");
    d = paired.find(x => x.id === d.id) || paired.find(x => x.name === d.name) || d;
  } catch { /* keep the row we know */ }
  addEl($("#paired"), pairedRow(d));
  countPaired();
});

// ================= Saved =================
function savedRow(s) {
  const all = INFO.adapters.map(a => a.key), missing = all.filter(k => !s.on.includes(k));
  const where = all.length > 1 && !missing.length ? "Both adapters" : `${NAME(s.on[0])} only`;
  const copy = missing.length ? `<button class="btn small copy" data-src="${esc(s.on[0])}" data-dst="${esc(missing[0])}"><span class="label">Copy to ${esc(missing[0] === "builtin" ? "built-in" : SHORT(missing[0]))}</span></button>` : "";
  return `<div class="row" data-ssid="${esc(s.ssid)}">
  <span class="title">${esc(s.ssid)}</span>
  <span class="muted where">${esc(where)}</span>
  <span class="pw"><span class="secret">••••••••</span><button class="link reveal"><span class="label">Show</span></button></span>
  <span class="ops">${copy}
    <button class="btn small hold"><span class="label">Hold to delete</span><span class="fill"></span></button>
  </span></div>`;
}
async function loadSaved() {
  try {
    SAVED = await call("saved");
    $("#savedList").innerHTML = SAVED.map(savedRow).join("");
    countSaved();
  } catch (e) { setMsg($("#savedMsg"), e.message, true); }
}
$("#savedList").addEventListener("click", async e => {
  const show = e.target.closest(".reveal");
  if (show) {
    const row = show.closest(".row");
    if (show.dataset.open) { show.dataset.open = ""; scramble($(".secret", row), "••••••••"); return swap(show, "Show"); }
    try {
      const p = await call("password", row.dataset.ssid);
      show.dataset.open = "1"; scramble($(".secret", row), p || "(no password)"); swap(show, "Hide");
    } catch (err) { setMsg($("#savedMsg"), err.message, true); }
    return;
  }
  const cp = e.target.closest(".copy"); if (!cp || cp.disabled) return;
  const row = cp.closest(".row");
  try { await busy(cp, "Copying…", call("copy_profile", row.dataset.ssid, cp.dataset.src, cp.dataset.dst)); }
  catch (err) { return setMsg($("#savedMsg"), err.message, true); }
  setText($(".where", row), "Both adapters");
  removeEl(cp);
  setMsg($("#savedMsg"), `Copied ${row.dataset.ssid} to the ${NAME(cp.dataset.dst)}.`);
});

// ================= hold to confirm =================
document.addEventListener("pointerdown", e => {
  const b = e.target.closest(".hold"); if (!b || b.disabled) return;
  b.classList.add("holding");
  b._a = anime.waapi.animate($(".fill", b), {
    clipPath: ["inset(0 100% 0 0)", "inset(0 0% 0 0)"], duration: HOLD_MS, ease: "linear",
    onComplete: () => { b._a = null; b.classList.remove("holding"); confirmHold(b); },
  });
});
["pointerup", "pointerleave", "pointercancel"].forEach(t => document.addEventListener(t, e => {
  const b = e.target.closest && e.target.closest(".hold");
  if (!b || !b._a || (t === "pointerleave" && e.target !== b)) return; // pointerleave also fires for the label inside
  b._a.cancel(); b._a = null; b.classList.remove("holding");
  anime.waapi.animate($(".fill", b), { clipPath: "inset(0 100% 0 0)", duration: 200, ease });
}, true));
// the row only goes once the backend confirms; on failure it stays and says why
async function confirmHold(b) {
  const row = b.closest(".row"), saved = !!row.closest("#savedList"), msg = saved ? $("#savedMsg") : $("#btMsg");
  const label = saved ? row.dataset.ssid : $(".title", row).textContent;
  b.disabled = true;
  try { await (saved ? call("delete_profile", row.dataset.ssid) : call("bt_remove", row.dataset.id)); }
  catch (e) {
    b.disabled = false;
    anime.waapi.animate($(".fill", b), { clipPath: "inset(0 100% 0 0)", duration: 200, ease });
    return setMsg(msg, e.message, true);
  }
  removeEl(row, () => { countPaired(); countSaved(); });
  setMsg(msg, saved ? `Deleted ${label}.` : `Removed ${label}.`);
}

// ================= charts (dataviz rules: thin marks, one axis, values lead in tooltips) =================
// smallest "nice" number >= v, for axis tops
const nice = v => { const p = 10 ** Math.floor(Math.log10(v)); return [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map(m => m * p).find(s => s >= v); };
const pathOf = pts => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");

// shared tooltip; labels go in via textContent (names can come from the air)
const tip = $("#tip");
function showTip(x, y, rows, head) {
  tip.replaceChildren();
  if (head) { const h = document.createElement("div"); h.className = "n"; h.textContent = head; tip.append(h); }
  rows.forEach(r => {
    const d = document.createElement("div"); d.className = "row2";
    const k = document.createElement("i"); k.className = "key"; k.style.background = r.c;
    const b = document.createElement("b"); b.textContent = r.v;
    const n = document.createElement("span"); n.className = "n"; n.textContent = r.n;
    d.append(k, b, n); tip.append(d);
  });
  tip.style.display = "block";
  tip.style.left = `${Math.min(innerWidth - tip.offsetWidth - 8, x + 14)}px`;
  tip.style.top = `${Math.max(8, y - tip.offsetHeight - 10)}px`;
}
const hideTip = () => { tip.style.display = "none"; };

// crosshair for line charts: snaps to the nearest sample; arrow keys when focused.
// Each chart sets svg._m = { n, x(i), top, bottom, index(px), rows(i) -> [{c, v, n, y}], head(i) }.
function crosshair(svg) {
  let idx = null;
  const clear = () => { svg.querySelector(".hover")?.remove(); hideTip(); idx = null; };
  const show = (i, cx, cy) => {
    const m = svg._m; if (!m || !m.n) return;
    idx = i = Math.max(0, Math.min(m.n - 1, i));
    let g = svg.querySelector(".hover");
    if (!g) { g = document.createElementNS("http://www.w3.org/2000/svg", "g"); g.setAttribute("class", "hover"); svg.append(g); }
    const x = m.x(i), rows = m.rows(i), box = svg.getBoundingClientRect();
    g.innerHTML = `<line class="cross" x1="${x}" x2="${x}" y1="${m.top}" y2="${m.bottom}"/>`
      + rows.filter(r => r.y != null).map(r => `<circle class="end" cx="${x}" cy="${r.y}" r="4" fill="${r.c}"/>`).join("");
    showTip(cx ?? box.left + x, cy ?? box.top + m.top, rows, m.head(i));
  };
  svg.addEventListener("pointermove", e => { if (svg._m) show(svg._m.index(e.clientX - svg.getBoundingClientRect().left), e.clientX, e.clientY); });
  svg.addEventListener("pointerleave", clear);
  svg.addEventListener("focus", () => show(svg._m ? svg._m.n - 1 : 0));
  svg.addEventListener("blur", clear);
  svg.addEventListener("keydown", e => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault(); show((idx ?? svg._m.n - 1) + (e.key === "ArrowRight" ? 1 : -1));
  });
}
const busyChart = svg => svg.matches(":hover") || document.activeElement === svg;

// ---------- last test: throughput, one series, download then upload ----------
const TP_N = 40;  // chart capacity: speed.py takes at most 28 download + 12 upload samples
const tpTime = i => `${(i * 0.2).toFixed(1)} s`; // one sample every 0.2 s
let live = null;  // the test that is running: {key, samples, split}
window.onSpeedSample = s => {  // pushed by Python (api.py _push_sample) while a test runs
  if (!live) return;
  if (s.phase === "up" && live.split == null) live.split = live.samples.length;
  live.samples.push(s.v);
  drawTp(live.samples, live.key, { split: live.split ?? live.samples.length });
};
function drawTp(samples, key, { draw, split } = {}) {
  const svg = $("#tp"), W = svg.clientWidth; if (!W) return;
  const H = 220, L = 30, R = 10, T = 8, B = 24;
  split = Math.min(split ?? samples.length, samples.length);
  const max = nice(Math.max(40, ...Object.values(RESULTS).flatMap(r => r.samples || []), ...samples) * 1.1); // one scale for both adapters
  const x = i => L + i * (W - L - R) / (TP_N - 1), y = v => T + (1 - v / max) * (H - T - B);
  const pts = samples.map((v, i) => [x(i), y(v)]);
  const c = COLOR(key), splitX = x((samples.length > split ? split : 28) - 0.5);
  let s = [0, max / 2, max].map(v => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>
      <text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("");
  s += `<line class="grid" x1="${splitX}" x2="${splitX}" y1="${T}" y2="${H - B}"/>
    <text class="tick" x="${(L + splitX) / 2}" y="${H - 6}" text-anchor="middle">Download</text>
    <text class="tick" x="${(splitX + W - R) / 2}" y="${H - 6}" text-anchor="middle">Upload</text>`;
  if (!samples.length && !live) s += `<text class="tick" x="${W / 2}" y="${H / 2}" text-anchor="middle">No test yet. Press Run test.</text>`;
  // download and upload are separate measurements: one segment each, never joined
  const phases = [pts.slice(0, split), pts.slice(split)].filter(p => p.length > 1);
  s += phases.map(p => `<path class="area" fill="${c}" d="${pathOf(p)}L${p[p.length - 1][0]},${y(0)}L${p[0][0]},${y(0)}Z"/>
      <path class="line" stroke="${c}" d="${pathOf(p)}"/>`).join("");
  if (pts.length) { const last = pts[pts.length - 1]; s += `<circle class="end" cx="${last[0]}" cy="${last[1]}" r="4" fill="${c}"/>`; }
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.height = `${H}px`;
  svg.innerHTML = s;
  svg._m = { n: samples.length, x, top: T, bottom: H - B, index: px => Math.round((px - L) / ((W - L - R) / (TP_N - 1))),
    rows: i => [{ c, v: `${samples[i]} Mbps`, n: i < split ? "Download" : "Upload", y: y(samples[i]) }],
    head: i => `${NAME(key)}, ${tpTime(i)}` };
  if (draw && !reduce && phases.length) { // the curve draws itself on, download then upload
    $$(".line", svg).forEach((l, i) => anime.animate(anime.createDrawable(l), { draw: ["0 0", "0 1"], duration: 400, delay: i * 300, ease }));
    anime.animate($$(".area, .end", svg), { opacity: [0, 1], duration: 300, delay: 300, ease });
  }
}

// ---------- both adapters: small multiples, each metric on its own scale ----------
const METRICS = [
  { k: "down", name: "Download", unit: "Mbps" },
  { k: "up", name: "Upload", unit: "Mbps" },
  { k: "link", name: "Link rate", unit: "Mbps" },
  { k: "ping", name: "Ping", unit: "ms", note: "lower is better" },
];
let barsShown = false;
function drawBars() {
  const keys = INFO ? INFO.adapters.map(a => a.key) : [];
  const old = new Map($$("#bars .brow").map(r => [r.dataset.id, $(".bar", r).style.width]));
  $("#bars").innerHTML = METRICS.map(m => {
    const vals = keys.map(k => (RESULTS[k] || {})[m.k]);
    const max = Math.max(1, ...vals.filter(v => typeof v === "number")) * 1.35; // headroom for the tip label
    return `<div class="metric"><div class="mname">${m.name}${m.note ? `, ${m.note}` : ""}</div>${keys.map((k, i) => {
      const v = vals[i], text = typeof v === "number" ? `${v} ${m.unit}` : "No test yet";
      return `<div class="brow" data-id="${esc(k)}-${m.k}" data-k="${esc(k)}" data-m="${m.name}" data-v="${esc(text)}">
        <span class="track"><span class="bar" style="background:${COLOR(k)};width:${typeof v === "number" ? (v / max * 100).toFixed(1) : 0}%"></span>
        <span class="v">${esc(text)}</span></span></div>`;
    }).join("")}</div>`;
  }).join("");
  if (reduce) return;
  $$("#bars .brow").forEach((r, i) => {
    const bar = $(".bar", r), to = bar.style.width;
    if (!barsShown) anime.animate(bar, { width: ["0%", to], duration: 400, delay: i * 30, ease }); // first view only
    else if (old.has(r.dataset.id) && old.get(r.dataset.id) !== to) anime.animate(bar, { width: [old.get(r.dataset.id), to], duration: 300, ease });
  });
  barsShown = true;
}
$("#bars").addEventListener("pointermove", e => {
  const r = e.target.closest(".brow"); if (!r) return hideTip();
  showTip(e.clientX, e.clientY, [{ c: COLOR(r.dataset.k), v: r.dataset.v, n: NAME(r.dataset.k) }], r.dataset.m);
});
$("#bars").addEventListener("pointerleave", hideTip);

function renderResults() {
  $("#results").innerHTML = (INFO ? INFO.adapters : []).map(a => {
    const r = RESULTS[a.key];
    const cells = r ? [`${r.link ?? "–"} Mbps`, `${r.ping} ms`, `${r.down} Mbps`, `${r.up} Mbps`] : ["–", "–", "–", "–"];
    return `<tr data-adapter="${esc(a.key)}"><td>${esc(a.name)}</td>${cells.map(c => `<td class="num">${esc(c)}</td>`).join("")}</tr>`;
  }).join("");
  const at = Object.values(RESULTS).map(r => r.at).sort().pop();
  $("#measured").textContent = at ? `measured ${at}` : "no tests yet";
}
function showReadouts() {
  const r = RESULTS[activeKey()];
  $$(".readout .big").forEach((el, i) => setText(el, r ? [r.ping, r.down, r.up][i] : "–"));
}

// ---------- signal strength: every adapter, a reading every 2 s ----------
function drawSig(extra) {
  const svg = $("#sig"), W = svg.clientWidth; if (!W || !INFO) return;
  const keys = INFO.adapters.map(a => a.key);
  // 50-100%: a line chart may start above zero, and this is where signal lives
  const H = 150, L = 36, R = 96, T = 8, B = 22, step = (W - L - R) / (SIG_N - 1);
  const n = Math.max(1, ...keys.map(k => (sig[k] || []).length));
  const off = (extra ? SIG_N + 1 : SIG_N) - n;  // newest reading lands on the right edge (one step beyond while sliding in)
  const x = i => L + (i + off) * step, y = v => T + (1 - (Math.max(50, v) - 50) / 50) * (H - T - B);
  const line = vals => { let d = "", pen = false; vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; }); return d; };
  let s = `<defs><clipPath id="sigclip"><rect x="${L}" y="0" width="${W - L - R}" height="${H}"/></clipPath></defs>`;
  s += [50, 75, 100].map(v => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>
    <text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`).join("");
  s += `<text class="tick" x="${L}" y="${H - 4}">2 min ago</text><text class="tick" x="${W - R}" y="${H - 4}" text-anchor="end">now</text>`;
  s += `<g clip-path="url(#sigclip)"><g class="shift">${keys.map(k => `<path class="line" stroke="${COLOR(k)}" d="${line(sig[k] || [])}"/>`).join("")}</g></g>`;
  // end dots + labels at the newest reading; labels drop to the legend if they would collide
  const xEnd = L + (SIG_N - 1) * step;
  const ends = keys.map(k => { const a = sig[k] || []; return { k, v: a[a.length - 1] }; }).filter(e => e.v != null).map(e => ({ ...e, yy: y(e.v) }));
  const apart = ends.length < 2 || Math.abs(ends[0].yy - ends[1].yy) >= 14;
  s += ends.map(e => `<circle class="end" cx="${xEnd}" cy="${e.yy}" r="4" fill="${COLOR(e.k)}"/>`
    + (apart ? `<text class="lab" x="${xEnd + 10}" y="${e.yy + 4}">${esc(SHORT(e.k))} ${e.v}%</text>` : "")).join("");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.height = `${H}px`;
  svg.innerHTML = s;
  svg._m = { n: SIG_N, x: i => L + i * step, top: T, bottom: H - B, index: px => Math.round((px - L) / step),
    rows: i => keys.map(k => { const a = sig[k] || [], v = a[a.length - SIG_N + i]; return { c: COLOR(k), v: v === undefined ? "No reading yet" : v === null ? "Not connected" : `${v}%`, n: NAME(k), y: v == null ? null : y(v) }; }),
    head: i => i === SIG_N - 1 ? "Now" : `${(SIG_N - 1 - i) * 2} s ago` };
  if (extra && !reduce) { // slide the lines left by one step, then settle
    anime.animate($(".shift", svg), { x: [0, -step], duration: 400, ease: "linear", onComplete: () => { trimSig(); drawSig(); } });
  }
}

// table views: built when opened, from the same data the charts draw
$$("details.tv").forEach(d => d.addEventListener("toggle", () => {
  if (!d.open) return $("table", d)?.remove();
  const t = document.createElement("table");
  const row = (cells, tag = "td") => { const tr = t.insertRow(); cells.forEach(c => { const el = document.createElement(tag); el.textContent = c; tr.append(el); }); };
  if (d.dataset.table === "tp") {
    const r = RESULTS[activeKey()];
    row(["Time", "Phase", "Mbps"], "th");
    if (r) r.samples.forEach((v, i) => row([tpTime(i), i < r.split ? "Download" : "Upload", v]));
  } else {
    const keys = INFO ? INFO.adapters.map(a => a.key) : [];
    row(["Time", ...keys.map(NAME)], "th");
    for (let i = SIG_N - 1; i >= 0; i--) row([i === SIG_N - 1 ? "Now" : `${(SIG_N - 1 - i) * 2} s ago`,
      ...keys.map(k => { const a = sig[k] || [], v = a[a.length - SIG_N + i]; return v == null ? "–" : `${v}%`; })]);
  }
  d.append(t);
}));

function drawSpeed() {
  const key = activeKey(), r = RESULTS[key];
  drawTp(r ? r.samples : [], key, { split: r && r.split }); drawBars(); drawSig();
}
crosshair($("#tp")); crosshair($("#sig"));

$("#runTest").addEventListener("click", async function () {
  const key = activeKey(); if (!key) return;
  live = { key, samples: [], split: null };
  // the old curve steps back, then the new one is drawn as samples arrive
  anime.animate($$("#tp .line, #tp .area, #tp .end"), { opacity: 0, duration: 150, ease });
  try {
    RESULTS[key] = await busy(this, "Testing…", call("speed_test", key), { prog: $("#spProg") });
    live = null;
    renderResults(); showReadouts(); drawBars();
    drawTp(RESULTS[key].samples, key, { split: RESULTS[key].split });
  } catch (e) {
    live = null;
    setMsg($("#speedMsg"), e.message, true);
    const r = RESULTS[key];
    drawTp(r ? r.samples : [], key, { split: r && r.split });
  }
});

// ================= navigation =================
// Wi-Fi tab: Nearby | Saved. Content swaps instantly; only the highlight slides.
function view(name, instant) {
  $("#vNearby").hidden = name !== "nearby";
  $("#vSaved").hidden = name !== "saved";
  $$(".tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.view === name));
  slide($(".tab-ind"), $(`.tabs button[data-view="${name}"]`), instant);
  if (name === "nearby") { drawMaps(); highlight(selected); markSel(true); } // hidden elements measure 0
  if (name === "saved" && INFO) loadSaved();
}
$$(".tabs button").forEach(b => b.addEventListener("click", () => view(b.dataset.view)));
const nearbyShown = () => !$("#wifi").hidden && !$("#vNearby").hidden;

function go(id, instant) {
  $$("main section").forEach(s => s.hidden = s.id !== id);
  $$("nav button").forEach(b => b.dataset.go === id ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  slide($(".nav-ind"), $(`nav button[data-go="${id}"]`), instant);
  if (id === "wifi") { slide($(".tab-ind"), $(".tabs button[aria-selected='true']"), true); if (nearbyShown()) view("nearby", true); }
  if (id === "bt" && INFO) loadBt();
  if (id === "speed") drawSpeed();
  hideTip();
}
$$("nav button").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
document.addEventListener("keydown", e => {
  const ids = ["wifi", "bt", "speed"];
  if (e.ctrlKey && e.key >= "1" && e.key <= "3") { e.preventDefault(); go(ids[e.key - 1], true); } // keyboard: no motion
  if (e.key === "Enter" && nearbyShown() && !pw.open && !e.target.closest("button")) $("#connect").click();
});
addEventListener("resize", () => {
  if (nearbyShown()) { drawMaps(); highlight(selected); markSel(true); }
  if (!$("#speed").hidden) drawSpeed();
  slide($(".ad-ind"), activeAdapter(), true);
  slide($(".nav-ind"), $("nav button[aria-current]"), true);
  if (!$("#wifi").hidden) slide($(".tab-ind"), $(".tabs button[aria-selected='true']"), true);
});

// ================= start =================
const hash = location.hash.slice(1);
go(["wifi", "bt", "speed"].includes(hash) ? hash : "wifi", true);
if (hash === "saved") view("saved", true); // old link: Saved now lives inside Wi-Fi
setTimeout(() => { if (!INFO && !MOCK) setMsg($("#wifiMsg"), "Waiting for the app. To preview in a browser, open index.html?mock.", true); }, 3000);
(async function start() {
  try { INFO = await call("app_info"); }
  catch (e) { return setMsg($("#wifiMsg"), e.message, true); }
  if (!INFO.adapters.length) return setMsg($("#wifiMsg"), "No Wi-Fi adapters found. Plug in the Unigen dongle.", true);
  renderRail();
  RESULTS = await call("speed_results").catch(() => ({}));
  renderResults(); showReadouts();
  setText($("#speed h1"), `Speed on ${NAME(activeKey())}`);
  setText($("#tpSub"), `${NAME(activeKey())}, Mbps`);
  await poll();
  await loadNetworks(false).catch(e => setMsg($("#wifiMsg"), e.message, true));
  loadSaved(); loadBt();
  if (!$("#speed").hidden) drawSpeed();
  setInterval(poll, 2000);
  setInterval(tickAge, 1000);
  setInterval(() => { if (nearbyShown() && !pw.open) loadNetworks(false).catch(e => setMsg($("#wifiMsg"), e.message, true)); }, 10000);
})();
</script>
```

- [ ] **Step 6: Run the UI tests and the contract test and check they pass.** Run `py -3.10 -m pytest tests/ui tests/test_api.py`.
Expected: `27 passed` (15 UI tests and 12 API tests, now including `test_mock_api_matches_python_api`).

- [ ] **Step 7: Look at it.** Run `py -3.10 -m http.server 8765 --bind 127.0.0.1 --directory ui` in the background. Open `http://127.0.0.1:8765/index.html?mock` and click through all three tabs. Compare with the approved prototype screenshots: the same layout, colors and motion. Note the server's process ID when you start it, and stop **only that process**. Never use `taskkill /IM python.exe`.

- [ ] **Step 8: Commit**

```bash
git add ui/index.html ui/mock-api.js tests/ui
git commit -m "feat(ui): page talks to the Python API; mock for preview; Playwright UI tests"
```

### Task 9: Launcher, elevation and desktop shortcut

**Files:**
- Create: `app.py`, `UnigenManager.pyw`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `api.Api`, `api.DATA_DIR`, `winrun.ps`.
- Produces:
  - `app.is_admin() -> bool` and `app.should_relaunch(argv, admin) -> bool`
  - `app.relaunch_as_admin(argv, *, shell_execute=None) -> bool`: False means the user declined
  - `app.install_shortcut(run=None) -> None` and `app.main(argv=None) -> int`
  - Command-line flags: `--no-elevate` (set on the elevated copy, so it can never loop), `--debug` (pywebview developer tools), `--install-shortcut`

- [ ] **Step 1: Write the failing tests** in `tests/test_app.py`.

```python
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
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_app.py`.
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Implement `app.py` and `UnigenManager.pyw`**

`app.py`:
```python
"""Start Unigen Manager: elevate (radio switching needs it), log to app.log, open the window."""
import ctypes, logging, subprocess, sys
from pathlib import Path

from api import Api, DATA_DIR

ROOT = Path(__file__).resolve().parent
UI = ROOT / "ui" / "index.html"
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
    if should_relaunch(argv, admin) and relaunch_as_admin(argv):
        return 0  # the elevated copy takes over; if declined, carry on without admin
    setup_logging()
    import webview
    api = Api(admin=admin)
    window = webview.create_window("Unigen Manager", url=str(UI), js_api=api, width=1180, height=780,
                                   min_size=(940, 620), background_color="#16202B")
    api._window = window
    webview.start(debug="--debug" in argv, private_mode=True)
    return 0
```

`UnigenManager.pyw`:
```python
import sys

import app

sys.exit(app.main())
```

- [ ] **Step 4: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/test_app.py`.
Expected: `5 passed`.

- [ ] **Step 5: Smoke-test the real window.** Run `py -3.10 UnigenManager.pyw --no-elevate --debug` (this opens the app without asking for admin).
Expected:
  - The window opens with the dark design.
  - The side menu lists **Unigen dongle** ("Wi-Fi 6, Bluetooth 5.4") and **Built-in MediaTek** ("Wi-Fi 6, Bluetooth 5.2").
  - Wi-Fi shows real nearby networks.
  - The Bluetooth button shows the admin note.
  - The developer tools console shows no red errors.

  Close the window.

- [ ] **Step 6: Commit**

```bash
git add app.py UnigenManager.pyw tests/test_app.py
git commit -m "feat(app): elevated launcher, pywebview window, desktop shortcut"
```

---

### Task 10: Read-only hardware tests

These run against the real adapters but change nothing: no connects, no radio switches, no pairing, and no password printed.

**Files:**
- Create: `tests/hardware/__init__.py` (empty), `tests/hardware/test_readonly.py`

**Interfaces:**
- Consumes: `wifi`, `bt`, `speed`, `api.Api`.
- Produces: `py -3.10 -m pytest -m hardware`, which passes on this PC with both adapters present.

- [ ] **Step 1: Write the tests**

```python
"""Read-only checks against this PC's real adapters. Run: py -3.10 -m pytest -m hardware"""
import os
from pathlib import Path

import pytest

import api, bt, speed, wifi

pytestmark = pytest.mark.hardware


def by_key():
    return {wifi.adapter_key(i["description"]): i for i in wifi.interfaces()}


def test_both_wifi_adapters_present():
    assert {"unigen", "builtin"} <= set(by_key())


def test_drivers_report_wifi_6():
    drv = wifi.drivers()
    for i in by_key().values():
        assert wifi.wifi_standard(drv[i["name"]]["radio_types"]) == "Wi-Fi 6"


def test_networks_and_profiles_parse():
    for i in by_key().values():
        assert isinstance(wifi.networks(i["name"]), list)
    assert any(wifi.profiles().values())


def test_trigger_scan_accepted():
    for i in by_key().values():
        wifi.trigger_scan(i["guid"])


def test_bluetooth_radios_and_versions():
    rs = {r["key"]: r for r in bt.radios()}
    assert rs["unigen"]["version"] == "5.4" and rs["builtin"]["version"] == "5.2"
    assert any(r["ok"] for r in rs.values())


def test_paired_devices_list():
    devs = bt.devices(paired=True)
    assert all(set(d) == {"id", "name", "connected", "kind", "address"} for d in devs)


def test_ping_router_from_connected_adapter():
    i = next((i for i in by_key().values() if i["state"] == "connected"), None)
    if i is None:
        pytest.skip("no adapter is connected")
    a = speed.addresses(i["name"])
    assert speed.ping(a["ip"], a["gateway"], count=3) >= 0


def test_api_end_to_end_reads():
    a = api.Api()
    for name, args in [("app_info", ()), ("adapters", ()), ("saved", ()), ("bt_radio", ()), ("networks", ("unigen",))]:
        r = getattr(a, name)(*args)
        assert r["ok"], (name, r)


def test_saved_password_readable_without_printing_it():
    a = api.Api()
    first = a.saved()["data"][0]["ssid"]
    r = a.password(first)
    readable = r["ok"] and isinstance(r["data"], str) and len(r["data"]) > 0
    assert readable, "could not read a saved password"  # never put the value in the assertion


def test_launcher_present():
    assert Path(os.environ["WINDIR"], "pyw.exe").exists()
```

- [ ] **Step 2: Run them.** Run `py -3.10 -m pytest -m hardware -v`.
Expected: all pass. `test_ping_router_from_connected_adapter` may be skipped if no adapter is connected. If a WinRT call fails in `bt.ps1`, fix the type-loading line it names and re-run. These tests are the only automated check of `bt.ps1` against real Windows.

- [ ] **Step 3: Commit**

```bash
git add tests/hardware
git commit -m "test: read-only hardware checks against the real adapters"
```

---

### Task 11: Shared front end (`ui/shared.css`, `ui/shared.js`)

The main window and the tray widget must look and move the same, so tokens, base styles, buttons, the Python bridge and the anime.js helpers live in one place.

**Files:**
- Create: `ui/shared.css`, `ui/shared.js`, `tests/test_shared_frontend.py`
- Modify: `ui/index.html` (delete what moved; link the shared files)

**Interfaces:**
- Consumes: the Task 8 version of `ui/index.html`.
- Produces, global names in `shared.js` that both pages use:
  - DOM helpers: `$`, `$$`, `esc`
  - Bridge: `MOCK`, `apiReady`, `call(name, ...args)`
  - Motion: `ease`, `reduce`, `slide(ind, to, instant)` (horizontal when `ind.dataset.axis === "x"`), `swap(btn, text)`, `busy(btn, label, work, {prog, after})`, `arrive(el)`, `setText(el, text)`, `setMsg(el, text, isErr, {clearAfter = 0} = {})`, `scramble(el, text)`, `pop(dot, on)` (does nothing if unchanged)
  - Lists: `relayout(list, mutate, params)`, `removeEl(el, done)`, `addEl(list, html)`
  - Press feedback for `.btn, .adapter, nav button, .tabs button, .link, .seg button, .icon-btn`

- [ ] **Step 1: Write the failing test** in `tests/test_shared_frontend.py`.

```python
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui"
HELPERS = ["function call(", "function slide(", "function swap(", "async function busy(", "function arrive(",
           "function setText(", "function setMsg(", "function scramble(", "function pop(", "function relayout(",
           "function removeEl(", "function addEl("]


def test_index_uses_shared_files():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="shared.css">' in html
    assert '<script src="shared.js"></script>' in html
    assert "--panel:" not in html  # tokens live only in shared.css
    assert not any(h in html for h in HELPERS)  # helpers live only in shared.js


def test_shared_files_define_everything():
    css = (UI / "shared.css").read_text(encoding="utf-8")
    js = (UI / "shared.js").read_text(encoding="utf-8")
    assert "--panel: #16202B" in css and "--uni: #9085e9" in css and ".btn.primary" in css
    assert all(h in js for h in HELPERS)
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_shared_frontend.py`.
Expected: FAIL. `shared.css` doesn't exist yet.

- [ ] **Step 3: Create `ui/shared.css`**

```css
/* Shared by index.html (main window) and widget.html (tray widget): tokens, base, buttons, messages. */
:root {
  --panel: #16202B;
  --raised: #1F2C3A;
  --line: #2A3A4B;
  --ink: #E6EDF3;
  --muted: #8DA0B3;
  --b24: #E3A33B;
  --b5: #4FB3C8;
  --ok: #5CC08A;
  --err: #F07167;
  /* adapter identity in charts; validated on --raised (dataviz validator, dark: CVD dE 16.0, normal 19.7) */
  --uni: #9085e9;
  --bi: #d55181;

  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --display: "Bahnschrift", "Segoe UI", sans-serif;
  --body: "Segoe UI", system-ui, sans-serif;
}

* { box-sizing: border-box; }
button { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--b5); outline-offset: 2px; }
.num { font-family: var(--display); font-variant-numeric: tabular-nums; }

.btn {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  background: var(--raised);
  border-radius: 6px;
  padding: 8px 16px;
  cursor: pointer;
}
.btn.primary { background: var(--ink); color: var(--panel); border-color: var(--ink); font-weight: 600; }
.btn:disabled { opacity: 0.5; cursor: default; }
.btn.small { padding: 5px 11px; font-size: 13px; }
.btn .label, .link .label { display: inline-block; }

.msg { color: var(--muted); }
.msg.err { color: var(--err); }

@media (hover: hover) and (pointer: fine) {
  .btn:not(:disabled):hover { border-color: var(--muted); }
}
```

- [ ] **Step 4: Create `ui/shared.js`.** Move these blocks out of `ui/index.html` **unchanged**, in this order:
  - the first three lines (`const $ …`, `const $$ …`, `const esc …`)
  - the whole `// ================= bridge to Python (api.py) =================` section
  - the whole `// ================= motion components (anime.js) =================` section, up to and including `function addEl(…) {…}`

  Leave `const HOLD_MS = 1500;` in `index.html`. Then make exactly these three changes inside `shared.js`:

```js
// header comment at the very top of shared.js
// Shared by index.html and widget.html: DOM helpers, the bridge to Python (api.py), and the anime.js motion components.
```

```js
// PRESSABLE now also covers the widget's controls
const PRESSABLE = ".btn, .adapter, nav button, .tabs button, .link, .seg button, .icon-btn";
```

```js
// setMsg: optional clearAfter (ms) lets the widget's confirmations fade away; 0 keeps the message
function setMsg(el, text, isErr, { clearAfter = 0 } = {}) {
  clearTimeout(el._t);
  el.textContent = text;
  el.classList.toggle("err", !!isErr);
  anime.waapi.animate(el, { opacity: [0, 1], duration: 150, ease });
  if (clearAfter) el._t = setTimeout(() => anime.waapi.animate(el, { opacity: 0, duration: 200, ease,
    onComplete: () => { el.textContent = ""; el.style.opacity = ""; } }), clearAfter);
}

// pop: a status dot changes state (does nothing if it didn't change)
function pop(dot, on) {
  if (dot.classList.contains("on") === on) return;
  dot.classList.toggle("on", on);
  if (!reduce) anime.animate(dot, { scale: [1.8, 1], duration: 250, ease });
}
```
(These replace the moved `setMsg` and `pop`.)

- [ ] **Step 5: Edit `ui/index.html`.**
  - **Delete from its `<style>`:** the whole `:root { … }` block; the rules `* { box-sizing: border-box; }`, `button { font: inherit; color: inherit; }`, `:focus-visible { … }`, `.num { … }`, `.msg { … }` and `.msg.err { … }`; the `.btn { … }` block; and the rules `.btn.primary`, `.btn:disabled`, `.btn.small` and `.btn .label, .link .label`. Inside `@media (hover: hover) and (pointer: fine)`, also delete the line `.btn:not(:disabled):hover { border-color: var(--muted); }`.
  - **Link the shared stylesheet:** add `<link rel="stylesheet" href="shared.css">` on the line before `<style>`.
  - **Load the shared script:** change the script tags to:
```html
<script src="vendor/anime.umd.min.js"></script>
<script src="mock-api.js"></script>
<script src="shared.js"></script>
<script>
```
  - **Remove the moved blocks** from the inline script, keeping `const HOLD_MS = 1500;`.

- [ ] **Step 6: Run the tests and check they pass.** The UI tests catch anything the move broke. Run `py -3.10 -m pytest tests/test_shared_frontend.py tests/ui`.
Expected: `17 passed` (2 shared-file tests and 15 UI tests).

- [ ] **Step 7: Commit**

```bash
git add ui/shared.css ui/shared.js ui/index.html tests/test_shared_frontend.py
git commit -m "refactor(ui): shared tokens, bridge and anime.js helpers for main window and widget"
```

---

### Task 12: Tray icon, widget window, start-with-Windows, single instance

**Files:**
- Create: `tray.py`, `tests/test_tray.py`
- Modify: `requirements.txt`, `api.py`, `app.py`, `tests/test_api.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `winrun.run`, `winrun.CmdError`; `api.Api`; `app.relaunch_as_admin`, `app.is_admin`, `app.setup_logging`.
- Produces:
  - **In `tray.py`:**
    - Constants: `TASK = "Unigen Manager"`, `WIDGET_W = 342`, plus `MUTEX` and `SHOW_EVENT` (names that tests can replace)
    - Screen position: `work_area() -> (l, t, r, b)` in physical pixels; `scale() -> float`; `widget_position(area, width, height, scale=1.0, margin=12) -> (x, y)` in pywebview's logical pixels
    - Start with Windows: `launch_command(root, windir=…) -> str`, `startup_enabled() -> bool`, `set_startup(on: bool, root) -> None`
    - Single instance: `claim_instance() -> handle | None`, `release(handle)`, `signal_show() -> bool`, `watch_show(on_show, stop: threading.Event)`
    - Icon: `icon_image(size=64) -> PIL.Image`, and `class Tray(*, toggle_widget, open_main, quit_app, root, status)` with `.start()` and `.stop()`
  - **New public `Api` methods**, all wrapped in the usual envelope:
    - `use_adapter(key) -> {"key", "ssid"}`
    - `open_main() -> None`, `hide_widget() -> None`
    - `widget_fit(height_css_px) -> None`
  - **New private `Api` members**, used by `app.py`:
    - `_widget`: the widget window, next to `_window`
    - `_show_main()`, `_toggle_widget()`, `_status() -> str`
    - `_push_sample` now pushes to both windows
  - **`app.main`:** single instance first, then elevation; `--tray` starts with the main window hidden; closing the main window hides it; *Quit* in the tray exits.

- [ ] **Step 1: Add the dependencies.** Append to `requirements.txt`, then run `py -3.10 -m pip install -r requirements-dev.txt`.

```
pystray==0.19.5
Pillow==12.3.0
```

- [ ] **Step 2: Write the failing tray tests** in `tests/test_tray.py`.

```python
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
```

- [ ] **Step 3: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/test_tray.py`.
Expected: FAIL with `ModuleNotFoundError: No module named 'tray'`.

- [ ] **Step 4: Implement `tray.py`**

```python
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
```

- [ ] **Step 5: Run the tray tests and check they pass.** Run `py -3.10 -m pytest tests/test_tray.py`.
Expected: `7 passed`.

- [ ] **Step 6: Write the failing API tests.** Append to `tests/test_api.py`:

```python
import tray


def connected_both_disconnected_unigen():
    return wifi.parse_interfaces(fixture("interfaces.txt"))  # built-in on HOME-5G, Unigen disconnected


def test_use_adapter_joins_other_network_then_disconnects_it(hw, monkeypatch):
    calls = []
    monkeypatch.setattr(wifi, "connect", lambda iface, ssid, **kw: calls.append(("connect", iface, ssid, kw["saved"])) or {"rx": 433.0})
    monkeypatch.setattr(wifi, "disconnect", lambda iface: calls.append(("disconnect", iface)))
    monkeypatch.setattr(wifi, "copy_profile", lambda *a: calls.append(("copy",) + a))
    assert api.Api().use_adapter("unigen") == {"ok": True, "data": {"key": "unigen", "ssid": "HOME-5G"}}
    assert calls == [("connect", "Wi-Fi 2", "HOME-5G", True), ("disconnect", "Wi-Fi")]  # Unigen already has the profile


def test_use_adapter_copies_missing_profile_first(hw, monkeypatch):
    calls = []
    prof = wifi.parse_profiles(fixture("profiles.txt"))
    prof["Wi-Fi 2"].remove("HOME-5G")
    monkeypatch.setattr(wifi, "profiles", lambda: prof)
    monkeypatch.setattr(wifi, "connect", lambda iface, ssid, **kw: calls.append(("connect", iface)) or {})
    monkeypatch.setattr(wifi, "disconnect", lambda iface: calls.append(("disconnect", iface)))
    monkeypatch.setattr(wifi, "copy_profile", lambda ssid, src, dst: calls.append(("copy", ssid, src, dst)))
    api.Api().use_adapter("unigen")
    assert calls[0] == ("copy", "HOME-5G", "Wi-Fi", "Wi-Fi 2")


def test_use_adapter_needs_a_connection(hw, monkeypatch):
    ifs = wifi.parse_interfaces(fixture("interfaces.txt"))
    ifs[0]["state"] = "disconnected"
    monkeypatch.setattr(wifi, "interfaces", lambda: ifs)
    assert api.Api().use_adapter("unigen") == {"ok": False, "error": "Neither adapter is connected. Connect to a network first."}


class FakeWin:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name,) + a)


def test_widget_fit_keeps_bottom_right_above_taskbar(monkeypatch):
    monkeypatch.setattr(tray, "work_area", lambda: (0, 0, 1920, 1040))
    monkeypatch.setattr(tray, "scale", lambda: 1.0)
    a = api.Api()
    a._widget = FakeWin()
    assert a.widget_fit(480.4)["ok"]
    assert a._widget.calls == [("resize", 342, 480), ("move", 1566, 548)]


def test_toggle_ignores_the_click_that_blurred_it(monkeypatch):
    a = api.Api()
    a._widget = FakeWin()
    a._toggle_widget()  # opens
    assert ("show",) in a._widget.calls
    a.hide_widget()  # the widget hides itself when it loses focus (the tray click does that)...
    a._widget.calls.clear()
    a._toggle_widget()  # ...so this same click must not reopen it
    assert ("show",) not in a._widget.calls


def test_open_main_shows_window_and_hides_widget():
    a = api.Api()
    a._window, a._widget = FakeWin(), FakeWin()
    assert a.open_main()["ok"]
    assert ("show",) in a._window.calls and ("hide",) in a._widget.calls
```

- [ ] **Step 7: Implement the `Api` additions in `api.py`.** Add `import tray` next to the other imports. In `__init__`, add `self._widget, self._widget_shown, self._hid_at = None, False, 0.0`. Replace `_push_sample`, and add the methods below inside the class.

```python
    def _push_sample(self, phase, value):
        script = "window.onSpeedSample && window.onSpeedSample(" + json.dumps({"phase": phase, "v": value}) + ")"
        for w in (self._window, self._widget):
            if w is not None:
                w.evaluate_js(script)

    # ---- windows (private ones are called from app.py / the tray) ----
    def _show_main(self):
        if self._window is not None:
            self._window.show()
            self._window.restore()

    def _toggle_widget(self):
        if self._widget is None:
            return
        if self._widget_shown:
            self.hide_widget()
        elif time.monotonic() - self._hid_at > 0.3:  # the tray click that just blurred it should not reopen it
            self._widget_shown = True
            self._widget.show()
            self._widget.evaluate_js("window.onWidgetShown && window.onWidgetShown()")

    def _status(self):
        for a in self.adapters().get("data") or []:
            if a["state"] == "connected":
                return f"{a['name']}: {a['ssid']}, {a['signal']}%"
        return "Unigen Manager: not connected"

    @_envelope
    def open_main(self):
        self._show_main()
        if self._widget is not None:
            self.hide_widget()

    @_envelope
    def hide_widget(self):
        if self._widget is not None:
            self._widget.hide()
        self._widget_shown, self._hid_at = False, time.monotonic()

    @_envelope
    def widget_fit(self, height):
        """The widget page reports its height; keep its bottom-right corner just above the taskbar."""
        if self._widget is None:
            return
        h = int(max(200, min(900, round(height))))
        x, y = tray.widget_position(tray.work_area(), tray.WIDGET_W, h, tray.scale())
        self._widget.resize(tray.WIDGET_W, h)
        self._widget.move(x, y)

    @_envelope
    def use_adapter(self, key):
        """Wi-Fi uses this adapter: it joins the network the other one is on, then the other disconnects."""
        ifs = self._ifaces()
        target = self._iface(key)
        others = [i for k, i in ifs.items() if k != key]
        if target.get("state") == "connected":
            net = target.get("ssid")
        else:
            net = next((o.get("ssid") for o in others if o.get("state") == "connected"), None)
        if not net:
            raise wifi.WifiError("Neither adapter is connected. Connect to a network first.")
        if not (target.get("state") == "connected" and target.get("ssid") == net):
            names = wifi.profiles().get(target["name"], [])
            if net not in names and wifi.profile_name(net) not in names:  # reuse the other adapter's saved password
                src = next(o for o in others if o.get("ssid") == net)
                wifi.copy_profile(net, src["name"], target["name"])
            wifi.connect(target["name"], net, saved=True)
        for o in others:
            if o.get("state") == "connected":
                wifi.disconnect(o["name"])
        return {"key": key, "ssid": net}
```

Note: `hide_widget` is wrapped in `_envelope`, so calling it from `_toggle_widget` returns an envelope. That's harmless. The window calls themselves happen either way.

- [ ] **Step 8: Write the failing app tests.** In `tests/test_app.py`, replace `test_main_opens_window_with_api`, and append the three new tests:

```python
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
```

- [ ] **Step 9: Update `app.py`.** Add `import threading` and `import tray` to the imports, add `WIDGET = ROOT / "ui" / "widget.html"`, and replace `main` with:

```python
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
    stop = threading.Event()

    def on_closing():  # closing only hides; Quit is in the tray menu
        if stop.is_set():
            return True
        main_win.hide()
        return False

    main_win.events.closing += on_closing
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
```

Also update `test_main_hands_over_to_elevated_copy` in `tests/test_app.py`: add `monkeypatch.setattr(app.tray, "claim_instance", lambda: "HANDLE")` and `monkeypatch.setattr(app.tray, "release", lambda h: None)` at its start.

- [ ] **Step 10: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/test_tray.py tests/test_api.py tests/test_app.py`.
Expected: `33 passed` (7 tray, 18 API, 8 app). `test_mock_api_matches_python_api` fails until Task 13 adds the four new methods to `mock-api.js`, so add `--deselect tests/test_api.py::test_mock_api_matches_python_api` for now. Expected with the deselect: `32 passed, 1 deselected`.

- [ ] **Step 11: Commit**

```bash
git add requirements.txt tray.py api.py app.py tests/test_tray.py tests/test_api.py tests/test_app.py
git commit -m "feat(tray): notification-area icon, widget window, start with Windows, single instance"
```

---

### Task 13: Wire the widget to the API, plus widget UI tests

**Files:**
- Modify: `ui/widget.html` (replaced entirely: the approved prototype's look and motion, with real data), `ui/mock-api.js` (four new methods), `tests/test_shared_frontend.py`
- Create: `tests/ui/test_widget.py`

**Interfaces:**
- Consumes:
  - `shared.css` and `shared.js` (Task 11)
  - The `Api` methods `adapters`, `networks`, `connect`, `disconnect`, `use_adapter`, `bt_radio`, `bt_paired`, `bt_switch`, `speed_test`, `speed_results`, `open_main`, `hide_widget` and `widget_fit`
  - Python pushes: `window.onWidgetShown()` and `window.onSpeedSample({phase, v})`
- Produces:
  - `widget.html?mock`: a preview with a fake taskbar, used by the UI tests
  - Inside the app: the widget fills its window and reports its height through `widget_fit`

- [ ] **Step 1: Write the failing widget UI tests** in `tests/ui/test_widget.py`.

```python
"""Widget UI tests: ui/widget.html?mock with its fake taskbar, in the installed Microsoft Edge."""
import functools, http.server, threading
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.ui
UI = Path(__file__).resolve().parents[2] / "ui"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def base_url():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(UI)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/widget.html?mock"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        yield b
        b.close()


@pytest.fixture
def widget(browser, base_url):
    pages = []

    def _open(hooks=""):
        pg = browser.new_page(viewport={"width": 1000, "height": 760})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.add_init_script("window.MOCK_FAST = true;" + hooks)
        pg.goto(base_url)
        pg.locator("#chevron").click()
        pg.locator("#trayIcon").click()
        expect(pg.locator("#w")).to_be_visible()
        expect(pg.locator(".ad")).to_have_count(2)
        pages.append(pg)
        return pg

    yield _open
    for pg in pages:
        assert pg.errors == []
        pg.close()


def ad(pg, key):
    return pg.locator(f'.ad[data-k="{key}"]')


def test_opens_from_tray_and_shows_live_status(widget):
    pg = widget()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("HOME-5G")
    expect(pg.locator('.seg button[aria-checked="true"]')).to_have_text("Unigen")
    expect(pg.locator("#nets .net")).to_have_count(2)  # saved networks in range on the Unigen dongle
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.4")
    expect(pg.locator("#btDev")).to_have_text("Den Beats Pill")
    pg.mouse.click(100, 100)
    expect(pg.locator("#w")).to_be_hidden()  # like Windows flyouts: clicking elsewhere closes it


def test_use_built_in(widget):
    pg = widget()
    pg.locator('.seg button[data-k="builtin"]').click()
    expect(pg.locator("#wifiMsg")).to_have_text("Wi-Fi now uses the Built-in MediaTek.")
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("Not connected")
    expect(ad(pg, "builtin").locator(".ssid")).to_have_text("HOME-5G")


def test_use_failure_puts_the_switch_back(widget):
    pg = widget('window.MOCK_FAIL = { use_adapter: "Neither adapter is connected. Connect to a network first." };')
    pg.locator('.seg button[data-k="builtin"]').click()
    expect(pg.locator("#wifiMsg")).to_have_text("Neither adapter is connected. Connect to a network first.")
    expect(pg.locator('.seg button[aria-checked="true"]')).to_have_text("Unigen")


def test_disconnect_and_connect_saved(widget):
    pg = widget()
    home = pg.locator("#nets .net").filter(has=pg.get_by_text("HOME-5G", exact=True))
    home.locator("button").click()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("Not connected")
    expect(home.locator("button .label")).to_have_text("Connect")
    home.locator("button").click()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("HOME-5G")


def test_bluetooth_switch(widget):
    pg = widget()
    pg.locator("#btSwitch").click()
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.2")
    expect(pg.locator("#btSwitch .label")).to_have_text("Use Unigen")


def test_speed_test_sparkline(widget):
    pg = widget()
    pg.locator("#run").click()
    expect(pg.locator("#run .label")).to_have_text("Run test", timeout=10000)
    expect(pg.locator("#spark .line")).to_have_count(2)  # download and upload segments
    assert pg.locator("#dn").inner_text() not in ("", "–")


def test_confirmations_fade_errors_stay(widget):
    pg = widget()
    pg.locator("#btSwitch").click()
    expect(pg.locator("#btMsg")).not_to_be_empty()
    expect(pg.locator("#btMsg")).to_be_empty(timeout=6000)
```

Append to `tests/test_shared_frontend.py`:
```python
def test_widget_uses_shared_files():
    html = (UI / "widget.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="shared.css">' in html and '<script src="shared.js"></script>' in html
    assert "--panel:" not in html and not any(h in html for h in HELPERS)
```

- [ ] **Step 2: Run the tests and check they fail.** Run `py -3.10 -m pytest tests/ui/test_widget.py tests/test_shared_frontend.py`.
Expected: FAIL. The prototype doesn't load `mock-api.js` or `shared.js`, so the two `.ad` rows never come from the API.

- [ ] **Step 3: Add the four new methods to `ui/mock-api.js`,** just before `return api;`:

```js
  // tray widget
  def("use_adapter", 1400, key => {
    const t = adapter(key), others = plugged().filter(a => a.key !== key);
    const net = t.state === "connected" ? t.ssid : (others.find(a => a.state === "connected") || {}).ssid;
    if (!net) throw new Error("Neither adapter is connected. Connect to a network first.");
    PROFILES[key].add(net);
    const n = NETS.find(x => x.ssid === net), five = !n || n.aps.some(x => x.b === 5);
    Object.assign(t, { state: "connected", ssid: net, rate: five ? (key === "unigen" ? 433 : 866) : (key === "unigen" ? 144 : 287) });
    others.forEach(a => { a.state = "disconnected"; });
    return { key, ssid: net };
  });
  def("open_main", 0, () => null);
  def("hide_widget", 0, () => null);
  def("widget_fit", 0, () => null);
```

- [ ] **Step 4: Replace `ui/widget.html` entirely**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unigen Manager widget</title>
<link rel="stylesheet" href="shared.css">
<style>
  html, body { height: 100%; margin: 0; }
  body { background: var(--raised); color: var(--ink); font: 14px/1.45 var(--body); overflow: hidden; }

  /* the widget: fills its frameless window inside the app; floats above a fake taskbar in the ?mock preview */
  .widget { width: 100%; background: var(--raised); }
  .widget[hidden] { display: none; }
  header { display: flex; align-items: center; gap: 10px; padding: 12px 12px 10px 14px; }
  header h1 { font: 600 15px/1 var(--display); margin: 0; flex: 1; }
  .logo { width: 18px; height: 18px; flex: none; }
  .icon-btn { width: 28px; height: 28px; display: grid; place-items: center; background: none; border: 0; border-radius: 6px; color: var(--muted); cursor: pointer; }
  .sec { padding: 12px 14px; border-top: 1px solid var(--line); }
  .sec h2 { font: 600 13px/1 var(--display); color: var(--muted); margin: 0 0 8px; }
  .widget .msg { font-size: 12.5px; margin: 6px 0 0; }
  .widget .msg:empty { display: none; }
  .widget .btn { padding: 5px 11px; font-size: 13px; white-space: nowrap; }
  .widget .btn:not(.primary) { background: var(--panel); }

  /* Wi-Fi uses: one sliding highlight between the adapters */
  .uses { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .uses .lbl { color: var(--muted); font-size: 13px; }
  .seg { position: relative; display: flex; gap: 2px; background: var(--panel); border-radius: 7px; padding: 3px; }
  .seg button { position: relative; z-index: 1; background: none; border: 0; cursor: pointer; padding: 4px 12px; border-radius: 5px; color: var(--muted); font: 500 13px var(--display); }
  .seg button[aria-checked="true"] { color: var(--ink); }
  .seg button:disabled { cursor: default; }
  .seg .ind { position: absolute; top: 3px; bottom: 3px; left: 0; background: var(--raised); border-radius: 5px; pointer-events: none; }

  .ad { display: grid; grid-template-columns: 10px 1fr auto; column-gap: 10px; row-gap: 2px; align-items: center; padding: 6px 0; }
  .ad + .ad { border-top: 1px solid var(--line); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .dot.on { background: var(--ok); }
  .ad .name { font: 600 14px/1.3 var(--display); }
  .ad .ssid { text-align: right; font-size: 13px; display: inline-block; }
  .ad .ssid.off { color: var(--muted); }
  .ad .sub { grid-column: 2 / 4; display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12.5px; }
  .ad .sub .rate { margin-left: auto; display: inline-block; }
  .ad .sub .pct { display: inline-block; min-width: 30px; }
  .bars { display: inline-flex; align-items: flex-end; gap: 2px; height: 12px; }
  .bars i { width: 3px; border-radius: 1px; background: var(--line); }
  .bars i:nth-child(1) { height: 4px; } .bars i:nth-child(2) { height: 7px; }
  .bars i:nth-child(3) { height: 10px; } .bars i:nth-child(4) { height: 12px; }
  .bars i.lit { background: var(--ink); opacity: 0.8; }

  .net { display: grid; grid-template-columns: 1fr 38px 104px; gap: 8px; align-items: center; padding: 5px 0; min-height: 36px; }
  .net .title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .net .pct { color: var(--muted); font-size: 12.5px; text-align: right; }
  .net .act { justify-self: end; }
  .empty { color: var(--muted); font-size: 13px; padding: 4px 0; margin: 0; }

  .bt { display: flex; align-items: center; gap: 10px; }
  .bt .ver { font: 600 14px var(--display); white-space: nowrap; display: inline-block; }
  .bt .dev { flex: 1; color: var(--muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }

  .speed { display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: center; }
  .speed .nums { display: flex; align-items: baseline; gap: 8px; white-space: nowrap; }
  .speed .nums b { font: 400 20px/1 var(--display); display: inline-block; }
  .speed .nums .arrow, .speed .nums .unit { color: var(--muted); font-size: 12px; }
  #spark { display: block; width: 100%; height: 28px; overflow: visible; }
  #spark .line { fill: none; stroke-width: 1.5; stroke-linejoin: round; stroke-linecap: round; }
  #spark .area { fill-opacity: 0.1; }

  @media (hover: hover) and (pointer: fine) {
    .icon-btn:hover, .seg button:not(:disabled):hover { color: var(--ink); }
  }

  /* ---------- ?mock preview only: a Windows 10 taskbar to click ---------- */
  body.preview { background: #0E151D; }
  .preview .widget {
    position: fixed; right: 12px; bottom: 52px; width: 340px;
    border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45); overflow: hidden;
  }
  .taskbar { position: fixed; left: 0; right: 0; bottom: 0; height: 40px; background: #101820; border-top: 1px solid #1B2632;
    display: flex; align-items: center; justify-content: flex-end; gap: 2px; padding-right: 8px; }
  .taskbar[hidden], .overflow[hidden], .hint[hidden] { display: none; }
  .tb { height: 40px; min-width: 32px; padding: 0 8px; display: grid; place-items: center; background: none; border: 0; color: #C9D3DC; cursor: pointer; }
  .tb.clock { font-size: 12px; line-height: 1.25; text-align: center; cursor: default; }
  .overflow { position: fixed; bottom: 48px; right: 150px; display: grid; grid-template-columns: repeat(3, 34px); gap: 2px; padding: 6px;
    background: #1A242F; border: 1px solid #2A3644; border-radius: 4px; box-shadow: 0 6px 18px rgba(0, 0, 0, 0.4); }
  .overflow button { height: 34px; display: grid; place-items: center; background: none; border: 0; border-radius: 3px; cursor: pointer; color: #9FB0BF; }
  .hint { position: fixed; left: 16px; top: 14px; color: var(--muted); font-size: 13px; margin: 0; }
  @media (hover: hover) and (pointer: fine) { .tb:hover, .overflow button:hover { background: rgba(255, 255, 255, 0.08); } }
</style>
</head>
<body>

<div class="widget" id="w" role="dialog" aria-label="Unigen Manager">
  <header>
    <svg class="logo" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M2.5 7.5a9 9 0 0 1 13 0" fill="none" stroke="var(--b5)" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M5 10.2a5.4 5.4 0 0 1 8 0" fill="none" stroke="var(--b5)" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="9" cy="13.4" r="1.6" fill="var(--b5)"/>
    </svg>
    <h1>Unigen Manager</h1>
    <button class="icon-btn" id="openApp" aria-label="Open Unigen Manager" title="Open Unigen Manager">
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M8 1.5h4.5V6M12.5 1.5 7.5 6.5M6 12.5H1.5V8M1.5 12.5l5-5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
  </header>
  <div class="sec">
    <div class="uses"><span class="lbl" id="usesLbl">Wi-Fi uses</span><div class="seg" role="radiogroup" aria-labelledby="usesLbl"></div></div>
    <div id="ads"></div>
    <p class="msg" id="wifiMsg"></p>
  </div>
  <div class="sec">
    <h2>Saved networks in range</h2>
    <div id="nets"></div>
    <p class="msg" id="netMsg"></p>
  </div>
  <div class="sec">
    <div class="bt">
      <span class="ver" id="btVer">Bluetooth</span>
      <span class="dev" id="btDev"></span>
      <button class="btn" id="btSwitch"><span class="label">Switch</span></button>
    </div>
    <p class="msg" id="btMsg"></p>
  </div>
  <div class="sec">
    <div class="speed">
      <div class="nums"><span class="arrow">↓</span><b id="dn">–</b><span class="arrow">↑</span><b id="upv">–</b><span class="unit">Mbps</span></div>
      <svg id="spark" aria-label="Speed during the last test"></svg>
      <button class="btn primary" id="run"><span class="label">Run test</span></button>
    </div>
    <p class="msg" id="speedMsg"></p>
  </div>
</div>

<!-- ?mock preview only: a Windows 10 taskbar. Inside the app the widget fills its own window. -->
<p class="hint" id="hint" hidden>Preview: click <b>^</b> on the taskbar, then the Unigen icon.</p>
<div class="overflow" id="overflow" hidden>
  <button aria-label="OneDrive"><svg width="16" height="16" viewBox="0 0 16 16"><path d="M4 12h8.5a2.5 2.5 0 0 0 0-5 4 4 0 0 0-7.6-1A3 3 0 0 0 4 12z" fill="none" stroke="currentColor" stroke-width="1.2"/></svg></button>
  <button aria-label="Security"><svg width="16" height="16" viewBox="0 0 16 16"><path d="M8 1.8 3 3.8v4c0 3 2.2 5.2 5 6.4 2.8-1.2 5-3.4 5-6.4v-4z" fill="none" stroke="currentColor" stroke-width="1.2"/></svg></button>
  <button id="trayIcon" aria-label="Unigen Manager">
    <svg width="16" height="16" viewBox="0 0 18 18"><path d="M2.5 7.5a9 9 0 0 1 13 0" fill="none" stroke="#4FB3C8" stroke-width="1.8" stroke-linecap="round"/><path d="M5 10.2a5.4 5.4 0 0 1 8 0" fill="none" stroke="#4FB3C8" stroke-width="1.8" stroke-linecap="round"/><circle cx="9" cy="13.4" r="1.7" fill="#4FB3C8"/></svg>
  </button>
</div>
<div class="taskbar" id="taskbar" hidden>
  <button class="tb" id="chevron" aria-label="Show hidden icons" aria-expanded="false"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M2.5 7.5 6 4l3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg></button>
  <span class="tb"><svg width="16" height="16" viewBox="0 0 16 16"><path d="M1.5 6a9 9 0 0 1 13 0M4 8.7a5.4 5.4 0 0 1 8 0" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="8" cy="11.6" r="1.3" fill="currentColor"/></svg></span>
  <span class="tb"><svg width="16" height="16" viewBox="0 0 16 16"><path d="M2 6h3l4-3v10l-4-3H2z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M11.5 5.5a3.5 3.5 0 0 1 0 5" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg></span>
  <span class="tb clock" id="clock"></span>
</div>

<script src="vendor/anime.umd.min.js"></script>
<script src="mock-api.js"></script>
<script src="shared.js"></script>
<script>
// Tray widget. Inside the app it fills its own frameless window (Python shows it and calls onWidgetShown);
// opened as widget.html?mock it floats above a fake taskbar for preview and tests.
let INFO = null, ADS = [], uses = null, BT = null, RESULTS = {}, live = null, shown = false;
const NAME = k => (INFO && INFO.adapters.find(a => a.key === k) || {}).name || k;
const SHORT = k => ({ unigen: "Unigen", builtin: "Built-in" })[k] || NAME(k);
const COLOR = k => ({ unigen: "var(--uni)", builtin: "var(--bi)" })[k] || "var(--muted)";
const note = (el, text, isErr) => setMsg(el, text, isErr, { clearAfter: isErr ? 0 : 4000 }); // a flyout stays compact
const fail = el => e => note(el, e.message, true);

// ================= Wi-Fi: which adapter carries traffic =================
const level = s => s == null ? 0 : s >= 80 ? 4 : s >= 60 ? 3 : s >= 40 ? 2 : 1;
const bars = s => `<span class="bars" aria-hidden="true">${[1, 2, 3, 4].map(i => `<i class="${i <= level(s) ? "lit" : ""}"></i>`).join("")}</span>`;
function renderAdapters() {
  $(".seg").innerHTML = `<span class="ind" data-axis="x" aria-hidden="true"></span>` + INFO.adapters.map(a =>
    `<button role="radio" aria-checked="false" data-k="${esc(a.key)}">${esc(SHORT(a.key))}</button>`).join("");
  $("#ads").innerHTML = INFO.adapters.map(a => `
    <div class="ad" data-k="${esc(a.key)}">
      <span class="dot"></span><span class="name">${esc(a.name)}</span>
      <span class="ssid off">Checking…</span>
      <span class="sub"><span class="pct num">–</span>${bars(null)}<span class="rate">No link</span></span>
    </div>`).join("");
  $$(".seg button").forEach(b => b.addEventListener("click", () => useAdapter(b)));
}
function markUses(instant) {
  $$(".seg button").forEach(b => b.setAttribute("aria-checked", b.dataset.k === uses));
  const b = $$(".seg button").find(x => x.dataset.k === uses);
  if (b) slide($(".seg .ind"), b, instant);
}
// in place: only values that changed animate
function updateAdapters() {
  for (const row of $$(".ad")) {
    const d = ADS.find(x => x.key === row.dataset.k), on = !!d && d.state === "connected";
    pop($(".dot", row), on);
    const ssid = $(".ssid", row);
    ssid.classList.toggle("off", !on);
    setText(ssid, !d ? "Unplugged" : on ? d.ssid : "Not connected");
    setText($(".pct", row), on ? `${d.signal}%` : "–");
    setText($(".rate", row), on ? `${d.rate} Mbps` : "No link");
    $(".bars", row).outerHTML = bars(on ? d.signal : null);
  }
}
async function poll() {
  ADS = await call("adapters");
  if (!uses || !ADS.some(a => a.key === uses)) uses = (ADS.find(a => a.state === "connected") || ADS[0] || {}).key || null;
  updateAdapters(); markUses(true);
}
async function useAdapter(b) {
  const k = b.dataset.k;
  if (k === uses || b.disabled) return;
  const was = uses;
  $$(".seg button").forEach(x => { x.setAttribute("aria-checked", x === b); x.disabled = true; });
  slide($(".seg .ind"), b);
  note($("#wifiMsg"), `Switching Wi-Fi to the ${NAME(k)}…`);
  try {
    await call("use_adapter", k);
    uses = k;
    await Promise.all([poll(), loadNets(), loadSpeed(true)]);
    note($("#wifiMsg"), `Wi-Fi now uses the ${NAME(k)}.`);
  } catch (e) {
    uses = was; markUses();
    note($("#wifiMsg"), e.message, true);
  } finally {
    $$(".seg button").forEach(x => { x.disabled = false; });
  }
}

// ================= saved networks in range (on the adapter Wi-Fi uses) =================
async function loadNets() {
  if (!uses) return;
  const list = (await call("networks", uses)).networks.filter(n => n.state && !n.hidden).slice(0, 4);
  $("#nets").innerHTML = list.length ? list.map(n => `<div class="net" data-ssid="${esc(n.ssid)}">
      <span class="title">${esc(n.ssid)}</span>
      <span class="pct num">${Math.max(0, ...n.aps.map(a => a.s))}%</span>
      <span class="act">${n.state === "Connected"
        ? `<button class="btn" data-do="disconnect"><span class="label">Disconnect</span></button>`
        : `<button class="btn" data-do="connect"><span class="label">Connect</span></button>`}</span>
    </div>`).join("") : `<p class="empty">No saved networks in range.</p>`;
}
$("#nets").addEventListener("click", async e => {
  const b = e.target.closest("button[data-do]"); if (!b || b.disabled) return;
  const ssid = b.closest(".net").dataset.ssid, connect = b.dataset.do === "connect";
  try {
    await busy(b, connect ? "Connecting…" : "Disconnecting…", connect ? call("connect", uses, ssid, null) : call("disconnect", uses));
    note($("#netMsg"), connect ? `Connected to ${ssid}.` : `Disconnected from ${ssid}.`);
    await Promise.all([poll(), loadNets()]);
  } catch (err) { note($("#netMsg"), err.message, true); }
});

// ================= Bluetooth radio =================
async function loadBt() {
  const [radio, paired] = await Promise.all([call("bt_radio"), call("bt_paired")]);
  BT = radio;
  const act = BT.radios.find(r => r.key === BT.active), other = BT.radios.find(r => r.key !== BT.active);
  const dev = paired.find(d => d.connected);
  setText($("#btVer"), act && act.version ? `Bluetooth ${act.version}` : "Bluetooth");
  setText($("#btDev"), dev ? dev.name : "No device connected");
  const b = $("#btSwitch");
  b.hidden = !other;
  if (other) swap(b, `Use ${other.key === "builtin" ? "built-in" : SHORT(other.key)}`);
  b.disabled = !BT.can_switch;
  b.title = BT.can_switch ? "" : "Bluetooth radio switching needs administrator rights.";
}
$("#btSwitch").addEventListener("click", async function () {
  const other = BT && BT.radios.find(r => r.key !== BT.active);
  if (!other || this.disabled) return;
  try {
    await busy(this, "Switching…", call("bt_switch", other.key));
    note($("#btMsg"), `Bluetooth now uses the ${other.name} radio.`);
  } catch (e) { note($("#btMsg"), e.message, true); }
  loadBt().catch(fail($("#btMsg")));
});

// ================= mini speed test: sparkline of the last test on the adapter Wi-Fi uses =================
const TP_N = 40;  // speed.py takes at most 28 download + 12 upload samples
const pathOf = pts => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
function drawSpark(samples, k, { draw, split } = {}) {
  const svg = $("#spark"), W = svg.clientWidth, H = 28; if (!W) return;
  split = Math.min(split ?? samples.length, samples.length);
  const max = Math.max(40, ...Object.values(RESULTS).flatMap(r => r.samples || []), ...samples) * 1.05;
  const x = i => 1 + i * (W - 2) / (TP_N - 1), y = v => 2 + (1 - v / max) * (H - 4);
  const pts = samples.map((v, i) => [x(i), y(v)]);
  // download and upload are separate measurements: one segment each, never joined
  const segs = [pts.slice(0, split), pts.slice(split)].filter(p => p.length > 1);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = segs.map(p => `<path class="area" fill="${COLOR(k)}" d="${pathOf(p)}L${p[p.length - 1][0]},${H}L${p[0][0]},${H}Z"/>
    <path class="line" stroke="${COLOR(k)}" d="${pathOf(p)}"/>`).join("");
  if (draw && !reduce && segs.length) {
    $$(".line", svg).forEach((l, i) => anime.animate(anime.createDrawable(l), { draw: ["0 0", "0 1"], duration: 350, delay: i * 250, ease }));
    anime.animate($$(".area", svg), { opacity: [0, 1], duration: 250, delay: 250, ease });
  }
}
async function loadSpeed(draw) {
  RESULTS = await call("speed_results");
  const r = RESULTS[uses];
  setText($("#dn"), r ? r.down : "–");
  setText($("#upv"), r ? r.up : "–");
  drawSpark(r ? r.samples : [], uses, { draw, split: r && r.split });
}
window.onSpeedSample = s => {  // pushed by Python (api.py _push_sample) while a test runs
  if (!live) return;
  if (s.phase === "up" && live.split == null) live.split = live.samples.length;
  live.samples.push(s.v);
  drawSpark(live.samples, live.key, { split: live.split ?? live.samples.length });
};
$("#run").addEventListener("click", async function () {
  if (!uses || this.disabled) return;
  live = { key: uses, samples: [], split: null };
  try {
    const r = await busy(this, "Testing…", call("speed_test", uses));
    live = null;
    RESULTS[uses] = r;
    setText($("#dn"), r.down); setText($("#upv"), r.up);
    drawSpark(r.samples, uses, { split: r.split });
    note($("#speedMsg"), `Measured on the ${NAME(uses)}.`);
  } catch (e) { live = null; note($("#speedMsg"), e.message, true); }
});

$("#openApp").addEventListener("click", () => call("open_main").catch(fail($("#wifiMsg"))));

// ================= open / close =================
const W = $("#w");
async function refresh(draw) {
  await poll();
  await Promise.all([loadNets(), loadBt(), loadSpeed(draw)]);
}
function animateOpen() {
  anime.animate(W, reduce ? { opacity: [0, 1], duration: 150, ease } : { opacity: [0, 1], y: [8, 0], duration: 180, ease });
}
window.onWidgetShown = () => {  // Python calls this right after showing the window
  shown = true; animateOpen(); markUses(true);
  refresh(true).catch(fail($("#wifiMsg")));
};
function hideWidget() {
  if (!shown) return;
  shown = false;
  anime.animate(W, { opacity: 0, ...(reduce ? {} : { y: 4 }), duration: 120, ease, onComplete: () => {
    if (MOCK) { if (!shown) W.hidden = true; } else call("hide_widget").catch(() => {});
    W.style.opacity = ""; W.style.transform = "";
  } });
}
addEventListener("keydown", e => { if (e.key === "Escape") hideWidget(); });
if (!MOCK) {
  addEventListener("blur", hideWidget);  // like Windows flyouts: losing focus closes it
  new ResizeObserver(() => { if (shown) call("widget_fit", Math.ceil(W.getBoundingClientRect().height)).catch(() => {}); }).observe(W);
}
setInterval(() => { if (shown) { poll().catch(fail($("#wifiMsg"))); loadNets().catch(fail($("#netMsg"))); } }, 3000);

// ================= ?mock preview: fake taskbar with the ^ overflow =================
if (MOCK) {
  document.body.classList.add("preview");
  $("#taskbar").hidden = false; $("#hint").hidden = false; W.hidden = true;
  const tick = () => { const d = new Date(); $("#clock").innerHTML = `${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}<br>${d.toLocaleDateString()}`; };
  tick(); setInterval(tick, 30000);
  $("#chevron").addEventListener("click", e => {
    e.stopPropagation();
    const ov = $("#overflow"); ov.hidden = !ov.hidden;
    $("#chevron").setAttribute("aria-expanded", !ov.hidden);
  });
  $("#trayIcon").addEventListener("click", e => {
    e.stopPropagation();
    $("#overflow").hidden = true; $("#chevron").setAttribute("aria-expanded", "false");
    if (shown) return hideWidget();
    W.hidden = false; window.onWidgetShown();
  });
  document.addEventListener("click", e => {
    if (!e.target.closest("#w, #overflow, #chevron")) { hideWidget(); $("#overflow").hidden = true; }
  });
}

(async function start() {
  try {
    INFO = await call("app_info");
    renderAdapters();
    await refresh(false);
  } catch (e) { note($("#wifiMsg"), e.message, true); }
})();
</script>
</body>
</html>
```

- [ ] **Step 5: Run the tests and check they pass.** Run `py -3.10 -m pytest tests/ui tests/test_shared_frontend.py tests/test_api.py`.
Expected: `43 passed` (15 main-window and 7 widget UI tests, 3 shared-file tests, 18 API tests, now including the contract test).

- [ ] **Step 6: Try the real tray.** Run `py -3.10 UnigenManager.pyw --debug` and choose **Yes** at the admin prompt.
Expected:
  - The cyan icon appears in the **^** overflow, and hovering shows the adapter tooltip.
  - Left-click opens the widget 12 px above the taskbar at the bottom right. Clicking elsewhere closes it. Clicking the icon again does **not** flicker it open.
  - The right-click menu works. *Start with Windows* creates the task (`schtasks /Query /TN "Unigen Manager"`).
  - Closing the main window hides it; *Quit* exits.
  - Running `py -3.10 UnigenManager.pyw` a second time brings the existing window forward. You may see one admin prompt, because the running copy is elevated.

  If the widget sits in the wrong place on a scaled display, the fix belongs in `tray.widget_position` and `tray.scale`: correct the conversion there and add a test case for that scale.

- [ ] **Step 7: Commit**

```bash
git add ui/widget.html ui/mock-api.js tests/ui/test_widget.py tests/test_shared_frontend.py
git commit -m "feat(widget): tray widget on the real API; preview and Playwright tests"
```

---

### Task 14: Full verification and manual checklist

**Files:**
- Create: `docs/superpowers/test-reports/manual-checklist.md`
- Modify: `docs/superpowers/specs/2026-10-13-unigen-manager-design.md` ("Testing" section)

**Interfaces:**
- Consumes: the whole app.
- Produces: a signed-off test report.

- [ ] **Step 1: Run every automated suite.**
  - `py -3.10 -m pytest`. Expected: `115 passed` (93 unit and contract tests: winrun 6, parsers 9, Wi-Fi actions 19, speed 8, Bluetooth 15, API 18, app 8, tray 7, shared front end 3; plus 22 UI tests: 15 for the main window and 7 for the widget). Hardware tests are excluded by default.
  - `py -3.10 -m pytest -m hardware`. Expected: `10 passed`, or `9 passed, 1 skipped` when no adapter is connected.

  Paste both summaries into the report in Step 2.

- [ ] **Step 2: Write `docs/superpowers/test-reports/manual-checklist.md`.** The person at the PC runs it with you: the checks need the UAC prompt, real devices and unplugging the dongle. Fill in **Result** from what is actually observed.

```markdown
# Unigen Manager: manual test checklist

Date: <date> · Build: <git rev-parse --short HEAD>

## Automated results
- `py -3.10 -m pytest`: <paste summary>
- `py -3.10 -m pytest -m hardware`: <paste summary>

## State-changing checks (on the real PC)

| # | Steps | Expected | Result |
|---|---|---|---|
| 1 | `py -3.10 app.py --install-shortcut`, then double-click "Unigen Manager" on the desktop and choose **Yes** | The window opens. Side menu: Unigen dongle (Wi-Fi 6, Bluetooth 5.4), Built-in MediaTek (Wi-Fi 6, Bluetooth 5.2). Tabs: Wi-Fi 6, Bluetooth 5.4, Speed | |
| 2 | Close the app, start it again and choose **No** at the prompt | The app still opens. On Bluetooth, the radio button is disabled and the admin note shows | |
| 3 | Wi-Fi with Unigen selected: select the connected network, then **Disconnect** | The status column clears, the side menu shows "Not connected" and the dot turns grey within 2 s | |
| 4 | Select HOME-5G (Saved), then **Connect** | "Connected to HOME-5G." within 15 s. The channel map fills in | |
| 5 | Turn on a phone hotspot with a known password. Select it, then **Connect** and enter a wrong 8+ character password | After at most 15 s: "Couldn't connect to <hotspot>. Check the password." `netsh wlan show profiles` does **not** list the hotspot | |
| 6 | Connect to the hotspot again with the right password | Connected. The hotspot now shows as Saved | |
| 7 | Wi-Fi › Saved: **Show** on HOME-5G | The password matches the one Windows shows in Settings. **Hide** puts the dots back | |
| 8 | Saved: **Copy to built-in** on Maple House | The row changes to "Both adapters". `netsh wlan show profiles` lists it under interface "Wi-Fi" | |
| 9 | Saved: hold **Hold to delete** on the hotspot for 1.5 s | The row slides away and the count drops. netsh no longer lists it on either adapter | |
| 10 | Speed: **Run test** on each adapter | The curve draws live, download then upload. Numbers are close to the 12 Oct manual test (Unigen about 50/12, Built-in about 53/31 Mbps). Results survive closing and reopening the app | |
| 11 | Bluetooth (as admin): **Use built-in radio** | The label changes to Bluetooth 5.2. Device Manager shows the MediaTek radio enabled and the Unigen radio disabled. If the MediaTek radio doesn't start within 10 s: "…didn't start. Switched back to the Unigen dongle." and Unigen works again | |
| 12 | **Use Unigen radio** | Back to Bluetooth 5.4. Paired devices reconnect | |
| 13 | Put a phone in pairing mode, then **Search**, then **Pair** | The phone appears under Nearby. After pairing it moves to Paired and the count goes up. Windows Settings lists it | |
| 14 | Hold **Hold to remove** on that phone | It disappears from Paired and from Windows Bluetooth settings | |
| 15 | Turn on the JBL Go 3 (or the spike device), then **Connect**, then **Disconnect** | If the spike said WORKS: the speaker connects, then disconnects. If FAILS: Windows Bluetooth settings open, with the explanation message | |
| 16 | Unplug the Unigen dongle while the app is open, then plug it back in | No crash. The side menu shows "Unplugged". Selecting it shows "The Unigen dongle isn't plugged in." After replugging it returns within a few seconds | |
| 17 | Windows Settings › Ease of Access › Display › turn off "Show animations", then restart the app | Motion becomes simple fades. Nothing slides or scales | |
| 18 | Click **^** on the taskbar, then the cyan Unigen icon | The widget rises in just above the taskbar at the bottom right. Clicking elsewhere closes it. Clicking the icon again doesn't make it flicker | |
| 19 | Widget: **Wi-Fi uses › Built-in** (then back to Unigen) | The chosen adapter joins the network and the other disconnects. The main window's side menu agrees | |
| 20 | Widget: Disconnect / Connect a saved network, **Use built-in** Bluetooth, **Run test** | Each one works as in the main window. The sparkline draws live. Confirmations fade after 4 s | |
| 21 | Tray right-click › **Start with Windows**, then sign out and back in | The tray icon appears at sign-in with **no** admin prompt. `schtasks /Query /TN "Unigen Manager"` lists the task | |
| 22 | Close the main window, then double-click the desktop shortcut | The main window comes back (one copy only; there may be one admin prompt). Tray › **Quit** removes the icon and ends the process | |
| 23 | Check `%LOCALAPPDATA%\UnigenManager\app.log` after all of the above | No passwords anywhere in the file | |

## Sign-off
- Failures and follow-ups:
- Tested by:
```

- [ ] **Step 3: Run the checklist with the user and fill in every Result.** Fix any failure as its own commit, re-run the affected automated suite, then re-check that row.

- [ ] **Step 4: Point the spec's "Testing" section at the real suite.** Replace the two bullets under `## Testing` with:

```markdown
- Automated: `py -3.10 -m pytest`. This covers unit tests (parsers against real captured netsh output, commands, profile XML, Bluetooth switch and rollback, the speed sampler against a local server), API contract tests (including mock-api.js ↔ Api method names), and Playwright UI tests against `?mock` in Microsoft Edge.
- Hardware, read-only: `py -3.10 -m pytest -m hardware`.
- State-changing: `docs/superpowers/test-reports/manual-checklist.md`, run with the user.
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/test-reports/manual-checklist.md docs/superpowers/specs/2026-10-13-unigen-manager-design.md
git commit -m "test: full verification report and manual checklist"
```
