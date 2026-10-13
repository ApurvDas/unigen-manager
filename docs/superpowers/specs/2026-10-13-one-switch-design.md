# One switch for Wi-Fi and Bluetooth: design

**Approved by the user on 2026-10-13.** Ships in 1.0.2 alongside the Bluetooth work (branch `bluetooth-primary`).

**Goal.** A single **Using: Dongle | Built-in** control moves Wi-Fi and Bluetooth together. The choice sticks across restarts, never leaves the user without Wi-Fi, follows the dongle being unplugged and plugged back in, and shows each step while it runs.

## What exists today, and what goes

- `api.use_adapter(key)`: joins the other adapter's network on `key`, then disconnects the other. The tray widget's **Wi-Fi uses** control calls it. It doesn't stick, because the other adapter keeps auto-connect profiles and Windows reconnects it.
- `api.bt_switch(key)` → `bt.switch`: disables the other Bluetooth radio, enables the target, and rolls back on failure. The Bluetooth page's **Use built-in radio** button and the widget's Bluetooth button call it.
- **Removed:** `use_adapter`, `bt_switch`, the widget's **Wi-Fi uses** control, the widget's Bluetooth switch button, and the Bluetooth page's `#tryRadio`. `bt.switch` stays, because `hw` uses it for the Bluetooth step.

## How it sticks

The adapter not in use is turned off in Device Manager: both its Wi-Fi device and its Bluetooth device. Windows can't fall back to a disabled device, including after a restart. The choice is saved as `{"use": "unigen" | "builtin"}` in `%LOCALAPPDATA%\UnigenManager\settings.json`. With no saved choice, the app manages nothing until the user switches once.

Devices, matched as the existing code already does:

| Key | Wi-Fi device | Bluetooth device |
|---|---|---|
| `unigen` | `USB\VID_368B&PID_8D81&MI_02…` (AIC8800D80) | `USB\VID_368B&PID_8D81&MI_00…` |
| `builtin` | `PCI\VEN_14C3&DEV_7961…` (MT7921) | `USB\VID_13D3&PID_3563…` (MediaTek) |

## New module `hw.py` (+ `hw.ps1`)

- **`devices() -> {key: {"present", "wifi": dev|None, "bt": dev|None}}`:** each `dev` is `{"id", "ok", "disabled"}`, read from `Get-PnpDevice -PresentOnly` (Net and Bluetooth classes), so disabled devices are still listed. A dongle that isn't plugged in has no entry at all (`present` False).
- **`enable(id)` / `disable(id)`:** PnP, admin only.
- **`load_choice(path)` / `save_choice(path, key)`**
- **`use(target, *, on_step, path)`:** the switch, holding one lock, run in this order:
  1. "Turning on the {target}…": enable the target's Wi-Fi device, then wait up to 20 s for its interface in `wifi.interfaces()`. If it doesn't appear, restart it once (disable, then enable) and wait again. If it still doesn't appear, disable it again and raise.
  2. "Connecting to {ssid}…": runs only if the old adapter is connected. Copy the profile to the target if it lacks it, then `wifi.connect(target, ssid, saved=True)`. On failure, disable the target's Wi-Fi and raise.
  3. "Moving Bluetooth…": runs if both adapters have a Bluetooth device. Call `bt.switch(target)`, which rolls back its own Bluetooth step. On failure, disable the target's Wi-Fi and raise.
  4. "Turning off the {old}…": disable the old Wi-Fi device. Failure here is reported, not rolled back, because the target already works.
  5. Save the choice, then "Done. Using the {target}."
  - **Errors:** every raise is an `hw.HwError` whose sentence says the old adapter is back, for example "The dongle's Wi-Fi didn't start. You're still on the built-in adapter."
  - **Already in use:** switching to the adapter already in use (old off, target fine) just saves the choice.
- **`follow(path, notify, *, sleep)`:** one watchdog pass, called every 5 s from a tray thread.
  - **Choice is the dongle but it's not present** (unplugged): enable the built-in Wi-Fi and Bluetooth if they're disabled, then call `notify("The dongle was unplugged. Using the built-in adapter.")`. Windows reconnects saved networks by itself. The saved choice stays "unigen".
  - **Dongle comes back** (it wasn't present on the previous pass, and is now), with the choice still "unigen": `use("unigen")`, then `notify("Dongle plugged in. Using the dongle.")`. If that fails, notify the error and don't retry until the next unplug and replug.
  - **At startup** (first pass), with a saved choice whose adapter is present while the other adapter's Wi-Fi is enabled: `use(choice)` once, so the choice is enforced after a restart.
  - **Not admin:** `follow` does nothing.

## API (`api.py`)

- **`app_info()`:** adapters come from `hw.devices()` merged with `wifi.interfaces()`. Each adapter gains `"using": bool` and `"off": bool` (its Wi-Fi device is disabled). An off adapter is still listed. The top level gains `"using": key|None`.
- **`switch_to(key)`:** needs admin, else "Switching adapters needs administrator rights. Restart the app and choose Yes." It runs `hw.use` and pushes `window.onSwitchStep({"text", "done": bool, "error": bool})` to both windows for every step, and once more at the end. It returns `{"using": key}`.
- **Watchdog:** after an automatic switch, `follow`'s notify shows a tray balloon (`icon.notify`) and pushes `window.onUsingChanged && window.onUsingChanged()` to both windows.
- **`_KNOWN`** gains `hw.HwError`.
- **`ui/mock-api.js`:** mirrors `switch_to` with timed steps. Its `app_info` gains `using` and `off`. `MOCK_ADMIN = false` disables the control.

## UI

- **Main window:**
  - **Side menu:** a **Using** segmented control (`#using`, role=radiogroup, buttons `data-k`) above **Adapters**.
  - **Adapter rows:** the in-use row shows **In use**. The off row shows **Off** and isn't selectable: the Wi-Fi page stays on the adapter in use.
  - **While switching:** the control is disabled, and the step text shows under it (`#switchMsg`).
  - **On success:** `INFO` reloads and the Wi-Fi and Bluetooth views refresh.
  - **Bluetooth page:** the radio line keeps "Bluetooth is running on the …" without the button.
- **Tray widget:**
  - **Using control:** the **Wi-Fi uses** segmented control becomes **Using**, wired to `switch_to`, with the step text in `#wifiMsg`.
  - **Bluetooth row:** loses its switch button.
- **Both windows:** reload when `onUsingChanged` fires.
- **Without admin:** the control is disabled with the tooltip "Switching adapters needs administrator rights."

## Testing

- **`tests/test_hw.py`, with fake PnP and fake wifi/bt:**
  - device mapping
  - the order of steps
  - rollback at each step
  - the restart-once path
  - already in use
  - choice saved only on success
  - `follow`: unplug enables built-in once, replug switches back once, a failed replug doesn't retry, startup enforcement, and no-ops without admin
- **API:** `switch_to` needs admin, pushes steps, and the `app_info` shape with an off adapter. Mock parity holds.
- **UI (Playwright, mock):**
  - switching from the main window updates the In use/Off labels and the step text
  - the widget **Using** control
  - non-admin disabled
  - `onUsingChanged` reloads
- **Hardware (read-only):** `hw.devices()` finds both adapters' Wi-Fi and Bluetooth.
- **Manual (user):** switch both ways, restart Windows and check the choice holds, then unplug and replug the dongle.

## Out of scope

Mixing adapters (dongle Wi-Fi with built-in Bluetooth), and scanning or copying profiles on the adapter that's off.
