# Bluetooth as a primary app: design (sub-project A)

**Goal.** Users pair and connect every common Bluetooth device in Unigen Manager without opening Windows Settings. Sub-project B (Wi-Fi: WPA3, hidden, Enterprise, any language, hot-plug, Wi-Fi on/off) gets its own spec.

**Approved by the user on 2026-10-13** in three sections: architecture, search and pairing, controls and testing. Approach: Python WinRT bindings (`winrt-*` packages).

## Why

- Pairing uses `DeviceInformationPairing.PairAsync()` from a hidden PowerShell process, which can't answer PIN ceremonies. OnePlus Nord Buds 3r fail with `Failed`/`AuthenticationFailure`.
- The nearby list is Windows' cached list from `FindAllAsync`, so absent devices show and BLE-only devices (mice, keyboards) never do.
- Devices with both a classic and an LE record (buds, Beats Pill) show twice.
- There is no Bluetooth on/off switch, and audio Connect/Disconnect is unverified (checklist row 24).

## Architecture

| Unit | Responsibility |
|---|---|
| `btwinrt.py` (new) | All WinRT work in Python: paired list, live search (`DeviceWatcher` over Bluetooth and Bluetooth LE association endpoints), custom pairing with ceremonies, unpair, radio on/off (`Windows.Devices.Radios`). Pure helpers (merging twins, device kinds, error mapping) are separate functions so they test without hardware. |
| `bt.py` | The only module `api.py` calls for Bluetooth. Keeps hardware radio switching (PnP enable/disable through `bt.ps1`, admin) and audio connect. Delegates devices, search, pairing and power to `btwinrt`. |
| `bt.ps1` | Shrinks to `radios`, `enable`, `disable`. |
| `api.py` | Existing method names stay, except `bt_nearby`, which live search replaces. New: `bt_power(on)`, `bt_search_start()`, `bt_search_stop()`, `bt_pair_answer(accept, pin)`. `bt_radio()` gains `power: "on" | "off" | "unknown"`. |
| `ui/index.html`, `ui/widget.html`, `ui/mock-api.js` | Live search list, inline pairing panel, on/off switch. Mock mirrors every new method (contract test). |

New runtime dependencies (pinned): `winrt-runtime`, `winrt-Windows.Foundation`, `winrt-Windows.Foundation.Collections`, `winrt-Windows.Devices.Enumeration`, `winrt-Windows.Devices.Bluetooth`, `winrt-Windows.Devices.Radios`. PyInstaller must bundle them.

## Search

- `bt_search_start()` starts a `DeviceWatcher` for unpaired Bluetooth and Bluetooth LE association endpoints, requesting `IsPresent`, `IsConnected`, `IsPaired`, `DeviceAddress`, `Bluetooth.Cod`, `Bluetooth.Le.Appearance` and `SignalStrength`. It stops itself after 30 s and pushes `window.onBtFound({id, name, kind, address})` and `window.onBtGone(id)` to the main window. Only present, unpaired devices are pushed.
- The search stops on timeout, page change (`bt_search_stop`), radio off, or when pairing starts.
- **Twins:** classic and LE records with the same name are one row. The row prefers the classic record for pairing, and keeps every id for removal. Paired twins merge the same way.
- **Kind:** class of device (classic) or GAP appearance (LE) maps to Headphones, Speaker, Phone, Computer, Keyboard, Mouse, Controller, Watch, TV, or Device.
- **Unnamed:** devices with no name are hidden from search, as in Windows Settings (anonymous beacons from nearby phones). A paired device with no name shows "Unknown device" plus the last 4 hex digits of its address.

## Pairing

- `bt_pair(id)` stops any search, then runs `Custom.PairAsync(ConfirmOnly | ConfirmPinMatch | DisplayPin | ProvidePin, ProtectionLevel.Default)` and handles `PairingRequested`:
  - **ConfirmOnly:** accept. The Pair click is the user's consent.
  - **ConfirmPinMatch:** push `window.onPairPrompt({kind: "confirm", pin})` and wait for `bt_pair_answer`.
  - **DisplayPin:** push `{kind: "display", pin}` and accept. The device completes the ceremony.
  - **ProvidePin:** push `{kind: "provide"}`, wait for `bt_pair_answer(true, pin)`, accept with the PIN.
  - A deferral holds the ceremony open while waiting. With no answer after 60 s, the handler declines.
- One pairing at a time. A second `bt_pair` returns "Already pairing a device."
- **Status messages:**
  - `Paired`, `AlreadyPaired`: success.
  - `AuthenticationFailure`, `RejectedByOnDevice`, `ConnectionRejected`: "The device refused. Put it in pairing mode, and disconnect it from your phone first."
  - `AuthenticationTimeout`, `NoSupportedProfiles`, `Failed`: "The device didn't answer. Bring it closer and make sure it's in pairing mode."
  - `RejectedByHandler`, `OperationAlreadyInProgress`: "Pairing cancelled."
  - `AuthenticationNotAllowed`: "Wrong PIN. Try again."
- After pairing, an audio device (Headphones, Speaker) is connected right away.
- Pairing runs only in the main window. The widget is unchanged.

## Controls

- **On/off:** `bt_power(on)` sets the WinRT radio of the active adapter. No admin needed. The Bluetooth page header and the widget show the switch. When off, the page shows "Bluetooth is off" with **Turn on**, and Search, Pair and Connect are disabled.
- **Audio connect:**
  1. Main method: `KSPROPERTY_ONESHOT_RECONNECT` / `KSPROPERTY_ONESHOT_DISCONNECT` (`KSPROPSETID_BtAudio`) sent with `IOCTL_KS_PROPERTY` to the device's Bluetooth audio KS filters, found through SetupAPI by the device address.
  2. Fallback: the existing service toggle.
  3. Last resort: Windows Bluetooth settings.
- **Status:** paired rows show Connected or Not connected and refresh with the existing poll.

## Errors

Every failure returns a plain sentence through the existing `_envelope`. Radio removal or power-off during search or pairing ends it with "Bluetooth turned off" or "The Bluetooth adapter was unplugged." Unexpected exceptions go to `app.log`.

## Testing

- **Unit tests with fakes:** kind mapping, twin merge, unnamed label, status messages, ceremony handling (each kind, timeout, cancel, wrong PIN), single-pairing lock, power, audio-connect fallback order.
- **UI:** mock prompts for each ceremony. Playwright tests cover live search rows, each prompt, cancel, power off state, and the contract test.
- **Hardware (read-only):** WinRT loads, radio power is readable, the paired list matches the PowerShell list count.
- **Manual checklist rows:** pair the buds, pair a phone (confirm PIN), keyboard (display PIN) if available, on/off, Connect and Disconnect on a speaker.

## Release

Version 1.0.2: README (features, limitations), exe rebuilt, GitHub release, installed copy in `C:\Program Files\Unigen Manager\` updated.

## Out of scope

File transfer, battery levels, Bluetooth settings beyond connecting, and pairing from the widget.
