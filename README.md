<div align="center">

<img src="docs/logo.svg" width="88" alt="Unigen Manager logo">

# Unigen Manager

**Manage the Unigen USB Wi-Fi 6 + Bluetooth dongle and a laptop's built-in Wi-Fi card side by side, from one dark-mode window and an always-on tray widget.**

<sub>An unofficial, independent app. Not made, endorsed or supported by Unigen. "Unigen" is their trademark, used here only to say which dongle this works with.</sub>

![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0E151D?style=flat-square&logo=windows&logoColor=4FB3C8)
![Python 3.10](https://img.shields.io/badge/Python-3.10-0E151D?style=flat-square&logo=python&logoColor=4FB3C8)
![pywebview](https://img.shields.io/badge/UI-pywebview%20%2B%20WebView2-0E151D?style=flat-square)
![anime.js](https://img.shields.io/badge/motion-anime.js%204-0E151D?style=flat-square)
![Tests](https://img.shields.io/badge/tests-336%20passing-5CC08A?style=flat-square)

<a href="https://github.com/ApurvDas/unigen-manager/releases/latest/download/UnigenManager.exe"><img src="https://img.shields.io/badge/Download-UnigenManager.exe%20%C2%B7%2033%20MB-4FB3C8?style=for-the-badge&logo=windows&logoColor=white" alt="Download UnigenManager.exe" height="44"></a>

**Plug and play:** download, double-click, done. No installer, no Python.

[Quick start](#quick-start) · [Features](#features) · [Usage](#usage) · [Run from source](#run-from-source) · [Development](#development) · [Security](#security)

<img src="docs/screenshots/wifi.png" alt="The Wi-Fi screen: both adapters in the side menu, a 2.4 and 5 GHz channel map, and the list of nearby networks" width="900">

</div>

## Quick start

| Step | What to do |
|:---:|---|
| **1** | Plug in the Unigen dongle. Its driver must be installed, so the dongle shows up in Windows' Wi-Fi list. |
| **2** | **[Download UnigenManager.exe](https://github.com/ApurvDas/unigen-manager/releases/latest/download/UnigenManager.exe)**: one file of about 33 MB. |
| **3** | Double-click it and choose **Yes** at the Windows prompt. |

That's it. The window opens, and a cyan icon appears in the taskbar's **^** flyout. Nothing is installed: the app runs from the `.exe` wherever you keep it, for example `C:\Apps\Unigen Manager\`.

> **"Windows protected your PC"?** The `.exe` isn't code-signed, so SmartScreen warns about it the first time. Click **More info ▸ Run anyway**.

**To remove it:** untick **Start with Windows** in the tray menu if you turned it on, quit from the tray, then delete the `.exe` and `%LOCALAPPDATA%\UnigenManager\`.

Older versions and checksums are on the [releases page](https://github.com/ApurvDas/unigen-manager/releases). Developers can [run from source](#run-from-source).

## Features

<table>
<tr>
<td width="50%" valign="top">

### 📶 Wi-Fi
- See nearby networks with signal, band and channel.
- A channel map for 2.4 and 5 GHz shows which channels are crowded.
- Connect, disconnect, or add a new WPA2 or open network with its password.
- **Saved networks:** show a password, copy a network to the other adapter, or hold to delete.
- An **Adapter** switch above the tabs picks which adapter Wi-Fi uses: the dongle or the built-in card.

</td>
<td width="50%" valign="top">

### 🎧 Bluetooth
- **Live search:** nearby devices appear as Windows finds them, and the search stops when you leave the page.
- **Pairing with PIN prompts:** confirm a code, type the code the device shows, or enter the device's PIN, right in the app.
- Bluetooth **on/off switch**, here and in the tray widget.
- **One row per device:** earbuds and speakers that Windows lists twice (classic Bluetooth and Bluetooth LE) show once, and Remove clears both.
- Remove devices, and connect or disconnect audio devices.
- **Fast:** the paired list loads in a few hundredths of a second.
- **Battery levels** of connected headphones and speakers (🔋 90%, amber at 20% or less), on the Bluetooth page and in the tray widget, updated every minute. Shown for devices that report battery to Windows over their hands-free connection, on either adapter.
- A **Radio** switch on this page picks which Bluetooth radio runs: the dongle (5.4) or the built-in one (5.2), independently of Wi-Fi. See [Two switches](#-two-switches-wi-fi-and-bluetooth-each-dongle--built-in) below.

</td>
</tr>
<tr>
<td valign="top">

### ⚡ Speed
- A live throughput curve for each adapter, with download and upload shown separately.
- Both adapters compared side by side: download, upload, link rate and ping.
- Signal strength of each adapter over the last 2 minutes.

</td>
<td valign="top">

### 🧭 Always-on tray widget
- Live status of both adapters, the dongle's status, and both switches (Wi-Fi and Bluetooth), the same as in the main window.
- Quick connect to saved networks, the Bluetooth on/off switch, and a mini speed test.
- Optional **Start with Windows**.

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 🔀 Two switches: Wi-Fi and Bluetooth, each Dongle | Built-in
- **Wi-Fi and Bluetooth are chosen separately.** For example, Wi-Fi on the dongle and Bluetooth on the built-in radio. The **Adapter** switch is on the Wi-Fi page, the **Radio** switch on the Bluetooth page, and the tray widget has both. Each choice is remembered across restarts (an older single choice is used for both until you change one).
- **Wi-Fi works on the new adapter in about 3 seconds:** the app turns each adapter's Wi-Fi radio on or off (the per-adapter Wi-Fi switch in Windows), so no driver has to restart. It joins the same network on the new adapter (copying the saved profile if needed), shows each step while it runs, and then turns the old adapter's Wi-Fi off in the background. If Windows' Wi-Fi button turns the unused adapter back on, the app turns it off again. Bluetooth is not touched.
- **Bluetooth moves in the background.** Windows runs one Bluetooth radio at a time, so the old one is turned off in Device Manager. That is usually quick, but Windows can take up to a minute while its audio engine lets go of a paired speaker or headphones. To avoid that, the app first disconnects any connected earbuds or speakers (Windows refuses to turn a radio off while audio is playing through it), turns the old radio off, then tries to reconnect them on the new one (a device not paired there shows **Re-pair**). The app tells you when Bluetooth has moved. If Windows still refuses, stop the audio or disconnect the earbuds and switch again. Wi-Fi is not touched.
- **One switch at a time:** the dongle's Wi-Fi and Bluetooth are one USB device, and changing one while the other is being turned off has hung its driver. So the two switches share a lock: a second click waits until the first is done.
- **It follows the dongle:** unplug it and the built-in adapter turns back on for both Wi-Fi and Bluetooth; plug it in again and each switch that was set to the dongle goes back to it (one set to Built-in stays). A tray notification tells you.
- **It notices a crashed dongle:** if the dongle stops responding (Windows still lists it, but it has no Wi-Fi), the app moves to the built-in adapter and asks you to unplug the dongle and plug it back in. A switch never waits on a device that has stopped answering.
- **Dongle status:** the top of the side menu, the tray widget and the tray icon's tooltip say whether the dongle is **connected**, **not plugged in** or **not responding**, and a notification says when it is plugged in. While it isn't connected, the **Dongle** button of both switches is disabled and Built-in stays usable.
- If the Wi-Fi step fails, the old adapter keeps working and the message says where you stand. If a Bluetooth move fails, Bluetooth stays on the old radio and the app says so (switch again to retry); the choice is saved only after a move worked, so the app never retries a failed one by itself. If a driver hangs, switching keeps working and the app asks you to re-plug the dongle.
- Needs administrator rights. Without them both switches are disabled and the app changes nothing.
- **Light on the PC:** adapter and radio status are read straight from Windows (SetupAPI) in milliseconds, so the always-on watchdog doesn't start a PowerShell process every few seconds. Wi-Fi radios are read and switched through the Windows Wi-Fi API (wlanapi); Bluetooth radios use the same Windows call as Device Manager, not PowerShell, and the app waits for the device to really change state.

</td>
</tr>
</table>

Each adapter shows its own standards, read from the hardware: **Wi-Fi 6**, **Bluetooth 5.4** for the Unigen dongle and **5.2** for the MediaTek card. The motion is built with anime.js and turns into simple fades when Windows' **Show animations** setting is off.

<div align="center">

| Bluetooth | Speed | Tray widget |
|:---:|:---:|:---:|
| <img src="docs/screenshots/bluetooth.png" alt="Bluetooth screen" width="300"> | <img src="docs/screenshots/speed.png" alt="Speed screen with charts" width="300"> | <img src="docs/screenshots/widget.png" alt="Tray widget above the taskbar" width="300"> |

</div>

## Requirements

| | |
|---|---|
| **Windows** | 10 or 11, **set to English** (the app reads `netsh` output) |
| **Python** | Not needed for `UnigenManager.exe`. To run from source: [3.10](https://www.python.org/downloads/release/python-31011/), with the `py` launcher (installed by default) |
| **WebView2** | Microsoft Edge WebView2 Runtime, already present on up-to-date Windows |
| **Rights** | Administrator, for the Wi-Fi and Bluetooth switches (turning adapters on and off) and Start with Windows (the app asks when it starts) |
| **Hardware** | Built for the Unigen AIC8800D80 dongle and MediaTek MT7921 card. Other Wi-Fi adapters show up under their Windows names |

## Run from source

Only needed for development. Everyone else can use [the `.exe`](#quick-start).

<details>
<summary><b>1. Download</b></summary>

- **Git:** `git clone https://github.com/ApurvDas/unigen-manager.git`
- **ZIP:** **Code ▸ Download ZIP** on this page, then extract it, for example to `C:\Users\<you>\UnigenManager`.

</details>

<details>
<summary><b>2. Install</b></summary>

Open a terminal in the project folder:

```powershell
py -3.10 -m pip install -r requirements.txt
```

That installs pywebview, pystray, Pillow and the WinRT packages used for Bluetooth. anime.js already ships in `ui/vendor/`.

</details>

<details>
<summary><b>3. Run</b></summary>

```powershell
py -3.10 UnigenManager.pyw
```

Choose **Yes** at the Windows prompt. If you choose **No**, the app still runs, but the Wi-Fi and Bluetooth switches are turned off and nothing is switched on its own.

Create a desktop shortcut (optional):

```powershell
py -3.10 app.py --install-shortcut
```

</details>

## Usage

| Action | How |
|---|---|
| Switch screens | Side menu, or <kbd>Ctrl</kbd>+<kbd>1</kbd> Wi-Fi · <kbd>Ctrl</kbd>+<kbd>2</kbd> Bluetooth · <kbd>Ctrl</kbd>+<kbd>3</kbd> Speed |
| Connect | Double-click a network, or select it and press <kbd>Enter</kbd> |
| Delete a saved network, or remove a device | Press and hold the button for 1.5 s; let go early to cancel |
| Open the widget | Click **^** on the taskbar, then the cyan icon. Click anywhere else or press <kbd>Esc</kbd> to close |
| Start with Windows | Right-click the tray icon and tick **Start with Windows** (a scheduled task; keeps running on battery) |
| Quit | Right-click the tray icon and choose **Quit**. Closing the main window only hides it |

Opening the app again while it's running brings the existing window forward, so only one copy runs at a time.

**Command-line options**

| Flag | Effect |
|---|---|
| `--tray` | Start with only the tray icon (the main window stays hidden) |
| `--no-elevate` | Don't ask for administrator rights |
| `--debug` | Open WebView developer tools |
| `--install-shortcut` | Create the desktop shortcut and exit |

The options work the same way on the `.exe`, for example `UnigenManager.exe --tray`.

App data such as the last speed results and `app.log` lives in `%LOCALAPPDATA%\UnigenManager\`.

## Development

**Preview the UI in a browser.** Both pages include a mock API with sample data:

```powershell
py -3.10 -m http.server 8765 --directory ui
```

Then open:
- `http://127.0.0.1:8765/index.html?mock` for the main window
- `http://127.0.0.1:8765/widget.html?mock` for the widget, above a fake taskbar

**Run the tests**

```powershell
py -3.10 -m pip install -r requirements-dev.txt
py -3.10 -m pytest                 # 336 unit, contract and UI tests (UI tests drive the installed Microsoft Edge)
py -3.10 -m pytest -m hardware     # read-only checks against the real adapters (changes nothing)
```

Checks that change system state (connecting, pairing, the Wi-Fi and Bluetooth switches, unplugging the dongle) are in the [manual checklist](docs/superpowers/test-reports/manual-checklist.md).

### Build the .exe

```powershell
py -3.10 -m pip install -r requirements-dev.txt
py -3.10 build_exe.py
```

This writes `dist\UnigenManager.exe`: one file of about 33 MB, with no console window, that runs without Python. PyInstaller bundles the Python runtime, the `ui/` folder, and `build_exe.py` draws the app icon from the tray logo. When the app runs as the `.exe`, the admin prompt, the desktop shortcut and Start with Windows all point at the `.exe` itself.

**Version numbers:** releases go 1.0.0, 1.0.1, … 1.0.9, then 1.1.0. Each part counts 0 to 9 and then rolls into the next one up (1.9.9 becomes 2.0.0). `version.py` holds the number of the next release, and `version.bump()` works out the one after it.

### How it fits together

```mermaid
flowchart LR
    subgraph Pages["WebView2 pages"]
        index["index.html<br/>main window"]
        widget["widget.html<br/>tray widget"]
        shared["shared.js + anime.js"]
    end
    app["app.py<br/>elevation, windows,<br/>single instance"] --> api
    app --> tray["tray.py<br/>pystray icon,<br/>Start with Windows"]
    index --> shared
    widget --> shared
    shared -- "window.pywebview.api" --> api["api.py<br/>plain-language errors"]
    api --> wifi["wifi.py<br/>netsh, wlanapi"]
    api --> bt["bt.py + btwinrt.py<br/>WinRT, KS audio, bthprops"]
    api --> hw["hw.py<br/>Wi-Fi and Bluetooth switches, watchdog"]
    hw --> pnp["pnp.py<br/>SetupAPI device reads"]
    bt --> pnp
    api --> speed["speed.py<br/>ping, sampled HTTP"]
    hw --> winrun
    wifi --> winrun["winrun.py<br/>argument lists only, no shell"]
    bt --> winrun
    speed --> winrun
```

| Path | What it does |
|---|---|
| `UnigenManager.pyw` | Double-click launcher |
| `app.py` | Administrator prompt, single instance, main and widget windows, tray |
| `api.py` | Everything the pages call, with plain-language errors |
| `wifi.py` | `netsh` parsing, connect and disconnect, saved profiles, Windows scan request |
| `hw.py` | The Wi-Fi and Bluetooth switches: Wi-Fi by radio with rollback, Bluetooth in the background, one lock, a saved choice for each, dongle status, unplug/replug watchdog |
| `pnp.py` | Reads Device Manager (status, disabled, Bluetooth version, device battery levels) through SetupAPI, in milliseconds, and turns devices on and off (verified by their state) |
| `bt.py` | Bluetooth radio switching and audio connect |
| `btwinrt.py` | Bluetooth through Windows' WinRT device APIs: paired list, live search, pairing with PIN prompts, unpair, radio power |
| `speed.py` | Ping and per-adapter sampled download and upload |
| `tray.py` | Tray icon, widget placement, Start with Windows, single instance |
| `winrun.py` | The only place that starts processes |
| `ui/` | `index.html`, `widget.html`, `shared.css`, `shared.js`, `mock-api.js`, vendored anime.js |
| `tests/` | pytest suites, Playwright UI tests, read-only hardware tests, captured `netsh` fixtures |
| `docs/superpowers/` | Design spec, implementation plan and the manual checklist |

## Security

- **Untrusted names:** anyone nearby can name a network or device, so names are always shown as text and handed to Windows tools as separate arguments, never as command text.
- **Passwords** are never logged. They only touch the disk inside temporary folders that are deleted straight away.
- **Start with Windows** runs the app with administrator rights at sign-in, without a prompt. The app's files live in your user folder, so anything that can change those files could gain administrator rights at your next sign-in. Leave the option off if that trade-off isn't right for you.

## Known limitations

- Windows must be in English. On other languages, the app shows *"Is Windows set to English?"* instead of wrong data.
- Network names with non-English characters may display incorrectly, and you can't connect to them from the app.
- New WPA3 and Enterprise networks must be added in Windows settings. Once saved, they connect normally.
- **Bluetooth audio Connect and Disconnect:**
  - The app first asks the device's audio driver to reconnect, the same way Windows Settings does.
  - If that fails it toggles the device's audio services, and if Windows still refuses, it opens Windows Bluetooth settings instead.
  - Which of the three works is still to be confirmed on real hardware (checklist row 24).
- Pairing a device that isn't in pairing mode times out after about a minute.
- **Two Bluetooth radios, two sets of pairings:** a device paired with only one radio shows **Re-pair** on the other. Each pairing needs the device in pairing mode while that radio is on, so the app can't pair a device with both radios in one go. **Hold to remove** on such a row unpairs it from the other radio too, which can fail while that radio is off.
- Battery levels of Bluetooth LE-only devices (most mice and keyboards) aren't shown yet.
- An adapter plugged in after the app starts appears after the app restarts.

## Built with

[pywebview](https://pywebview.flowrl.com/) (BSD) · [pystray](https://github.com/moses-palmer/pystray) (LGPL-3.0) · [Pillow](https://python-pillow.org/) (MIT-CMU) · [PyWinRT](https://github.com/pywinrt/pywinrt) (MIT) · [anime.js](https://animejs.com/) (MIT) · [Playwright](https://playwright.dev/python/) and [pytest](https://pytest.org/) for tests

The network names, addresses and device names in the tests and screenshots are made up.

## License

[MIT](LICENSE). The libraries above keep their own licenses; the exe bundles them unchanged.

Unigen Manager is an unofficial, independent project. It isn't affiliated with, endorsed by or supported by Unigen. "Unigen" and the dongle's name belong to their owners. For driver or hardware support, contact Unigen. For this app, [open an issue](https://github.com/ApurvDas/unigen-manager/issues).
