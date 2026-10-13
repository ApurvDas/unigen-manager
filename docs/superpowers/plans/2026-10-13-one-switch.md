# One switch for Wi-Fi and Bluetooth: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. TDD on every task: write the test, watch it fail, implement, watch it pass, commit.

**Goal:** One **Using: Dongle | Built-in** control moves Wi-Fi and Bluetooth together. The adapter not in use is disabled in Device Manager, the choice is remembered, a watchdog follows dongle unplug and replug, and steps are shown live.

**Spec:** `docs/superpowers/specs/2026-10-13-one-switch-design.md` (binding).

**Branch:** `bluetooth-primary` (continues on top of the Bluetooth work, and ships in 1.0.2).

## Global Constraints

- **Python and tests:** run Python as `py -3.10` and the suite as `py -3.10 -m pytest -q`. UI tests use Playwright with msedge, in `tests/ui`.
- **Test data:** fixtures never contain real SSIDs, device names or addresses. Use "HOME-5G" and made-up instance ids.
- **Process control:** never use `taskkill /IM`. The user's installed copy runs as UnigenManager.exe.
- **Errors:** every error the user sees is a plain sentence that says where they stand.
- **Mock parity:** `ui/mock-api.js` defines exactly the public `Api` methods. `test_mock_api_matches_python_api` enforces this.
- **UI style:** dark only. Motion uses the `ui/shared.js` helpers (`swap`, `busy`, `setMsg`, `slide`, `arrive`) and respects `reduce`.
- **Ledger:** `.superpowers/sdd/2026-10-13-one-switch/progress.md`. Write one completion line per task, and log every deviation as `Task N: Ruling: <what> — <why> — <cost if wrong>`.

## Review Focus

1. **Dongle unplugged mid-switch:** `use("unigen")` must roll back and leave the built-in adapter working. Test: `test_use_target_wifi_never_appears_restarts_once_then_rolls_back`.
2. **Old adapter not connected to anything:** skip the connect step, and still enable the target and disable the old adapter. Test: `test_use_without_network_skips_connect`.
3. **Replug switch fails:** the watchdog must not retry on every pass. Test: `test_follow_failed_replug_does_not_retry`.
4. **App running without admin:** `follow` and `switch_to` must change nothing. Tests: `test_follow_noop_without_admin`, `test_switch_to_needs_admin`.
5. **An adapter is off:** the Wi-Fi page must never call `networks()` or `scan()` for it. Test: `test_off_adapter_not_selectable`.

---

### Task 1: `hw.py` device list, choice file, and PowerShell helper

**Files:**
- Create: `hw.py`, `hw.ps1`
- Test: `tests/test_hw.py`

**Produces:**
- `hw.HwError(Exception)`
- `hw.device_key(instance_id, name) -> ("unigen"|"builtin"|None, "wifi"|"bt"|None)`
- `hw.devices() -> {key: {"present": True, "wifi": dev|None, "bt": dev|None}}`, where `dev = {"id", "ok", "disabled"}` and a key that isn't present is simply absent
- `hw.enable(id)` and `hw.disable(id)`
- `hw.load_choice(path) -> key|None` and `hw.save_choice(path, key)`
- `hw._ps`, a test seam that defaults to `winrun.ps`

**`hw.ps1`:**
- Action `devices`: `Get-PnpDevice -PresentOnly -Class Net,Bluetooth | Where-Object { $_.InstanceId -match '^(USB|PCI)\\' }`, output as JSON `[{id, name, status, problem}]` with `ConvertTo-Json -InputObject @(...) -Compress`.
- Actions `enable` and `disable`: the same as in `bt.ps1`.
- Read inputs from `$p`, the same way `bt.ps1` does.

**`device_key` rules:**
- `VID_368B&PID_8D81`: `MI_02` → `("unigen", "wifi")`, `MI_00` → `("unigen", "bt")`.
- `VEN_14C3&DEV_7961` or "MT7921" in the name → `("builtin", "wifi")`.
- `VID_13D3&PID_3563` → `("builtin", "bt")`.
- Anything else, for example the Realtek Ethernet device → `(None, None)`.
- A dev counts as ok when `status == "OK"`, and as disabled when `problem in ("CM_PROB_DISABLED", "22")`.

**Tests:**
- `test_device_key_maps_known_ids`, including an Ethernet device that maps to `(None, None)`.
- `test_devices_groups_by_adapter`: fake `_ps` returns the four devices plus Ethernet. Assert the dict shape, and that the disabled built-in Bluetooth shows `ok` False and `disabled` True.
- `test_devices_without_dongle`: `"unigen" not in devices()`.
- `test_choice_roundtrip`: uses `tmp_path`. A missing file gives None, a corrupt file gives None, and `save_choice` then `load_choice` returns the key.
- `test_enable_disable_pass_id_as_param`: the id travels only in `params`, never in the script text.

---

### Task 2: `hw.use` (the switch, with rollback)

**Files:**
- Modify: `hw.py`
- Test: `tests/test_hw.py`

**Consumes:**
- `wifi.interfaces()`, `wifi.adapter_key(desc)`, `wifi.profiles()`, `wifi.profile_name()`, `wifi.copy_profile(ssid, src, dst)`, `wifi.connect(iface, ssid, saved=True)` and `wifi.ADAPTER_NAMES`
- `bt.switch(key)`, which raises `bt.BtError` and does its own rollback

**Produces:** `hw.use(target, *, on_step=lambda text: None, path, wait=20.0, clock=time.monotonic, sleep=time.sleep) -> target`

Implementation (adapt names to the real modules; keep the order):

```python
_lock = threading.Lock()


def _name(k):
    return wifi.ADAPTER_NAMES.get(k, k)


def _iface(key):
    return next((i for i in wifi.interfaces() if wifi.adapter_key(i["description"]) == key), None)


def _wait_iface(key, wait, clock, sleep):
    deadline = clock() + wait
    while clock() < deadline:
        i = _iface(key)
        if i:
            return i
        sleep(1)
    return None


def use(target, *, on_step=lambda t: None, path, wait=20.0, clock=time.monotonic, sleep=time.sleep):
    if not _lock.acquire(blocking=False):
        raise HwError("A switch is already running.")
    try:
        return _use(target, on_step, path, wait, clock, sleep)
    finally:
        _lock.release()


def _use(target, on_step, path, wait, clock, sleep):
    devs = devices()
    if target not in devs:
        raise HwError(f"The {_name(target)} isn't plugged in.")
    old = next((k for k in devs if k != target), None)
    t, o = devs[target], devs.get(old) or {}
    back = f" You're still on the {_name(old)}." if old else ""
    # already in use: target Wi-Fi on, the old one off (or no old one)
    if t["wifi"] and t["wifi"]["ok"] and not (o.get("wifi") and o["wifi"]["ok"]):
        save_choice(path, target)
        on_step(f"Done. Using the {_name(target)}.")
        return target
    old_iface = _iface(old) if old else None
    on_step(f"Turning on the {_name(target)}…")
    if t["wifi"]:
        enable(t["wifi"]["id"])
        if not _wait_iface(target, wait, clock, sleep):
            disable(t["wifi"]["id"]); enable(t["wifi"]["id"])  # restart once: clears a half-started driver
            if not _wait_iface(target, wait, clock, sleep):
                _undo(t)
                raise HwError(f"The {_name(target)}'s Wi-Fi didn't start.{back}")
    try:
        ssid = old_iface.get("ssid") if old_iface and old_iface.get("state") == "connected" else None
        if ssid:
            on_step(f"Connecting to {ssid}…")
            ti = _iface(target)
            names = wifi.profiles().get(ti["name"], [])
            if ssid not in names and wifi.profile_name(ssid) not in names:
                wifi.copy_profile(old_iface.get("profile") or ssid, old_iface["name"], ti["name"])
            wifi.connect(ti["name"], ssid, saved=True)
        if t["bt"] and o.get("bt"):
            on_step("Moving Bluetooth…")
            bt.switch(target)
    except (wifi.WifiError, bt.BtError, winrun.CmdError) as e:
        log.warning("switch to %s failed: %s", target, e)
        _undo(t)
        raise HwError(f"Couldn't finish switching to the {_name(target)}.{back}")
    if o.get("wifi"):
        on_step(f"Turning off the {_name(old)}…")
        try:
            disable(o["wifi"]["id"])
        except winrun.CmdError:
            on_step(f"The {_name(old)} couldn't be turned off; Windows may still use it.")
    save_choice(path, target)
    on_step(f"Done. Using the {_name(target)}.")
    return target


def _undo(t):
    """Best effort: turn the target's Wi-Fi back off so the old adapter is exactly as it was."""
    if t["wifi"] and t["wifi"]["disabled"]:
        try:
            disable(t["wifi"]["id"])
        except winrun.CmdError:
            pass
```

Note: only roll back the target's Wi-Fi if it was disabled before the switch. `_undo` checks the pre-switch `t` snapshot.

**Tests:** fake `devices`, `enable`, `disable`, `wifi.*` and `bt.switch`, recording calls into one `calls` list. `sleep` is a no-op and `clock` is an iterator.
- `test_use_full_switch_order`: built-in in use and connected to HOME-5G, dongle Wi-Fi disabled. Expected calls in order: enable unigen-wifi, copy_profile (dongle lacks it), connect(dongle iface, HOME-5G), bt.switch("unigen"), disable builtin-wifi. The choice file says "unigen". The steps are the 5 texts in order.
- `test_use_without_network_skips_connect`: no connect or copy calls, and the old Wi-Fi is still disabled.
- `test_use_target_wifi_never_appears_restarts_once_then_rolls_back`: calls are enable, disable, enable, then disable (undo), and the old adapter is never touched. Raises "didn't start. You're still on the Built-in MediaTek." The choice file is unchanged.
- `test_use_connect_fails_rolls_back`: `wifi.connect` raises `WifiError`, giving a final disable of the target Wi-Fi with no `bt.switch` call. Raises HwError, and the choice is unchanged.
- `test_use_bt_fails_rolls_back_wifi`: same as above, but `bt.switch` raises.
- `test_use_already_in_use_only_saves_choice`
- `test_use_old_wifi_disable_fails_still_succeeds`
- `test_second_concurrent_use_refused`

---

### Task 3: `hw.follow` (the watchdog)

**Files:**
- Modify: `hw.py`
- Test: `tests/test_hw.py`

**Produces:** `class Follower(path, notify, *, admin, use=use)` with a `step()` method. The tray thread calls `step()` every 5 s, and `notify(text, changed: bool)` reports what happened.

**Logic:**
- **First `step()`:** if the choice is set and its adapter is present, check whether the other adapter's Wi-Fi is enabled and ok. If so, call `use(choice)`. On failure, notify the message once.
- **Choice is "unigen" and unigen is absent:** if the built-in Wi-Fi or Bluetooth is disabled, enable it, then `notify("The dongle was unplugged. Using the built-in adapter.", True)`. Do this once per absence.
- **unigen was absent on the previous step and is present now, with the choice "unigen":** call `use("unigen")`, then `notify("Dongle plugged in. Using the dongle.", True)`. On `HwError`, call `notify(str(e), False)`. Either way, wait for the next absence before trying again.
- **`admin=False`:** `step()` returns immediately.
- **Exceptions:** `step()` never raises. Log anything unexpected.

**Tests:**
- `test_follow_unplug_enables_builtin_once`: two steps while absent. Enable is called for the built-in Wi-Fi and Bluetooth exactly once, and there is one notify.
- `test_follow_replug_switches_back_once`
- `test_follow_failed_replug_does_not_retry`: `use` raises. Over three more present steps, `use` is called only once.
- `test_follow_startup_enforces_choice`
- `test_follow_noop_without_admin`
- `test_follow_without_choice_does_nothing`

---

### Task 4: API: `switch_to`, the `app_info` shape, watchdog wiring, removals

**Files:**
- Modify: `api.py`, `app.py`, `tray.py`, `ui/mock-api.js`
- Test: `tests/test_api.py`, `tests/test_app.py` and `tests/test_tray.py` where touched

**Changes:**
- **`_KNOWN`:** add `hw.HwError`.
- **`Api.__init__`:** add `settings_path=DATA_DIR / "settings.json"`, stored as `self._settings`.
- **`switch_to(key)`:** if not admin, raise `hw.HwError("Switching adapters needs administrator rights. Restart the app and choose Yes.")`. Otherwise:
  - Run `hw.use(key, on_step=self._push_step, path=self._settings)`.
  - On success, push a final `{"text": <last step>, "done": True, "error": False}`. On `HwError`, push `{"text": str(e), "done": True, "error": True}` and re-raise.
  - Return `{"using": key}`.
  - `_push_step(text)` evaluates `window.onSwitchStep && window.onSwitchStep({...})` in both windows, the way `_push_sample` does.
- **`app_info`:** build adapters from the union of `hw.devices()` keys and `wifi.interfaces()` keys. Each adapter is `{key, name, wifi, bt, using, off}`:
  - `off`: the adapter's Wi-Fi device is disabled.
  - `using`: the key equals `hw.load_choice(self._settings)`. When there's no choice, `using` is true for the connected adapter, or else the first one that isn't off.
  - The top level gets a `using` key.
  - The Wi-Fi standard of an off adapter comes from `drivers()` if present, otherwise None.
  - If `hw.devices()` raises a known error, fall back to the current behaviour with `off` False.
- **`adapters()`:** unchanged. It still lists only the interfaces that are on.
- **Removals:** delete `use_adapter` and `bt_switch`, and their tests. Keep `bt.switch`.
- **Watchdog:** `_follow_notify(text, changed)`:
  - Calls `self._notify(text)`, a callable set by `app.py` to the tray's `icon.notify`; it defaults to a no-op.
  - If `changed`, pushes `window.onUsingChanged && window.onUsingChanged()` to both windows.
- **`app.py` `after_start`:**
  - Create `hw.Follower(api._settings, api._follow_notify, admin=api._admin)`.
  - Start a daemon thread: `while not stop.wait(5): follower.step()`. Run one `step()` before the first wait.
  - Set `api._notify = lambda t: icon.icon.notify(t, "Unigen Manager")`. Check the `tray.Tray` attribute name.
- **`ui/mock-api.js`:**
  - Add `let USING = "unigen"`.
  - `app_info` adapters gain `using: a.key === USING` and `off: a.key !== USING`. `MOCK_UNPLUG` still removes the dongle.
  - `def("switch_to", 0, async key => {...})`: if `MOCK_ADMIN === false`, throw the admin message. Otherwise, for each of the four step texts, call `window.onSwitchStep({text, done: false, error: false})` and wait 300 ms (0 under `MOCK_FAST`). Set `USING = key`, push a final done step, and return `{using: key}`.
  - `MOCK_FAIL.switch_to` works through `def`. Remove the `use_adapter` and `bt_switch` mocks.
  - Mock `adapters()` returns only the adapter in use.

**Tests:**
- `test_switch_to_needs_admin`
- `test_switch_to_pushes_steps_and_final`, using a fake window that records scripts
- `test_switch_to_error_pushes_error_and_returns_message`
- `test_app_info_lists_off_adapter`: `hw.devices` has both adapters, with the built-in Wi-Fi disabled, and `wifi.interfaces` lists only the dongle. Assert both adapters are present, the built-in `off` is True, and `using` is "unigen".
- `test_follow_notify_pushes_reload_when_changed`
- Mock parity passes.

---

### Task 5: Main window and widget UI

**Files:**
- Modify: `ui/index.html`, `ui/widget.html`, `ui/shared.css` (if a shared segmented style is needed)
- Test: `tests/ui/test_ui.py`, `tests/ui/test_widget.py`

**Main window:**
- **Side menu:** above `<h2>Adapters</h2>`, add `<h2 id="usingLbl">Using</h2><div class="seg" id="using" role="radiogroup" aria-labelledby="usingLbl"></div><p class="msg" id="switchMsg"></p>`. Reuse the widget's segmented-control styling: move it into `shared.css` if the main page doesn't have it.
- **Building the control:** buttons `data-k`, built from `INFO.adapters`, labelled "Dongle" and "Built-in". `aria-checked` follows `INFO.using`, and a sliding `.ind` highlight uses `slide()`.
- **Adapter rows:** the row with `using` true gets an **In use** tag. A row with `off` true gets an **Off** tag, the `off` class and `aria-disabled="true"`, and clicking it does nothing. The Wi-Fi page's active adapter is always the one in use.
- **Click handler:**
  - If the button is already checked or the control is busy, do nothing.
  - Otherwise disable all the buttons and call `switch_to`.
  - `window.onSwitchStep = s => setMsg($("#switchMsg"), s.text, s.error)`.
  - On success, re-fetch `app_info` and re-render: the side menu, the Wi-Fi page and `loadBt()` if the Bluetooth page is open.
  - On error, restore the selection and show the message.
  - If `!INFO.admin`, the buttons are disabled with the title "Switching adapters needs administrator rights."
- **Bluetooth page:** remove `#tryRadio` and its handler. `renderRadio` keeps the "Bluetooth is running on the …" text and drops `#btOther`'s switch hint ("The … radio is turned off." can stay).
- **`window.onUsingChanged`:** re-fetches `app_info` and re-renders, the same as after a successful switch.

**Widget:**
- **Using control:** the existing **Wi-Fi uses** segmented control becomes **Using** (label text and `aria`). It calls `switch_to` instead of `use_adapter`, with steps shown in `#wifiMsg` through `onSwitchStep`. `uses` is initialised from `app_info().using`.
- **Bluetooth row:** remove the `#btSwitch` button and its handler.
- **`window.onUsingChanged`:** reloads `poll()`, `loadNets()`, `loadBt()` and `loadSpeed(true)`.

**UI tests (mock):**
- **Update existing:** `test_bt_radio_switch_changes_label` (the Bluetooth label now changes through `#using`) and `test_bt_switch_needs_admin` (now asserts `#using button` is disabled). Update or remove any widget tests that use `use_adapter` or `#btSwitch`.
- `test_using_switch_main`: click "Built-in" in `#using`. `#switchMsg` ends with "Done. Using the Built-in MediaTek.", the built-in row shows "In use", the dongle row shows "Off", and the Bluetooth tab label becomes "Bluetooth 5.2" (the mock's built-in BT version).
- `test_off_adapter_not_selectable`: clicking the Off row doesn't change `aria-pressed`, and `MOCK_LOG` gets no `networks` or `scan` call for that key.
- `test_using_switch_error_restores`: with `MOCK_FAIL = {switch_to: "Couldn't finish switching to the Built-in MediaTek. You're still on the Unigen dongle."}`, the selection goes back and the message shows.
- `test_using_needs_admin`
- `test_using_changed_event_reloads`: `page.evaluate` flips the mock's `USING` (expose `window.mockApi._setUsing` or reuse a test hook) and fires `onUsingChanged()`. The labels update.
- `test_widget_using_switch`: the widget's Using control switches and shows the steps.

---

### Task 6: Hardware test, docs, build

**Files:**
- Modify: `tests/hardware/test_readonly.py`, `README.md`

**Steps:**
1. Add the hardware test `test_hw_devices_finds_both_adapters`: both keys are present, and each has `wifi` and `bt` that aren't None. It's skipped when the dongle isn't plugged in.
2. Update the README:
   - Features: one Using switch, choice remembered, follows unplug/replug.
   - Admin note.
   - Remove the text about the old separate switches.
   - Update the test counts.
3. Run the full suite, then build with `py -3.10 build_exe.py`.
4. Don't launch `dist\UnigenManager.exe` while the installed copy runs. Smoke-test with a throwaway build that imports `hw` and calls `hw.devices()`, as was done for the Bluetooth work.
5. Commit. Don't push, release or install.
