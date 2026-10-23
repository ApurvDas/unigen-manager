# Merge connections: use both Wi-Fi adapters at once (and Ethernet, and USB tethering)

**Source:** the user wants net-merge's capabilities (github.com/rohit267/net-merge, MIT, Go, v0.3.3 on 2026-10-20) in Unigen
Manager. The user asked to plan straight from the research, without the design Q&A, so every choice below that isn't
"from net-merge" is **Claude's call**, which the user reviews along with the plan.

## What net-merge does (the part we copy)
- **Per-connection balancing, not bonding.** Each new TCP connection leaves from one physical adapter. The socket is
  bound to that adapter's IPv4 address, with `IP_UNICAST_IF` (option 31, the interface index in network byte order)
  so Windows can't route it elsewhere.
- **Scheduler:** weighted least-active, score = (active + 1) / weight, with a random tie-break. Adapters are in tiers
  (internet confirmed > not yet checked > failed), and only the best non-empty tier is used. Weights follow each link's
  measured peak throughput (decays ×0.97, floor 0.05, idle links drift back up).
- **Failover:** network-unreachable, address-not-available and timeout dial errors sideline the adapter for 15 s and
  retry on another. The Windows codes are 10049, 10050, 10051, 10060 and 10065.
- **Internet probe:** a TCP connect to 1.1.1.1:443 and 8.8.8.8:443, bound to the adapter. It runs every 15 s while the
  adapter works and every 4 s while it is failing.
- **SOCKS5 mode** (CONNECT only, 127.0.0.1, no admin). The system-wide TUN mode (Wintun driver) is **not** copied.

## Limits the user should know (shown in the app's help line)
- One connection uses one link, so a single download is never faster than one adapter. Gains come from apps that open
  many connections: browsers, Steam, IDM, aria2.
- Both adapters on the **same router** share one internet line, so there is little or no gain. Real gains need two
  networks, for example home Wi-Fi plus a phone hotspot.
- Only apps that use the system proxy benefit: browsers and most apps do; Windows Update (WinHTTP), games and UDP/QUIC
  don't. Chrome turns QUIC off behind a proxy.
- Some sites log you out when your IP changes between connections.

## Decisions (Claude's calls)
1. **Rewrite it in Python with the standard library only** (asyncio, socket, ctypes, winreg). Don't bundle net-merge:
   it would add a Go binary, a driver, a second tray app and antivirus flags.
2. **Merge is a separate on/off setting (`"merge": true` in settings.json)**, not a third Wi-Fi choice. The Wi-Fi
   choice stays the main adapter (Windows' default route, and what the switch shows). With merge on, the other adapter's
   radio stays on and connects on its own. The user picks its network in the existing per-adapter Wi-Fi list.
3. **The system proxy is a PAC file served by the app**, set in HKCU `AutoConfigURL`. If the app dies, the PAC can't be
   fetched, so browsers go direct: crash-safe, like net-merge's "dies with the process". The old values are saved in
   settings.json and put back when merge is turned off, on quit, and on the next start after a crash.
4. **"Keep both connected" changes the Windows policy `fMinimizeConnections` = 0**
   (HKLM `SOFTWARE\Policies\Microsoft\Windows\WcmSvc\GroupPolicy`) when merge turns on. This stops Windows
   soft-disconnecting the second adapter. The old value (or its absence) is saved and restored when merge turns off.
   The app is already elevated.
5. **The WinHTTP proxy isn't touched**, and there is no per-site exception list (add one if logins break).
6. **Radio changes keep the one shared lock** (`hw._lock`). Turning merge on or off waits like a switch does.
7. **Same network on both:** the Merge card says "Both adapters are on <SSID>: little speed gain."

## Ethernet and USB tethering (added 2026-10-23)
The user asked: "also include ethernet and usb tethering in unigen and also give options to merge those". The pool, scheduler, probing
and failover never knew they were dealing with Wi-Fi, so a link is now **any usable internet link**, not only a Wi-Fi radio. These
are the coordinator's calls; the user reviews them with the rest.

**Which links exist** (`merge.scan_links()`, `merge.find_links()`):
- **Wi-Fi:** the dongle and the built-in radio, keys `unigen` and `builtin`, as before. Both are always listed (a radio that is off shows
  as not connected, so the user can include it again), and used when on and addressed.
- **Ethernet:** an adapter of IfType 6 that is up and has an IPv4 address (not link-local), and is not virtual. A USB network card is
  Ethernet.
- **USB tethering:** the same kind of adapter, told apart by its description: Remote NDIS / RNDIS (Android), NCM, Apple Mobile Device
  Ethernet, iPhone USB. It is listed only while it is up with an address.
- **Never listed:** Hyper-V `vEthernet`, VirtualBox, VMware, WSL, TAP/TUN/VPN (WireGuard, OpenVPN, Wintun), loopback, Bluetooth PAN,
  PPP/WAN miniports, debug adapters. Anything of another IfType is ignored too.
- **Reading them:** `GetAdaptersAddresses` through ctypes (read only), next to the existing iphlpapi calls. A struct-layout test pins the
  field offsets, as `MIB_IF_ROW2` has.
- **Keys:** `ethernet:<guid>` and `tether:<guid>`, so a choice survives a replug. Each link has a name ("Ethernet", "USB tethering
  (phone)"; with two of a kind the adapter's own name is added), a kind (`wifi`, `ethernet`, `tether`) and a detail (the description).

**Which links take part** (settings.json `merge_links: {key: bool}`):
- Defaults when there is no saved choice: Wi-Fi **in**, Ethernet **in**, USB tethering **out** (it uses the phone's mobile data).
- The proxy only dials out of links that are included, up, and have an address. With fewer than two such links merge still runs through
  the one it has and the Merge card says so (`single`); it never fails over that.
- The watchdog only manages Wi-Fi radios. Ethernet and tethering need no radio handling. A Wi-Fi radio that is left out is not forced on
  (merge on) and is turned off like with merge off; `set_merge` and the switch-adapter move (`_use`) follow the same rule. Taking a Wi-Fi
  radio in or out is a saved choice only: the watchdog's next pass (5 s) does the radio.

**Surfaces:**
- `Api.merge_status()` lists every link: kind, name, up/down, IPv4, live rate, included, state (`up`, `checking`, `down`, `off`).
  `Api.set_merge_link(key, on)` saves one choice (admin is not needed: it is a setting; the radio part is the watchdog's).
- The Merge card (Traffic page) has a row for every link with its kind icon and label, state, live rate and an include switch (the same
  switch as Bluetooth power). The tethering row says "uses your phone's mobile data".
- The Traffic page samples Ethernet and tethering too (`Sampler(extra=merge.wired_links)`): they are in Today, and a chart selector
  (Dongle | Built-in | Ethernet | USB phone) appears when there is more than the two Wi-Fi adapters.
- The widget has only the on/off switch and a "Merged" badge. The per-link choices live in the app.

**Limits the user should know:**
- Tethering shares the phone's mobile data plan: merging it can use a lot of data, which is why it starts out of merge.
- Ethernet plus Wi-Fi on the same router share one internet line: little gain, like two Wi-Fi adapters on one network. The "same network"
  note only compares the two Wi-Fi adapters; it does not know that an Ethernet cable goes to the same router.
- Detection of a tethered phone goes by the adapter's description. A phone whose driver names its adapter differently shows up as plain
  Ethernet (still mergeable, just not marked as tethering and not defaulted out).

## Must not break
- With merge **off**, everything behaves exactly as today: the watchdog still turns the second radio off.
- Unplugging the dongle with merge on falls back to the built-in adapter, and the proxy keeps working on one link.
- Quitting or crashing never leaves the PC without internet.
- A link going away (a cable pulled, a phone unplugged) never breaks a connection that is open on another link, and new connections use
  whatever links are left.
