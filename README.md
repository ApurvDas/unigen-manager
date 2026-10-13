# Unigen Manager

A Windows app for managing a Unigen USB Wi-Fi 6 + Bluetooth dongle (AIC8800D80) and a laptop's built-in Wi-Fi card (MediaTek MT7921) side by side. It has a dark-mode window for Wi-Fi, Bluetooth and speed tests, plus an always-on widget in the taskbar's notification area (the **^** flyout).

![Wi-Fi](docs/screenshots/wifi.png)

| Bluetooth | Speed | Tray widget |
|---|---|---|
| ![Bluetooth](docs/screenshots/bluetooth.png) | ![Speed](docs/screenshots/speed.png) | ![Widget](docs/screenshots/widget.png) |

## Features

- **Two adapters, one window:** see both Wi-Fi cards with their network, link speed, signal and standards (Wi-Fi 6, Bluetooth 5.4 / 5.2), read from the hardware.
- **Wi-Fi:**
  - Nearby networks, with a channel map for 2.4 and 5 GHz.
  - Connect and disconnect, and add new WPA2 or open networks with a password.
  - Rescan on demand.
  - **Saved networks:** show a password, copy a network to the other adapter, and hold-to-delete.
- **Bluetooth:**
  - Paired and nearby devices: pair, remove, connect and disconnect audio devices.
  - Switch between the dongle's and the built-in Bluetooth radio, with automatic switch-back if the new radio doesn't start.
- **Speed:** a live throughput chart for each adapter, both adapters compared side by side, and signal strength over the last 2 minutes.
- **Tray widget:**
  - Live status, and a "Wi-Fi uses" switch that moves the connection to one adapter.
  - Quick connect to saved networks, the Bluetooth radio switch, and a mini speed test.
  - Optional **Start with Windows**.
- **Motion:** anime.js animations that respect Windows' "Show animations" setting.

## Requirements

- Windows 10 or 11, **set to English** (the app reads `netsh` output)
- **Python 3.10** from [python.org](https://www.python.org/downloads/release/python-31011/), with the `py` launcher (installed by default)
- Microsoft Edge WebView2 Runtime (already present on up-to-date Windows 10/11)
- Administrator rights for Bluetooth radio switching and Start with Windows (the app asks when it starts)

## Download

Download the code with either:
- **Git:** `git clone https://github.com/ApurvDas/unigen-manager.git`
- **ZIP:** on GitHub, choose **Code ▸ Download ZIP**, then extract it, for example to `C:\Users\<you>\UnigenManager`.

## Setup

Open a terminal in the project folder:

```powershell
py -3.10 -m pip install -r requirements.txt
```

That installs pywebview, pystray and Pillow.

### Run

```powershell
py -3.10 UnigenManager.pyw
```

Choose **Yes** at the Windows prompt. If you choose **No**, the app still runs, but Bluetooth radio switching is turned off.

Create a desktop shortcut (optional):

```powershell
py -3.10 app.py --install-shortcut
```

**Start with Windows:** right-click the tray icon and tick **Start with Windows**. This registers a scheduled task that starts the tray at sign-in, with no prompt. It keeps running on battery.

**Command-line options:**

| Flag | Effect |
|---|---|
| `--tray` | Start with only the tray icon (the main window stays hidden) |
| `--no-elevate` | Don't ask for administrator rights |
| `--debug` | Open WebView developer tools |
| `--install-shortcut` | Create the desktop shortcut and exit |

**What happens on close:** closing the main window hides it, and the tray icon keeps running. Use the tray menu's **Quit** to exit. Opening the app again while it's running brings the existing window forward. Only one copy runs at a time.

App data such as the last speed test results and `app.log` is stored in `%LOCALAPPDATA%\UnigenManager\`.

## Preview the UI without the app

Both pages include a mock API with sample data:

```powershell
py -3.10 -m http.server 8765 --directory ui
```

Then open:
- `http://127.0.0.1:8765/index.html?mock` for the main window
- `http://127.0.0.1:8765/widget.html?mock` for the tray widget (click **^**, then the cyan icon)

## Development and tests

```powershell
py -3.10 -m pip install -r requirements-dev.txt
py -3.10 -m pytest                  # unit, contract and UI tests (UI tests drive the installed Microsoft Edge)
py -3.10 -m pytest -m hardware      # read-only checks against the real adapters (changes nothing)
```

State-changing checks (connecting, pairing, radio switching, unplugging the dongle) are in [docs/superpowers/test-reports/manual-checklist.md](docs/superpowers/test-reports/manual-checklist.md).

### Project layout

| Path | What it does |
|---|---|
| `UnigenManager.pyw` | Double-click launcher |
| `app.py` | Admin prompt, single instance, main window, widget window, tray |
| `api.py` | Everything the pages call (`window.pywebview.api`); plain-language errors |
| `wifi.py` | `netsh` parsing, connect/disconnect, saved profiles, Windows scan request |
| `bt.py`, `bt.ps1` | Bluetooth radios, devices, pairing, audio connect (PowerShell WinRT + `bthprops.cpl`) |
| `speed.py` | Ping and per-adapter sampled download/upload |
| `tray.py` | Notification-area icon, widget placement, Start with Windows, single instance |
| `winrun.py` | The only place that starts processes (argument lists only, no shell) |
| `ui/` | `index.html` (main window), `widget.html` (tray widget), `shared.css`/`shared.js`, `mock-api.js`, anime.js |
| `tests/` | pytest suites, Playwright UI tests and read-only hardware tests |
| `docs/superpowers/` | Design spec, implementation plan and test checklist |

## Security notes

- Network and device names come from the air, so they're always shown as text and passed to Windows tools as separate arguments, never as command text.
- Wi-Fi passwords are never logged. They only touch the disk inside temporary folders that are deleted right away.
- **Start with Windows runs the app with administrator rights at sign-in, without a prompt.** The app's files live in your user folder. Anything that can change those files could therefore gain administrator rights at your next sign-in. Leave **Start with Windows** off if that trade-off isn't right for you.

## Known limitations

- Windows must be in English. On other languages, the app shows "Is Windows set to English?" instead of wrong data.
- Network names with non-English characters may display incorrectly and can't be connected from the app.
- New WPA3 and Enterprise networks have to be added in Windows settings. Connecting to them once they're saved works.
- **Bluetooth Connect/Disconnect for audio devices:**
  - The app toggles the device's audio services.
  - If Windows refuses, the app opens Windows Bluetooth settings instead.
  - This is still to be confirmed on real hardware (checklist row 24).
- An adapter plugged in after the app starts appears after the app restarts.
