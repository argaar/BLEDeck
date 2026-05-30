# BLEDeck — Troubleshooting

Common failures and how to diagnose them. Check the rows top-to-bottom; the
"First check" column usually resolves the issue.

## Connection

| Symptom | First check | Then check | Last resort |
|---------|-------------|------------|-------------|
| App stays *Disconnected* forever | Bluetooth adapter enabled in Windows Settings? | Device powered, OLED on? | Remove the device from Windows Bluetooth pairing list, then reconnect from the app |
| App connects then drops within seconds | BLE adapter supports BLE 4.0+? | Other Bluetooth peripherals interfering? | Move device closer (<3 m); check `bledeck.log` under `%APPDATA%\BLEDeck\logs\` |
| Multiple BLEDecks in range, wrong one connects | App settings now pin the first MAC address used. Delete `%APPDATA%\BLEDeck\app_settings.json` to reset, then reconnect to the desired device first | — | — |
| `[SIMULATOR]` shown in window title | `BLEDECK_SIM=1` environment variable is set | Unset it (`set BLEDECK_SIM=` on cmd, `Remove-Item Env:BLEDECK_SIM` on PowerShell) and restart the app | Reboot if env var persists |

> The app now prints these checks under the *Debug Log* (Help → Enable Debug)
> as a `❌ Device not found` block — flip the panel on if you're triaging
> a no-connect report.

## Battery

| Symptom | First check | Then check | Last resort |
|---------|-------------|------------|-------------|
| Battery shows 100 % when pack is half drained | Plug USB, watch the `[BAT] adc=... vbat=... pct=...` serial line | Compare `vbat` against a multimeter on the battery terminals | Reflash with `pio run -e calibrate -t upload` and follow the printed retune formula |
| Battery shows `USB` when battery is connected | ADC reads `0 mV` → check divider wiring | Confirm `BAT_PIN` (GPIO 13) is connected to the divider mid-tap | Try a different ADC1 pin in `configuration.h` (ADC2 has known quirks on ESP32) |

## OTA

| Symptom | First check | Then check | Last resort |
|---------|-------------|------------|-------------|
| OTA web page says *Auth failed* | `OTA_HTTP_PASSWORD` in `credentials.h` matches what the browser sent | Browser cached a stale password — open a private window | Reflash via USB (`pio run -t upload`) and reset the password |
| OTA endpoint stops accepting uploads | Five wrong-password attempts within 60 s trigger a 5-minute lockout — wait it out | Watch serial for `[OTA] Auth lockout` | Power-cycle the device |
| Device can't join WiFi | `OTA_WIFI_SSID` / `OTA_WIFI_PASSWORD` in `credentials.h` match the AP | 2.4 GHz network? The ESP32 does not do 5 GHz | Use the AP fallback (`BLEDeck-OTA`) — random password is on the OLED |
| Build error: undefined `OTA_HTTP_PASSWORD` | Open `credentials.h` and rename the old `OTA_PASSWORD` macro to `OTA_HTTP_PASSWORD` | See `firmware/src/credentials.h.example` | Copy the example file fresh: `cp src/credentials.h.example src/credentials.h` |

## Profiles & macros

| Symptom | First check | Then check | Last resort |
|---------|-------------|------------|-------------|
| Profile file disappeared | Check `%APPDATA%\BLEDeck\profiles.json.corrupt.json` — the app renames bad files instead of overwriting | History snapshots under `%APPDATA%\BLEDeck\history\` (most recent first) | Use File → New, recreate; see `bledeck.log` for the failure reason |
| Macro fires into the wrong window | The recorder picked the wrong anchor. Open the macro editor and inspect each `ClickStep`'s `relative_to` — `window:<title>` vs `monitor:<n>` vs `abs` | Re-record while the target window is the foreground app | Set the anchor manually to `monitor:<n>` for desktop/taskbar clicks |
| Profile name truncated on the device OLED | App UI is now capped at 39 chars; older files may exceed. Edit the name in Edit mode and save | — | Hand-edit `profiles.json` and trim to 39 UTF-8 bytes |
| App pops "untrusted commands" warning on load | The profile file contains commands flagged as risky (`powershell`, `cmd /c`, `curl ... | iex`, etc.). Inspect and either remove or confirm trust per profile file | — | Edit the JSON to remove the risky command |

## Logs

Rotating log lives at `%APPDATA%\BLEDeck\logs\bledeck.log` (5 × 20 MB rotation, 100 MB cap). `KEEP_ALIVE` traffic is filtered out to keep it readable. Open it in any editor for chronological app activity.

## Asking for help

Open an issue at the project's GitHub. Include:
1. App version (Help → Info), firmware version (visible on device OLED for ~2 s at boot, or in `[BAT]` serial line context).
2. The most recent ~200 lines of `bledeck.log`.
3. Output of `pio device monitor` for the same timeframe if firmware is involved.
4. Steps to reproduce.
