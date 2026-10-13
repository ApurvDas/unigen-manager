# Unigen Manager: design spec

Date: 2026-10-13
Status: awaiting review

## Purpose

A Windows desktop app that gives one place to manage Wi-Fi and Bluetooth on this PC. The PC has two Wi-Fi adapters and two Bluetooth radios:

| Adapter | Windows name | Hardware |
|---|---|---|
| Unigen USB dongle | `Wi-Fi 2`, Bluetooth "Generic Bluetooth Adapter" | AIC8800D80 (VID 368B, PID 8D81) |
| Built-in card | `Wi-Fi`, "MediaTek Bluetooth Adapter" | MediaTek MT7921 (Bluetooth currently **disabled** in Device Manager: problem code 22, `CM_PROB_DISABLED`) |

The user chose four things the Windows panels don't do well:

1. Wi-Fi and Bluetooth in one window
2. Choose which adapter does the work, and switch between them
3. Signal, band, channel and speed details
4. Saved networks: show passwords, delete, copy between adapters

**Success:** from the app alone, the user can see nearby networks on either adapter, connect with a password, switch which adapter is used, manage saved networks, list, pair and remove Bluetooth devices, switch the Bluetooth radio, and run a speed test. The app never freezes while doing any of these.

## Decisions already made

- **Stack:** Python 3.10 (`py` launcher, has pip) + **pywebview**, which shows the HTML/CSS interface in a native window through WebView2 (installed, version 154). The MSYS2 `python` on PATH has no pip and is not used.
- **Interface:** the approved dark mockup at `ui/index.html`. The backend replaces its hard-coded arrays (`NETS`, `PAIRED`, `SAVED`) with live data. The look does not change.
- **Admin:** the app runs elevated on every launch, because Bluetooth radio switching needs it (user's choice).
- **Out of scope:** system tray, automatic adapter switching, usage graphs, 6 GHz, Windows set to a language other than English (see Risks).

## Architecture

```
UnigenManager/
  UnigenManager.pyw   entry point: elevation, window, Api class (the JS bridge)
  wifi.py             Wi-Fi: adapters, scan, connect, saved profiles (netsh + wlanapi)
  bt.py               Bluetooth: devices, pair/remove, connect, radio switch (PowerShell/WinRT + Win32)
  speed.py            ping, download, upload per adapter; last results in results.json
  ui/index.html       the approved interface
  ui/vendor/anime.umd.min.js   anime.js v4.5.0 (MIT), stored locally
  test_parsers.py     assert-based checks for the netsh/PowerShell output parsers
```

Each Python module has one job and no knowledge of the UI. `UnigenManager.pyw` is the only file that knows about both sides.

### Bridge between the UI and Python

pywebview exposes an `Api` object to the page as `window.pywebview.api`. Every method:

- runs on its own thread (pywebview does this), so slow work never blocks the window
- returns `{"ok": true, "data": ...}` or `{"ok": false, "error": "<plain-language message>"}`

The page shows `error` in the red message line of the current screen. Every screen gets the same message line the Wi-Fi screen already has.

| Api method | Returns / does |
|---|---|
| `adapters()` | Both Wi-Fi adapters: friendly name, connected SSID, link rate, signal, channel, IP |
| `scan(adapter)` | Triggers a fresh scan (wlanapi `WlanScan`), waits up to 4 s, returns networks in the `NETS` shape |
| `connect(adapter, ssid, password=None)` | Connects. Creates a profile first if the network is new. |
| `disconnect(adapter)` | Disconnects |
| `saved()` | Saved profiles, each marked "both adapters" or "Unigen dongle only" / "built-in only" |
| `password(adapter, ssid)` | The saved password (`key=clear`) |
| `copy_profile(ssid, src, dst)` | Copies a saved network to the other adapter |
| `delete_profile(adapter, ssid)` | Deletes a saved network |
| `bt_radio()` | Which Bluetooth radio is active, and each radio's state |
| `bt_switch(target)` | Switches the Bluetooth radio (see below) |
| `bt_paired()` / `bt_nearby()` | Device lists. `bt_nearby` searches for about 10 s. |
| `bt_pair(id)` / `bt_remove(id)` | Pair / unpair |
| `bt_connect(id)` / `bt_disconnect(id)` | Best-effort audio connect/disconnect (see below) |
| `speed_test(adapter)` | Ping, download, upload. Also saved to `results.json`. |
| `speed_results()` | The last result for each adapter, for the comparison table |

### Wi-Fi (`wifi.py`)

- **Reading:** `netsh wlan show interfaces`, `show networks mode=bssid interface=...`, `show profiles`, and `show profile ... key=clear`, parsed line by line. Each access point gives `{b, ch, s}`. Band is worked out from the channel: 1–14 is 2.4 GHz, anything higher is 5 GHz.
- **Fresh scans:** netsh only shows Windows' cached list. `WlanScan` from `wlanapi.dll` (called through `ctypes`, which is in the standard library) asks the adapter to rescan first.
- **Connecting to a new network:** writes a WPA2-Personal (or open) profile XML to a temporary file, runs `netsh wlan add profile`, then `netsh wlan connect`. The temporary file is deleted in a `finally` block, so the password never stays on disk. After connecting, the app polls the interface for up to 15 s. If it isn't connected by then, it reports "Couldn't connect to <ssid>. Check the password." and deletes the half-made profile.
- **Copying between adapters:** export with `key=clear` to a fresh temporary folder, `add profile interface=<dst>`, then delete the folder. This is the same method used manually earlier.
- **Adapter names:** an interface description containing `AIC8800` is shown as "Unigen dongle", and one containing `MT7921` as "Built-in MediaTek". Anything else shows its Windows description.

### Bluetooth (`bt.py`)

- **Lists, pairing, removing:** WinRT `Windows.Devices.Enumeration` + `Windows.Devices.Bluetooth`, run through `powershell.exe` 5.1 (the only PowerShell that can call WinRT directly). Results come back as JSON. Device IDs go to the scripts as arguments, never pasted into script text.
- **Connect / disconnect (best effort):** Windows has no public "connect this headset" API. The app calls Win32 `BluetoothSetServiceState` (bthprops.cpl, via ctypes) to turn the device's audio services off and back on, which makes Windows reconnect. If that fails, the app opens `ms-settings:bluetooth` and says so. **This needs a quick feasibility test before building on it** (first task in the plan).
- **Radio switch:** finds Bluetooth radios with `Get-PnpDevice -Class Bluetooth` (USB/PCI instance IDs), turns off the active one (`Disable-PnpDevice`) and turns on the target (`Enable-PnpDevice`). It then waits up to 10 s for the target to report OK. **If the target doesn't come up, the original radio is turned back on**, so the user is never left without Bluetooth. Then it reports "The built-in radio didn't start. Switched back to the Unigen dongle."

### Speed (`speed.py`)

Same method as the manual test on 12 Oct:

- ping the gateway from the adapter's IP (`ping -n 10 -S <ip>`)
- 3 × 25 MB downloads and 1 × 25 MB upload against `speed.cloudflare.com`, sent through the chosen adapter with `curl.exe --interface <ip>`
- results averaged and saved per adapter, with a timestamp, to `results.json`

### Elevation

On launch, `UnigenManager.pyw` checks `IsUserAnAdmin()`. If it isn't elevated, it relaunches itself through `ShellExecuteW(..., "runas", ...)` and exits. **If the user declines the admin prompt,** the app opens anyway with radio switching disabled and the note "Bluetooth radio switching needs administrator rights." Everything else still works.

## Interface changes

The mockup stays as it is, except:

1. The hard-coded arrays become `await window.pywebview.api.*` calls.
2. Every screen gets a message line for errors.
3. "Scanned N seconds ago" uses the real scan time. The Wi-Fi list refreshes every 10 s while that screen is visible, updating rows in place (selection and scroll position are kept).
4. The adapter entries in the side menu refresh every 3 s.
5. Connecting to a new secured network asks for the password in a small centered dialog inside the page.
6. "Show" reveals the password and changes to "Hide".
7. **Navigation (changed 2026-10-13):** the side menu has three tabs: **Wi-Fi 6** (Ctrl+1), **Bluetooth 5.x** (Ctrl+2) and **Speed** (Ctrl+3).
   - **Version sources:** each adapter entry shows its own standards. Unigen is "Wi-Fi 6, Bluetooth 5.4" (LMP 13). MediaTek is "Wi-Fi 6, Bluetooth 5.2" (LMP 11). Wi-Fi 6 comes from 802.11ax in `netsh wlan show drivers`. Bluetooth comes from `DEVPKEY_Bluetooth_RadioLmpVersion` (LMP 9→5.0, 10→5.1, 11→5.2, 12→5.3, 13→5.4, 14→6.0), which Windows keeps even while a radio is disabled.
   - **Bluetooth label:** the Bluetooth tab label follows the radio Bluetooth is currently using.
   - **Backend:** read these values from the hardware, never hard-code them. Saved networks moved inside the Wi-Fi tab as a **Nearby | Saved** switcher with a sliding highlight. The Saved count updates when a network is deleted.
8. **Speed screen charts** (added 2026-10-13, built with the dataviz rules):
   - **Last test:** throughput line and area for the chosen adapter. Download and upload are separate segments on one Mbps axis (0–80). It draws live during a test, and draws on when you switch adapters (`createDrawable`).
   - **Both adapters:** small multiples for Download, Upload, Link rate and Ping, each on its own scale, with values at the bar tips. Bars grow on first view and animate only when a value changes.
   - **Signal strength:** both adapters, last 2 minutes, a reading every 2 s on a 50–100% axis. The lines slide left, and sliding pauses while hovered or focused.
   - All three have a crosshair or per-bar tooltip (values lead, names follow, written with `textContent`), arrow-key navigation, and a "Table view" built from the same data.
   - Adapter colors: Unigen `#9085e9` (violet), Built-in `#d55181` (magenta). Both were validated on `--raised` with the dataviz validator (dark): CVD ΔE 16.0, normal-vision 19.7, all checks pass.
   - Backend data: `speed_test` should return per-sample Mbps (about 40 samples with a download/upload split). `adapters()` polling every 2 s feeds the signal history.

## Tray widget (added 2026-10-13)

The user asked for an always-on widget in the notification area, the **^** flyout at the bottom right. The approved prototype is `ui/widget.html`; open it in a browser and click **^**, then the Unigen icon. This replaces "system tray" in the original out-of-scope list.

- **Tray icon:** `pystray` + `Pillow`, drawn with the cyan signal arcs.
  - Tooltip: "<adapter>: <network>, <signal>%", updated every 10 s.
  - Left-click toggles the widget.
  - Right-click menu: *Open Unigen Manager*, *Start with Windows* (checkbox), *Quit*.
- **Widget window:** a second pywebview window, frameless and always on top, 340 px wide. It sits 12 px above the taskbar at the bottom right, worked out from the screen work area (`SystemParametersInfo SPI_GETWORKAREA`). It hides when it loses focus or on Escape. It uses the same `Api` as the main window and only polls (every 3 s) while open.
- **Content:**
  - **Wi-Fi uses:** the chosen adapter joins the network the other one was on (if it isn't already connected), then the other adapter disconnects. New API method: `use_adapter(key)`.
  - Live status of both adapters: network, signal % with a 4-bar glyph, link speed.
  - Up to 4 saved networks in range on the chosen adapter, with Connect / Disconnect.
  - The Bluetooth version of the active radio and the connected device, with the radio switch (same rollback as the main app).
  - A mini speed test on the chosen adapter: download and upload averages and a sparkline in the adapter's color, with download and upload as separate segments.
- **Motion** (anime.js, same helpers and tokens as the main app):
  - The widget opens by rising 8 px with a fade (180 ms) and closes in 120 ms.
  - The switch highlight slides; buttons shrink on press; labels swap with a blur; changed values settle in; status dots pop.
  - The sparkline draws live during a test and draws on when you switch adapters.
  - Confirmation messages fade after 4 s; errors stay.
  - With reduced motion turned on, everything only fades.
- **Always on:**
  - **Start with Windows:** a scheduled task (`schtasks /Create /SC ONLOGON /RL HIGHEST`) starts `UnigenManager.pyw --tray` at sign-in with admin rights, so there's no admin prompt each time. The tray checkbox creates or deletes the task.
  - Closing the main window hides it; *Quit* exits.
  - **Single instance:** a named mutex. A second launch sets a named event, and the running copy shows its main window.
- **Shared front end:** the CSS tokens, button styles and motion helpers move into `ui/shared.css` and `ui/shared.js`, used by both `index.html` and `widget.html`, so the two can't drift apart.

## Motion (anime.js)

The user asked for anime.js. It is **v4.5.0**, loaded as `ui/vendor/anime.umd.min.js` with a plain `<script>` tag, which creates a global `anime`. The ES-module build is avoided because module scripts can fail to load from local files in WebView2. All motion uses one curve, matching the mockup's `--ease-out`: `const ease = anime.cubicBezier(0.23, 1, 0.32, 1)`.

**Reduced motion:** anime.js does not check Windows' reduced-motion setting itself. A single flag, `const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches`, switches every effect below to "fade only, no movement".

| Moment | anime.js | Values |
|---|---|---|
| Hold-to-delete fill (Saved, Bluetooth) | `anime.waapi.animate(overlay, { clipPath: ['inset(0 100% 0 0)', 'inset(0 0% 0 0)'], duration: 1500, ease: 'linear' })`. Releasing early cancels it and plays a 200 ms snap-back. `onComplete` runs the delete. | Replaces the current CSS transition + separate `setTimeout`, so the 1.5 s is defined in **one** place |
| Row removed after delete | `anime.createLayout(list, { leaveTo: { opacity: 0 }, duration: 200, ease })`: `record()`, remove the row, `animate()`. The row fades out and the rows below slide up into the gap. | Fade 150–200 ms. Reduced motion: fade only. |
| Nearby Bluetooth devices appearing | Same `createLayout` on the nearby list with `enterFrom: { opacity: 0, translateY: 4 }`. Rows arrive one by one as they are found, so no stagger is added. | 200 ms. Reduced motion: fade only. |
| Password dialog | Open: `anime.animate(dialog, { opacity: [0, 1], scale: [0.96, 1], duration: 200, ease })`, scaled from the center. Backdrop opacity 0→1 over 200 ms. Close: the reverse in 150 ms. | Reduced motion: opacity only, 150 ms. |
| Message line set (every screen) | `anime.waapi.animate(msg, { opacity: [0, 1], duration: 150, ease })`, replayed every time, even for identical text | Kept with reduced motion (fade only) |

**Every click responds (added 2026-10-13 at the user's request).** The mockup's `<script>` has a "motion components" block. Every interaction goes through these helpers:

| Component | Does | Used by |
|---|---|---|
| `press` | One document listener: anything clickable scales to 0.97 on pointer down (120 ms) and back to 1 on release (200 ms) | Every button, adapter, menu item, link |
| `slide(ind, to, instant)` | One highlight per group moves to the chosen item (200 ms). Instant for keyboard shortcuts and resizes. | Side menu, adapter choice, selected network |
| `swap(btn, text)` | Label blurs out (100 ms), text changes, blurs back in (140 ms) | Every label change |
| `busy(btn, label, ms, {prog, after})` | Shared shape of every slow action: disable, swap the label, optional progress bar, then settle | Connect, Disconnect, Scan, Search, Pair, Copy, Try radio, Run test |
| `arrive(el)` / `setText(el, text)` | A changed value fades in and drops 3 px into place (200 ms). Only values that actually changed animate. | Status cells, side-menu SSID and link rate, paired count, speed numbers, timestamps |
| `pop(dot, on)` | Status dot scales from 1.8 to 1 when it changes | Side-menu connection dots |
| `scramble(el, text)` | `anime.scrambleText` through `innerHTML`, 300 ms | Show / Hide password |
| `addEl` / `removeEl` | `createLayout` enter/leave | Nearby devices, pairing (Nearby → Paired), hold-to-delete, Copy button removal |
| `fillIn()` | The newly connected network's bump fills in on the channel map (250 ms) | Connect / Disconnect |

The CSS `:active` shrink and the CSS label-blur transition were removed. anime.js now does both, so there is one motion system. Only the moving progress bars stay in CSS, because they run continuously.

**Never animated:** the section content when switching screens (only the menu highlight moves, and not at all with Ctrl+1–4), the channel-map hover highlight, and the automatic Wi-Fi list refresh (its row order stays frozen while the pointer is over the list). Numbers never count up. They swap in place with `arrive`.

## Security

The app runs as administrator and shows network names that **anyone nearby can set**, so:

- Every subprocess call uses an argument list, never `shell=True`. SSIDs and device IDs are passed as separate arguments or JSON, never inserted into command or script text.
- Everything shown in the page goes through the existing `esc()` helper.
- Passwords are never logged and never written to disk except as the short-lived temporary files described above.
- pywebview's local page is the only content loaded. No remote pages, no CDN scripts (anime.js is stored in the app folder), and no developer tools in the normal build.

## Testing

- Automated: `py -3.10 -m pytest`. This covers unit tests (parsers against real captured netsh output, commands, profile XML, Bluetooth switch and rollback, the speed sampler against a local server), API contract tests (including mock-api.js ↔ Api method names), and Playwright UI tests against `?mock` in Microsoft Edge.
- Hardware, read-only: `py -3.10 -m pytest -m hardware`.
- State-changing: `docs/superpowers/test-reports/manual-checklist.md`, run with the user.

## Risks

| Risk | Handling |
|---|---|
| Bluetooth connect via `BluetoothSetServiceState` may not work for every device | Feasibility test first; fallback is opening Windows settings |
| The built-in MediaTek Bluetooth radio is disabled (problem code 22). Enabling it should work, but it hasn't been tried. | Automatic switch-back if it doesn't reach OK within 10 s. The message tells the user. |
| netsh output is language-dependent | Out of scope (the PC is in English). Parsers fail loudly with a clear error rather than showing wrong data. |
| `WlanScan` results arrive asynchronously | Wait up to 4 s, then show whatever netsh has |

## Build order

1. Bluetooth connect feasibility test (throwaway)
2. `wifi.py` + parser tests, then wire the Wi-Fi and Saved screens
3. `speed.py`, then wire the Speed screen
4. `bt.py` (lists, pair, remove, radio switch), then wire the Bluetooth screen
5. Elevation, launcher, desktop shortcut

anime.js is added in step 2 with the shared `ease` and `reduce` helpers. Each screen's motion from the Motion table is built in the same step as that screen.
