# Unigen Manager: manual test checklist

Date: 2026-10-13 · Build: e295789

## Automated results
- `py -3.10 -m pytest`: 120 passed, 10 deselected (98 unit/contract incl. 5 added by review fixes, 22 UI in Microsoft Edge)
- `py -3.10 -m pytest -m hardware`: 10 passed, 120 deselected

## State-changing checks (on the real PC)

| # | Steps | Expected | Result |
|---|---|---|---|
| 1 | `py -3.10 app.py --install-shortcut`, then double-click "Unigen Manager" on the desktop and choose **Yes** | The window opens. Side menu: Unigen dongle (Wi-Fi 6, Bluetooth 5.4), Built-in MediaTek (Wi-Fi 6, Bluetooth 5.2). Tabs: Wi-Fi 6, Bluetooth 5.4, Speed | |
| 2 | Close the app, start it again and choose **No** at the prompt | The app still opens. On Bluetooth, the radio button is disabled and the admin note shows | |
| 3 | Wi-Fi with Unigen selected: select the connected network, then **Disconnect** | The status column clears, the side menu shows "Not connected" and the dot turns grey within 2 s | |
| 4 | Select HOME-5G (Saved), then **Connect** | "Connected to HOME-5G." within 15 s. The channel map fills in | |
| 5 | Turn on a phone hotspot with a known password. Select it, then **Connect** and enter a wrong 8+ character password | After at most 15 s: "Couldn't connect to <hotspot>. Check the password." `netsh wlan show profiles` does **not** list the hotspot | |
| 6 | Connect to the hotspot again with the right password | Connected. The hotspot now shows as Saved | |
| 7 | Wi-Fi › Saved: **Show** on HOME-5G | The password matches the one Windows shows in Settings. **Hide** puts the dots back | |
| 8 | Saved: **Copy to built-in** on Maple House | The row changes to "Both adapters". `netsh wlan show profiles` lists it under interface "Wi-Fi" | |
| 9 | Saved: hold **Hold to delete** on the hotspot for 1.5 s | The row slides away and the count drops. netsh no longer lists it on either adapter | |
| 10 | Speed: **Run test** on each adapter | The curve draws live, download then upload. Numbers are close to the 12 Oct manual test (Unigen about 50/12, Built-in about 53/31 Mbps). Results survive closing and reopening the app | |
| 11 | Bluetooth (as admin): **Use built-in radio** | The label changes to Bluetooth 5.2. Device Manager shows the MediaTek radio enabled and the Unigen radio disabled. If the MediaTek radio doesn't start within 10 s: "…didn't start. Switched back to the Unigen dongle." and Unigen works again | |
| 12 | **Use Unigen radio** | Back to Bluetooth 5.4. Paired devices reconnect | |
| 13 | Put a phone in pairing mode, then **Search**, then **Pair** | The phone appears under Nearby. After pairing it moves to Paired and the count goes up. Windows Settings lists it | |
| 14 | Hold **Hold to remove** on that phone | It disappears from Paired and from Windows Bluetooth settings | |
| 15 | Turn on the JBL Go 3 (or the spike device), then **Connect**, then **Disconnect** | If the spike said WORKS: the speaker connects, then disconnects; after the app's Disconnect, connect from Windows Settings and confirm audio plays. If FAILS: Windows Bluetooth settings open, with the explanation message | |
| 16 | Unplug the Unigen dongle while the app is open, then plug it back in | No crash. The side menu shows "Unplugged". Selecting it shows "The Unigen dongle isn't plugged in." After replugging it returns within a few seconds | |
| 17 | Windows Settings › Ease of Access › Display › turn off "Show animations", then restart the app | Motion becomes simple fades. Nothing slides or scales | |
| 18 | Click **^** on the taskbar, then the cyan Unigen icon | The widget rises in just above the taskbar at the bottom right. Clicking elsewhere closes it. Clicking the icon again doesn't make it flicker | |
| 19 | Widget: **Wi-Fi uses › Built-in** (then back to Unigen) | The chosen adapter joins the network and the other disconnects. The main window's side menu agrees | |
| 20 | Widget: Disconnect / Connect a saved network, **Use built-in** Bluetooth, **Run test** | Each one works as in the main window. The sparkline draws live. Confirmations fade after 4 s | |
| 21 | Tray right-click › **Start with Windows**, then sign out and back in; also unplug the charger, then sign out and back in: the tray still starts; leave it running on battery | The tray icon appears at sign-in with **no** admin prompt, also on battery, and is still running later. `schtasks /Query /TN "Unigen Manager"` lists the task | |
| 22 | Close the main window, then double-click the desktop shortcut | The main window comes back (one copy only; there may be one admin prompt). Tray › **Quit** removes the icon and ends the process | |
| 23 | Check `%LOCALAPPDATA%\UnigenManager\app.log` after all of the above | No passwords anywhere in the file | |

| 24 | Bluetooth spike (deferred plan Task 1): turn on a paired speaker, run the spike script from an elevated prompt; after the app's Disconnect, connect from Windows Settings and confirm audio plays | Records whether `bt.SERVICE_TOGGLE` stays True (Connect/Disconnect work directly) or becomes False (always opens Settings) | |

## Sign-off
- Failures and follow-ups:
- Tested by:
