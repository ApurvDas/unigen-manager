# Merge connections: use both Wi-Fi adapters at once

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

## Must not break
- With merge **off**, everything behaves exactly as today: the watchdog still turns the second radio off.
- Unplugging the dongle with merge on falls back to the built-in adapter, and the proxy keeps working on one link.
- Quitting or crashing never leaves the PC without internet.
