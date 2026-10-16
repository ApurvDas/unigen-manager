# Crashed-dongle recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every failure in the 2026-10-16 app.log: the app must never lose Bluetooth or hang its switch when the Unigen dongle's chip crashes, must tell the user to re-plug it, and must recover on its own.

**Architecture:** "Working" is judged by what Windows can actually use (a Bluetooth radio from `BluetoothFindFirstRadio`, a WLAN interface from wlanapi), never by Device Manager's "started/OK" alone. Every Device Manager change that can block in a crashed driver runs in a bounded thread, so the switch lock is always released. The watchdog treats a crashed dongle like an unplugged one.

**Tech Stack:** Python 3.10, ctypes (setupapi, cfgmgr32, bthprops.cpl, wlanapi), pytest.

**Spec:** this plan; evidence in `%LOCALAPPDATA%\UnigenManager\app.log` (session `==== start` 11:32:04) and the System event log (BTHUSB 6 at 11:33:34, BTHUSB 17 at 12:28:55, Kernel-PnP 225 at 12:28:08).

## What happened (evidence)

| Time | Log line | Cause |
|---|---|---|
| 11:33:34 → 11:34:12 | `moving Bluetooth to unigen failed: The Unigen dongle radio didn't start` | Dongle plugged in with its Bluetooth enabled while MediaTek ran ("Only one active Bluetooth adapter", BTHUSB 6): it failed to start. `bt._switch` only *enables* the target; a device that is enabled-but-failed needs a restart. |
| 12:27:30 → 12:28:55 | Wi-Fi to dongle ok; Bluetooth move logged nothing | Dongle Bluetooth firmware crashed (BTHUSB 17), taking its WLAN interface with it. Device Manager still says started/OK, so `bt._switch` reported success. |
| 12:28:17 → 12:29:14 | `networks('unigen') failed: The Unigen dongle isn't plugged in.` | Wrong message: it is plugged in but crashed. |
| 12:29:16 | `switch_to('builtin') ok` then nothing | `_finish` → `wifi_off('unigen')` → no WLAN interface → Device Manager disable of the crashed device → blocks forever, outside the BT_STUCK guard. Lock held for good, MediaTek Bluetooth never re-enabled. |
| 12:32 | connect/disconnect/power fail: no radio | Consequence of the above. Disconnect also opened Windows Settings, which can't help. |
| 11:32, 11:35, 12:32, 12:46 | `adapters() ok in 4-14 s (slow)`, `app_info() slow` | Windows' Wi-Fi service blocked by the dongle driver (several calls finish in the same millisecond; netsh takes 70 ms when healthy). **No code task:** it goes away once the dongle is recovered (Tasks 5-6). |
| 11:32:53 | two `open_main()` at once | User clicked again while the first waited on the slow service. Idempotent. **No task.** |

## Global Constraints

- Never poke a radio Windows is still tearing down (see `pnp.set_enabled` docstring); never re-enable the old radio after a disable that didn't finish.
- No Device Manager call that can block on a crashed driver may run while holding `hw._lock` without a time bound.
- User-facing text: plain language, says where the user stands and what to do.
- Commits in this repo carry **no** Co-Authored-By / Claude trailers.
- Tests must not touch hardware: replace `bt._set`, `bt._radio_up`, `hw.enable/disable/set_radio/_rows/_radios`.

## Review Focus

1. Dongle just plugged in, WLAN interface not up yet (1-3 s): must not be called "crashed". Debounce in Task 5 (`LOST_PASSES`); `_use` still waits for it (Task 6).
2. `wifi.radios()` fails (wlansvc down): `_radios()` returns `{}`; nothing may be marked lost from an empty read (Task 2 test).
3. Both radios broken (MediaTek disabled, dongle crashed): switching to Built-in must enable MediaTek, not hang on the dongle (Task 3 test via bounded `_finish`).
4. A restart of a failed-start radio must not run on a radio that is mid-teardown (`ok` False because it is turning off): restart only when the state is a start failure, after the old radios are off (Task 4 test).
5. Watchdog after a crash with choice `unigen`, then re-plug: must switch back to the dongle exactly once (Task 5 test).

---

### Task 1: Bluetooth "started" means Windows has a radio — IN PROGRESS (worker)

**Files:** Modify `bt.py` (`_radio_up`, `_switch`, `_toggle`); Test `tests/test_bt.py`

**Interfaces:** Produces `bt._radio_up() -> bool` (BluetoothFindFirstRadio found a radio; tests replace it).

- [ ] `_switch`: early return and wait-loop success require `_radio_up()`; rollback disables the target only when there are old radios to restore.
- [ ] `_toggle`: no radio → `BtError("No Bluetooth radio is working, so {name} can't {verb}. Switch adapters again, or re-plug the dongle.")`, Settings not opened. The warning log says `audio connect` / `audio disconnect` to match the verb.
- [ ] Tests: no radio after enable → rollback; already-ok target without radio → no early return; toggle without radio → no Settings.

### Task 2: Wi-Fi without a WLAN interface isn't working — IN PROGRESS (worker)

**Files:** Modify `hw.py` (`devices`, `wifi_off`); Test `tests/test_hw.py`

- [ ] `devices()`: when `radios` is non-empty and has no entry for the key, and the Wi-Fi isn't `pnp_off` → `ok = False`, `disabled` stays False.
- [ ] `wifi_off()`: no WLAN interface → do nothing (drop the Device Manager disable fallback that hung).
- [ ] Tests: crashed dongle → `ok False`; `radios == {}` → unchanged; `wifi_off` with no radio calls nothing.

### Task 3: The switch tail is bounded and logged; unplug recovery for either choice — IN PROGRESS (worker)

**Files:** Modify `hw.py` (`_finish`, `Follower._step`); Test `tests/test_hw.py`

- [ ] `_finish`: `wifi_off` and `bt.switch` both run in the one thread joined with `BT_STUCK`; lock always released; `log.info("switch to %s finished: %s", target, text)` on every path.
- [ ] `Follower._step`: the "dongle gone → built-in Wi-Fi and Bluetooth on" block runs for choice `builtin` too.
- [ ] Tests: blocking `wifi_off` → lock released, `on_later(..., False)`; success logs "finished"; choice builtin + dongle absent + MediaTek BT disabled → `enable(MT_BT)`.

### Task 4: Restart a Bluetooth radio that failed to start

**Files:** Modify `bt.py:_switch`; Test `tests/test_bt.py`

**Interfaces:** Consumes `bt._radio_up` (Task 1). Produces a new `radios()` row field `failed: bool` = Device Manager problem code set and not 22 (a start failure such as code 10).

- [ ] **Step 1: Failing tests** `test_switch_restarts_a_target_that_failed_to_start`: radios = dongle `ok True` + MediaTek with problem `"10"`; after the switch to `builtin` the `_set` calls are `[("disable", unigen), ("disable", MT), ("enable", MT)]` and it returns `"builtin"`. `test_switch_never_restarts_a_stopped_target_without_a_problem`: MediaTek `status Error`, problem `CM_PROB_NONE` (stopping) → no `("disable", MT)` call.
- [ ] **Step 2:** `py -3.10 -m pytest tests/test_bt.py -k restart -v` → first FAILS (no MT disable).
- [ ] **Step 3:** In `_switch`, after the old radios are off and before enabling: `if tgt["failed"]: _set(tgt["id"], False)` (a radio that never started has nothing to tear down; a stopping one, with no problem code, is left alone). On the final "didn't start" failure, `log.warning` the `radios()` snapshot so the next report shows each radio's state.
- [ ] **Step 4:** whole `tests/test_bt.py` passes.
- [ ] **Step 5:** commit `Bluetooth: restart a radio that failed to start while the other one ran`.

### Task 5: The watchdog treats a crashed dongle like an unplugged one

**Files:** Modify `hw.py` (`devices`, `Follower`); Test `tests/test_hw.py`

**Interfaces:** Consumes Task 2's rule. Produces `devices()[key]["wifi"]["lost"] -> bool` (started in Device Manager, no WLAN interface, read worked) and `hw.LOST_PASSES = 3`.

- [ ] **Step 1: Failing tests:**
  - `test_watchdog_moves_off_a_crashed_dongle`: choice `unigen`, dongle present with `wifi.lost True` for 3 `step()` calls → built-in Wi-Fi turned on (`wifi_on`) and MediaTek BT `enable`d on the 3rd pass, not before; notify called once with text containing `"stopped responding"` and `"plug it back in"`.
  - `test_watchdog_returns_to_the_dongle_after_replug`: continue the above with the dongle absent for one pass, then present and healthy → `use("unigen")` called exactly once.
  - `test_brief_missing_interface_is_not_a_crash`: lost for 2 passes then healthy → no `wifi_on`, no notify.
- [ ] **Step 2:** run them → FAIL.
- [ ] **Step 3:** `devices()` sets `lost` alongside Task 2's `ok = False` (False everywhere else). `Follower` counts consecutive passes where `devs["unigen"]["wifi"]["lost"]`; at `LOST_PASSES` it treats the dongle as not present (same block as unplug, notify text `"The dongle stopped responding. Using the built-in adapter. Unplug it and plug it back in."`). A healthy pass resets the count; going present again follows the existing replug path.
- [ ] **Step 4:** whole `tests/test_hw.py` passes.
- [ ] **Step 5:** commit `A crashed dongle switches to the built-in adapter and asks to be re-plugged`.

### Task 6: Switching to a crashed dongle can't hang the switch

**Files:** Modify `hw.py:_use` (the "restart once" disable); Test `tests/test_hw.py`

**Interfaces:** Reuses the bounded-thread helper Task 3 introduced in `_finish` (if Task 3 inlined it, extract `_bounded(fn, seconds) -> (finished: bool, error: Exception | None)` and use it in both). Produces `hw.RESTART_LIMIT = 30` (s).

- [ ] **Step 1: Failing test** `test_switch_to_unresponsive_dongle_says_replug`: target Wi-Fi never gets an interface, `disable` blocks on an Event, `RESTART_LIMIT` lowered to 0.1 → `use()` raises `HwError` matching `"isn't responding. Unplug it and plug it back in"` and `hw._lock` is released.
- [ ] **Step 2:** run → FAIL (hangs: guard the test with a timeout via a thread join).
- [ ] **Step 3:** run the restart-once `_settled(disable, …)` through `_bounded(..., RESTART_LIMIT)`; not finished → `bail()` is skipped (don't touch the device again) and raise `HwError(f"The {_name(target)} isn't responding. Unplug it and plug it back in.{back}")`.
- [ ] **Step 4:** whole suite passes.
- [ ] **Step 5:** commit `Switching to an unresponsive dongle says to re-plug it instead of hanging`.

### Task 7: The right message for a crashed dongle in the pages

**Files:** Modify `api.py:_iface`; Test `tests/test_api.py`

- [ ] **Step 1: Failing test** `test_iface_of_crashed_dongle_says_replug`: no `unigen` interface, `hw.devices()` has `unigen` present → `networks("unigen")` error is `"The Unigen dongle isn't responding. Unplug it and plug it back in."`; with `unigen` absent from devices it stays `"… isn't plugged in."`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** in `_iface`, when the interface is missing, check `"unigen"`/key presence in `hw.devices()` (catch `_KNOWN` → old message).
- [ ] **Step 4:** `py -3.10 -m pytest -q` → all pass.
- [ ] **Step 5:** commit `A crashed dongle says to re-plug it, not that it's unplugged`.

### Task 8: Release 1.0.5 and install (needs the user's go-ahead)

- [ ] README "Known limitations"/"One switch" bullets: a crashed dongle is detected and the app asks to re-plug it; copy README to `level-1/Notes/Unigen-Manager/README.md`.
- [ ] `py -3.10 build_exe.py`; annotated tag `v1.0.5`; `gh release create v1.0.5 dist\UnigenManager.exe`; `version.py` → `bump()` (1.0.6) committed.
- [ ] Install: quit the running app (end the process if the hung thread blocks exit), copy the exe to `C:\Program Files\Unigen Manager`, start the "Unigen Manager" scheduled task, confirm `==== start: version 1.0.5` in app.log.
- [ ] Decision entry at the top of `level-1/Notes/decisions.md`.
