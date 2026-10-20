# Merge Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the dongle and the built-in Wi-Fi at the same time. A local proxy spreads new connections across both
adapters (net-merge's approach), with a Merge switch in the app.

**Architecture:** A new `merge.py` keeps a pool of links (adapter key, interface index, IPv4 address). A
least-active-per-weight scheduler picks a link for each new connection. The socket is bound to that adapter
(`IP_UNICAST_IF`). An asyncio SOCKS5 + HTTP proxy on 127.0.0.1 runs in a thread. A new `sysproxy.py` points Windows at
a PAC file the proxy serves, and sets the policy that keeps both adapters connected. Each change saves the old values
for restoring. In `hw.py`, the watchdog leaves both radios on while merge is on.

**Tech Stack:** Python 3.10 standard library only (asyncio, socket, ctypes, winreg), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-20-merge-connections-design.md`

## Global Constraints

- Standard library only. No TUN/Wintun, no bundled net-merge binary.
- With merge **off**, behaviour is exactly today's: the existing `tests/test_hw.py` must pass unchanged.
- Values fixed by the spec:
  - `COOLDOWN = 15.0` s
  - `PROBE_UP = 15.0` s, `PROBE_DOWN = 4.0` s, probe targets `("1.1.1.1", 443)` then `("8.8.8.8", 443)`
  - `REFRESH = 3.0` s
  - `PEAK_DECAY = 0.97`, `WEIGHT_FLOOR = 0.05`
  - `IP_UNICAST_IF = 31`
  - failover codes `{10049, 10050, 10051, 10060, 10065}` plus `TimeoutError`
- Proxy listens on `127.0.0.1` only, preferred `PORT = 18780`, falling back to any free port. PAC URL:
  `http://127.0.0.1:<port>/proxy.pac`. PAC body:
  `function FindProxyForURL(u, h) { return "PROXY 127.0.0.1:<port>; DIRECT"; }`
- User-facing text is plain language: where the user stands and what to do.
- Commits in this repo carry **no** Co-Authored-By or Claude trailers.
- Tests never touch the network, the registry or hardware. They replace `merge.open_on`, `merge.find_links`,
  `sysproxy`'s `reg` object, `hw.wifi_on/wifi_off/devices/_radios`.
- Run the suite with: `py -3.10 -m pytest -q`

## Review Focus

1. **The app is killed while merge is on.** Browsers must go direct (the PAC can't load), and the next start puts the
   saved proxy and policy values back (Task 4 test `test_restore_leftover_after_crash`).
2. **One link left (dongle unplugged) or none.** One link: the proxy carries everything through it. None: it answers
   at once with a SOCKS "network unreachable" (reply 0x03) or HTTP 502, never a hang (Task 3 test
   `test_no_links_fails_fast`).
3. **An adapter's IP changes** (it reconnected to another network). `Pool.update` replaces the address, and new
   connections use the new IP (Task 1 test `test_update_replaces_address_keeps_counts`).
4. **The client closes mid-transfer or half-closes.** The link's active count goes down exactly once (Task 3 test
   `test_active_released_once_on_early_close`).
5. **The host resolves only to IPv6.** The proxy replies with an error and keeps running (Task 2 test
   `test_dial_ipv6_only_host_errors`).

---

### Task 1: The link pool and scheduler

**Files:**
- Create: `merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Produces:
  - `merge.Link`, a dataclass with fields:
    - `key: str`, `index: int`, `ip: str`
    - `active: int = 0`
    - `state: str = "unknown"` (`"up"`, `"unknown"` or `"down"`)
    - `until: float = 0.0` (cooldown end), `peak: float = 0.0`, `weight: float = 1.0`
    - `opened: int = 0` (total connections)
  - `merge.Pool(clock=time.monotonic, rand=random.random)`, with methods:
    - `update(found: dict[str, tuple[int, str]]) -> None`
    - `pick(exclude: set[str] = frozenset()) -> Link | None`
    - `release(link: Link) -> None`
    - `sideline(key: str) -> None`
    - `mark(key: str, ok: bool) -> None`
    - `observe(key: str, bytes_per_s: float) -> None`
    - `links() -> list[Link]`

- [ ] **Step 1: Write the failing tests** in `tests/test_merge.py`:
  - `test_pick_least_active`: links a and b, both `up`. `pick()` returns a, then b, then a again (equal weights, with
    `rand` fixed so the tie-break starts at a). Each pick adds 1 to `active`, and `release` takes 1 off (never below 0).
  - `test_weight_scales_share`: a has weight 2 and b weight 1. Over six picks with none released, a gets 4 and b gets 2.
  - `test_best_tier_only`: a is `up` and b is `unknown`, so `pick()` always returns a. With a `down` and b `unknown`, it
    returns b.
  - `test_sidelined_skipped_then_back`: `sideline("a")` at t=0 → pick returns b until t=15.0, then a is eligible again.
    If every link is sidelined, `pick()` still returns the least-active one (it never refuses while a link exists).
  - `test_update_replaces_address_keeps_counts`: a link with active 2 gets a new ip from `update`. The ip changes and
    active stays 2. A key missing from `found` is dropped, and `pick` with no links returns None.
  - `test_observe_sets_weight_from_peak`: `observe("a", 10e6)` and `observe("b", 5e6)` give weights 1.0 and 0.5. With
    no traffic, each tick multiplies the peak by 0.97, and the weight never falls below 0.05.
- [ ] **Step 2:** Run `py -3.10 -m pytest tests/test_merge.py -v`. Expected: FAIL (no module `merge`).
- [ ] **Step 3: Implement** `Link` and `Pool` in `merge.py`, with the constants from Global Constraints.
  - `pick` score: `(active + 1) / max(weight, WEIGHT_FLOOR)`. Lowest wins, with ties broken from a start offset set by
    `rand()`. Tiers: `up` < `unknown` < `down`, and sidelined links (`until > clock()`) are left out unless every link
    is sidelined.
  - `observe`: `peak = max(rate, peak * PEAK_DECAY)`, `weight = max(WEIGHT_FLOOR, peak / max(all peaks))`, all 1.0
    while every peak is 0.
  - Guard everything with one `threading.Lock`: the asyncio thread and the probe thread both call in.
- [ ] **Step 4:** Run `py -3.10 -m pytest tests/test_merge.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `Merge: a pool of links with a least-active, weighted scheduler`.

### Task 2: Finding the links, binding sockets, probing, failover dial

**Files:**
- Modify: `traffic.py`. Split the row lookup out of `counters` into `_row(guid) -> MIB_IF_ROW2`, and add
  `if_index(guid) -> int`.
- Modify: `merge.py`
- Test: `tests/test_merge.py`, `tests/test_traffic.py` (counters keeps working)

**Interfaces:**
- Consumes: `Pool`, `Link` (Task 1). `wifi.radios()` returns `{key: {"guid", "on"}}`. `traffic.if_index(guid)`.
- Produces:
  - `merge.ipv4_by_index() -> dict[int, str]`: ctypes `GetIpAddrTable`, skipping `0.0.0.0` and `169.254.*`.
  - `merge.find_links() -> dict[str, tuple[int, str]]`: radios that are on, have an index, and have an IPv4 address.
  - `merge.open_on(link: Link, addr: tuple[str, int], timeout: float = 10.0) -> socket.socket`: blocking. It does
    `setsockopt(IPPROTO_IP, IP_UNICAST_IF, struct.pack(">I", index))`, then `bind((ip, 0))`, then `connect`.
    Tests replace it.
  - `merge.probe(link: Link) -> bool`: `open_on` to each probe target with a 3 s timeout; True on the first success.
  - `async merge.dial(pool: Pool, host: str, port: int) -> tuple[socket.socket, Link]`. Raises `merge.DialError(code)`,
    where code is a SOCKS reply code: 3 = network unreachable, 4 = host unreachable, 5 = refused.

- [ ] **Step 1: Write the failing tests:**
  - `test_find_links_skips_off_and_unaddressed`: `wifi.radios`, `traffic.if_index` and `merge.ipv4_by_index` are
    replaced. An adapter whose radio is off, or that has no IPv4 address, is left out.
  - `test_dial_fails_over_on_unreachable`: `open_on` raises `OSError(10051, ...)` for link a and returns a fake socket
    for b. `dial` returns b, a is sidelined, and a's `active` is back to 0.
  - `test_dial_refused_is_not_failover`: `OSError(10061)` raises `DialError(5)` and sidelines nothing.
  - `test_dial_no_links`: `DialError(3)`.
  - `test_dial_ipv6_only_host_errors`: `getaddrinfo` (`AF_INET`) raises `socket.gaierror`, giving `DialError(4)`.
  - In `tests/test_traffic.py`: `test_if_index_reads_row` replaces `_row` and checks `if_index` returns
    `InterfaceIndex`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `dial` resolves with `loop.getaddrinfo(host, port, family=AF_INET, type=SOCK_STREAM)`. It then tries
    `pool.pick(exclude=tried)` on up to `len(pool.links())` links, running `open_on` through
    `loop.run_in_executor`. A failover error (from Global Constraints) leads to `pool.sideline`,
    `pool.release(link)` and the next link. Any other `OSError` leads to `release` and `DialError(5)`.
  - On success it sets `link.opened += 1` and returns the socket set non-blocking.
- [ ] **Step 4:** Run `py -3.10 -m pytest tests/test_merge.py tests/test_traffic.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `Merge: find both Wi-Fi links and dial out of one, failing over to the other`.

### Task 3: The proxy server (SOCKS5, HTTP CONNECT, plain HTTP, PAC)

**Files:**
- Modify: `merge.py`
- Test: `tests/test_merge_proxy.py`

**Interfaces:**
- Consumes: `dial`, `DialError`, `Pool` (Tasks 1–2).
- Produces: `merge.Proxy(pool: Pool)`, with:
  - `async start(port: int = PORT) -> int`: falls back to port 0 on `OSError`, and returns the port it listens on.
  - `async stop() -> None`
  - `pac() -> str`
  - `bytes: dict[str, list[int]]`: per link key, `[down, up]`, cumulative.

- [ ] **Step 1: Write the failing tests.** They use a real asyncio echo server on 127.0.0.1, with `merge.open_on`
  replaced by a plain `socket.create_connection` and a pool with one link ip `127.0.0.1`.
  - `test_socks5_connect_echo`: greeting `05 01 00` gets `05 00`. CONNECT to an IPv4 address and to a domain name both
    reply `05 00 …`, then the bytes echo back.
  - `test_http_connect_echo`: `CONNECT 127.0.0.1:<echo> HTTP/1.1` gets `HTTP/1.1 200 Connection established`, then
    the bytes echo back.
  - `test_http_get_absolute_uri`: `GET http://127.0.0.1:<srv>/x HTTP/1.1` reaches a tiny HTTP server as `GET /x`,
    with `Connection: close`, and the response is relayed.
  - `test_serves_pac`: `GET /proxy.pac` to the proxy itself returns `200` with content type
    `application/x-ns-proxy-autoconfig` and the exact PAC body from Global Constraints with the real port.
  - `test_no_links_fails_fast`: an empty pool gives a SOCKS reply `05 03` and HTTP CONNECT `502`, both within 1 s.
  - `test_active_released_once_on_early_close`: the client closes right after CONNECT, so after a tick `active == 0`.
    A half-close (client `write_eof`) still lets the server's reply through before `active` drops to 0.
  - `test_counts_bytes_per_link`: after echoing 1000 bytes, `proxy.bytes["a"] == [1000, 1000]`.
  - `test_port_busy_falls_back`: with 18780 held by another socket, `start()` returns a different port.
- [ ] **Step 2:** Run `py -3.10 -m pytest tests/test_merge_proxy.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the handler with `asyncio.start_server` on 127.0.0.1.
  - Peek the first byte: `0x05` means SOCKS5 (CONNECT only, no auth, other commands get reply `07`). Anything else is
    HTTP: read headers up to 64 KiB.
  - HTTP: `CONNECT` tunnels. `GET /proxy.pac` with a relative path returns the PAC. An absolute URI is forwarded with
    the request line rewritten to origin form, `Proxy-Connection` dropped and `Connection: close` forced.
  - Relay: two pumps with `write_eof` passed on. `pool.release(link)` runs in one `finally`.
- [ ] **Step 4:** Run `py -3.10 -m pytest tests/test_merge_proxy.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `Merge: a local SOCKS5 and HTTP proxy that spreads connections over the links`.

### Task 4: System proxy and the keep-both-connected policy, restorable

**Files:**
- Create: `sysproxy.py`
- Test: `tests/test_sysproxy.py`

**Interfaces:**
- Produces:
  - `sysproxy.Reg` (the real winreg wrapper), with:
    - `get(hive, path, name) -> object | None`
    - `put(hive, path, name, value, kind) -> None`
    - `delete(hive, path, name) -> None`
  - `sysproxy.apply(pac_url: str, settings: Path, reg=Reg()) -> None`: saves the current `AutoConfigURL` and
    `fMinimizeConnections` values (None if absent) under settings.json `"merge_saved"`, but only when no saved copy
    exists yet. Then it sets `AutoConfigURL` = pac_url and `fMinimizeConnections` = 0 (REG_DWORD), and calls `_refresh()`.
  - `sysproxy.restore(settings: Path, reg=Reg()) -> bool`: puts back the saved values, deleting any that were None,
    removes `"merge_saved"`, calls `_refresh()`, and returns whether anything was restored.
  - `sysproxy._refresh()`: `InternetSetOptionW(None, 39, None, 0)` and then `(None, 37, None, 0)`. Tests replace it.
  - Registry paths:
    - HKCU `Software\Microsoft\Windows\CurrentVersion\Internet Settings`, value `AutoConfigURL`
    - HKLM `SOFTWARE\Policies\Microsoft\Windows\WcmSvc\GroupPolicy`, value `fMinimizeConnections`

- [ ] **Step 1: Write the failing tests** with a dict-backed fake `reg`:
  - `test_apply_then_restore_absent_values`: nothing set → after `apply`, both values are set. After `restore`, both
    are deleted and `"merge_saved"` is gone.
  - `test_restore_puts_back_old_pac`: an existing `AutoConfigURL` `"http://corp/pac"` is back after `restore`.
  - `test_apply_twice_keeps_first_saved`: a second `apply` with another port doesn't overwrite the saved originals.
  - `test_restore_leftover_after_crash`: a settings file holding `"merge_saved"` (from a crashed run) →
    `restore` returns True and the registry is back to the saved values. With no leftover, it returns False and
    changes nothing.
  - `test_other_settings_kept`: `"wifi"` and `"traffic_unit"` survive both `apply` and `restore` (use
    `hw.save_choice`-style merge writes).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** `sysproxy.py`.
- [ ] **Step 4:** Run `py -3.10 -m pytest tests/test_sysproxy.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `Merge: point Windows at the proxy and keep both adapters connected, restorably`.

### Task 5: The watchdog keeps both radios on while merging

**Files:**
- Modify: `hw.py` (`load_merge`, `set_merge`, `Follower._step`)
- Test: `tests/test_hw.py`

**Interfaces:**
- Produces:
  - `hw.load_merge(path) -> bool`: settings.json `"merge"` is True. False for anything else or a missing file.
  - `hw.set_merge(on: bool, *, path) -> None`. It takes `_lock` (raising `_busy()` if it's held) and saves
    `"merge": on`.
    - On: it calls `wifi_on(other, dev)` for the adapter that isn't the Wi-Fi choice, if that adapter is present.
    - Off: it calls `wifi_off(other, dev)`.
    - Both run through `_bounded(..., BT_STUCK)`. A failure raises `HwError("Couldn't turn the {name} on/off.")`.

- [ ] **Step 1: Write the failing tests:**
  - `test_watchdog_leaves_both_on_when_merging`: choice `unigen`, merge true, both Wi-Fi `ok`. `step()` doesn't call
    `wifi_off` and doesn't switch.
  - `test_watchdog_turns_other_on_when_merging`: merge true, built-in Wi-Fi radio off → `wifi_on("builtin", …)`
    is called once.
  - `test_merge_off_still_turns_other_off`: the same world with merge false behaves as today (`wifi_off` called).
  - `test_unplug_while_merging_falls_back`: merge true, dongle absent → the existing built-in fallback runs and the
    user is notified once.
  - `test_set_merge_busy`: with `_lock` held, `set_merge(True, path=…)` raises `Busy`.
- [ ] **Step 2:** Run `py -3.10 -m pytest tests/test_hw.py -v`. Expected: the new tests FAIL and the existing ones pass.
- [ ] **Step 3: Implement.** In `Follower._step`, read `merge = load_merge(self._path)`.
  - The first-start switch and the both-on `wifi_off` branch only run when `not merge`.
  - When `merge` is on, the dongle is present and the other adapter's Wi-Fi is `disabled` (radio off), call
    `wifi_on(key, other["wifi"])`.
- [ ] **Step 4:** Run `py -3.10 -m pytest -q`. Expected: everything passes.
- [ ] **Step 5: Commit** `Merge: the watchdog keeps both Wi-Fi radios on while merging`.

### Task 6: Wiring: the Merger runner, api and app

**Files:**
- Modify: `merge.py` (adds `Merger`), `api.py`, `app.py`
- Test: `tests/test_merge.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: everything above. `traffic.Sampler.rate(key)` gives `(down, up)` bytes per second.
- Produces:
  - `merge.Merger(rate=lambda key: None)`:
    - `start() -> int`: runs an asyncio loop in a daemon thread named `merge`, starts `Proxy`, and returns its port.
      Every `REFRESH` seconds it calls `pool.update(find_links())` and `pool.observe(key, down)` from `rate`.
    - The probe runs per link on `PROBE_UP` / `PROBE_DOWN` and calls `pool.mark`.
    - `stop() -> None`: idempotent.
    - `status() -> list[dict]`: per link `key`, `state`, `active`, `opened`, `down`, `up`.
    - `port: int | None`
  - `Api.merge_status()`, polled (add it to `_POLLED`). Returns:
    - `on: bool`, `port`, `wcm: bool` (whether `fMinimizeConnections` is 0)
    - `links`, each with the adapter's `name` added
    - `same_network`: the SSID when both adapters are connected to the same SSID, else None
  - `Api.set_merge(on)`: `_need_admin("Merging connections")`, then `hw.set_merge`. Then:
    - On: `merger.start()`, then `sysproxy.apply(f"http://127.0.0.1:{port}/proxy.pac", settings)`.
    - Off: `sysproxy.restore` and `merger.stop()`.
    - Pushes `window.onMerge && window.onMerge()`.
  - `app.py`:
    - At start, before the windows: `sysproxy.restore(settings)` (a crash leftover).
    - In `after_start`: if `hw.load_merge` → `merger.start()` + `sysproxy.apply`.
    - In `quit_app`: `sysproxy.restore` + `merger.stop()`. The `"merge"` setting stays, so the next start resumes.

- [ ] **Step 1: Write the failing tests:**
  - `test_merger_status_after_refresh`: `find_links` gives two links and `rate` gives a 4e6 / 2e6 down rate. After one
    refresh, both links appear and their weights are 1.0 and 0.5.
  - `test_set_merge_on_applies_proxy_and_off_restores`: `hw.set_merge`, `sysproxy.apply/restore` and `Merger` are
    replaced. The call order is right and the PAC URL carries the merger's port.
  - `test_set_merge_needs_admin`: without admin, it fails with the admin message and nothing is called.
  - `test_merge_status_same_network`: both adapters are connected to "Home" → `same_network == "Home"`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** as above. `Api.__init__` takes `merger=None` (default `merge.Merger(rate=sampler.rate)`).
- [ ] **Step 4:** Run `py -3.10 -m pytest -q`. Expected: everything passes.
- [ ] **Step 5: Commit** `Merge: the Merge switch turns the proxy and system settings on and off`.

### Task 7: The Merge card and the widget toggle

**Files:**
- Modify: `ui/index.html` (a Merge card at the top of the `#traffic` section), `ui/widget.html` (a Merge switch row
  under the Wi-Fi adapter switch), `ui/shared.js` (if a helper is shared), `ui/mock-api.js` (`merge_status`,
  `set_merge`)
- Test: `tests/test_shared_frontend.py` / `tests/ui` (follow the existing pattern for new mock calls)

**Interfaces:**
- Consumes: `merge_status()`, `set_merge(on)`, and the `window.onMerge` push (Task 6).

- [ ] **Step 1:** Add the mock calls, plus a frontend test that the card renders two link rows from the mock and that
  the toggle calls `set_merge(true)`. Run it: FAIL.
- [ ] **Step 2: Build the card** in the app's existing brutalist style (same switch component as Bluetooth power).
  - The switch is labelled **Merge connections**.
  - One row per adapter: a state dot (up green, checking grey, down red), its share of open connections, and its live
    down/up rate (reuse `fmtRate`).
  - The `same_network` note: "Both adapters are on {ssid}: little speed gain. Connect one to another network (a phone
    hotspot) to add speed."
  - A help line: "Speeds up apps that open many connections (browsers, Steam, download managers). One download can't
    go faster than one adapter. Games and Windows Update aren't merged."
  - Without admin, the switch is disabled with the existing admin hint.
  - The widget gets the same switch, plus a "Merged" badge when on.
- [ ] **Step 3:** Run `py -3.10 -m pytest -q`. Expected: everything passes. Check the mock in a browser (Playwright
  screenshot) at the widget's width.
- [ ] **Step 4: Commit** `Merge: a Merge card on the Traffic page and a switch in the widget`.

### Task 8: Hardware check, README, release (needs the user's go-ahead)

- [ ] **Manual check on this PC:**
  - Connect the dongle to home Wi-Fi and the built-in card to a phone hotspot (two different networks). Turn Merge on.
    Both links show `up`.
  - After 2 minutes idle, both are still connected (the WCM policy is working).
  - A parallel download (Steam, or aria2 `-x8`) uses both rates on the Traffic page.
- [ ] **Crash check:**
  - Kill the app (Task Manager) while merging. The browser still loads pages (PAC unreachable, so DIRECT).
  - Start the app again: the proxy settings are restored, or reapplied if merge is on.
- [ ] **README:**
  - A "Merge connections" feature section with the limits from the spec.
  - Under Security: the app changes the user's proxy setting and one Windows policy while merging, and puts them back.
  - Copy the README to `level-1/Notes/Unigen-Manager/README.md`, and copy this plan to
    `level-1/Notes/Unigen-Manager/Merge-PLAN.md`.
- [ ] **Release:** `py -3.10 build_exe.py`, then an annotated tag, then `gh release create` with
  `dist\UnigenManager.exe`, then bump `version.py`. Install to `Desktop\Temp` with the elevated script, as in earlier
  releases.
