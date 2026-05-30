# BLEDeck — User Manual

BLEDeck is a 16-key Bluetooth Low Energy macro pad. This Windows app is the
control panel: it pushes profiles, RGB colors, and key actions to the device,
and reacts to physical key presses by running shell commands or recorded
macros on your PC.

The device itself stores nothing permanently — every time you connect, the app
re-sends the active profile.

---

## 1. Getting started

1. Power on the BLEDeck device.
2. Launch the app. It opens in **Pad** mode with the default profile loaded
   from `%APPDATA%\BLEDeck\profiles.json`.
3. Click **Connect**. The status bar shows *Connecting...* while the app scans
   for a device advertising as `BLEDeck`. Once paired, it shows
   *Connected to <address>*.
4. Tick **Auto-reconnect** to have the app automatically re-establish the
   connection if the link drops.

The battery indicator next to the status appears once connected:
`Bat: 42%` for a battery-powered device, `USB` when it is on cable power.

---

## 2. Modes

Switch via the **Mode** menu.

### Pad mode (default)

Clean, compact interface for daily use. The 4×4 key grid fills the window;
the profile dropdown lets you switch profiles; nothing else is editable.
This is the mode to leave the app in once you have configured it.

### Edit mode

Full editing surface. On top of the Pad widgets, you also get:

- Profile name field and **New Profile / Save Profile / Delete Profile**
  buttons.
- Key configuration panel: label, color picker, brightness slider, action
  type (Command or Macro), command field with file browser, macro editor
  launcher.

The window grows to ~900×700 to fit the extra controls. Switch back to Pad
when you're done editing.

---

## 3. The File menu

Profiles live in JSON files. The default file is at
`%APPDATA%\BLEDeck\profiles.json` and loads automatically each launch. You
can open a different file for the current session — useful for testing setups
or sharing configurations.

| Action | Shortcut | Behavior |
|--------|----------|----------|
| **New** | `Ctrl+N` | Discards the current file (after a save prompt if dirty) and starts a blank profile. The window title shows `[Unsaved]` until saved. |
| **Open...** | `Ctrl+O` | Opens any `*.json` profile file. The path is shown in the window title for the rest of the session. |
| **Save** | `Ctrl+S` | Writes back to the current file. If the current file is new (never saved), you are prompted: *Save as Default* (overwrites the APPDATA file) or *Save As...* (pick a custom location). When saving as Default with an existing file, a confirmation warns about the overwrite. |
| **Exit** | `Ctrl+Q` | Closes the app. Same dirty-changes prompt as the title bar X. |

An asterisk (`*`) in the title means there are unsaved changes.

> The **Save Profile** button in Edit mode runs the exact same logic as
> File → Save.

---

## 4. Profiles

A profile file holds an ordered list of profiles. Each profile has a name and
up to 16 keys. The device supports up to **10 profiles** (protocol limit).

- The **Profile** dropdown switches the active profile. The device follows.
- The device's rotary encoder also switches profiles; the app follows.
- **New Profile** appends an empty profile to the current file.
- Edit the name in the text field; the change is saved with the file.
- **Delete Profile** removes the current profile (at least one must remain).

---

## 5. Configuring a key (Edit mode)

1. Click any key in the 4×4 grid. The label `Selected Key: <name> (ID: <n>)`
   updates.
2. **Label** — short text shown on the key in the app. The device itself
   doesn't show labels — only the RGB color.
3. **Color** — enter `R,G,B,Brightness%` directly (e.g. `255,0,0,70`) or click
   **Pick Color** for a color dialog. The brightness slider rescales the
   brightness component (0–100%). The LED on the device updates instantly.
4. **Action** — choose **Command** or **Macro**.

### Command action

A shell command or executable path. Examples:

- `notepad.exe`
- `calc.exe`
- `"C:\Program Files\My App\tool.exe"`
- `cmd /c echo Hello`

Use **Browse...** to pick an `.exe`. Quote any path containing spaces.

When the device sends `KEY_PRESSED` for this key, the app launches the
command (non-blocking; the app does not wait for it to exit).

### Macro action

Records a sequence of mouse clicks, key presses, and pauses to replay on
demand. Click **Edit Macro...** to open the macro editor.

A re-entrancy guard prevents the same key from launching two parallel macros:
if you press the device key while a previous run is still in progress, the
new press is skipped (visible as `⚠️ Key X still running, skipping` in the
debug log).

---

## 6. The macro editor

Opened from a Macro-type key's **Edit Macro...** button.

> ⚠️ **Capture risk.** Recording uses a global keystroke / mouse listener — it
> sees **everything you type while it's running**, including passwords typed
> into other windows. Two safeguards are built in:
>
> - The recorder **auto-stops after 60 seconds of idle time** so a forgotten
>   session cannot silently capture later activity.
> - The captured macro is stored in `profiles.json` in plain text. Keep that
>   file out of public sync folders or Git repositories.
>
> Treat the editor like a temporary screen recorder, not a keylogger you walk
> away from. Hit **Stop** (or press `Esc`) the moment you've captured the
> sequence you wanted.

| Button | What it does |
|--------|--------------|
| **Record** | Captures every mouse click and key press as a step. Press `Esc` to stop. |
| **Stop** | Stops an in-progress recording. |
| **Test Run** | Plays the current macro back immediately. |
| **Edit Step** | Modify the selected step (double-click works too). |
| **Delete Step** | Remove the selected step. |
| **Clear** | Remove all steps. |

Steps can be drag-reordered in the list.

### Step types

- **Click** — `x, y, button, anchor`
- **Key** — single key plus optional modifiers (`ctrl`, `shift`, `alt`, `win`)
- **Sleep** — pause for *N* milliseconds

### Click anchors

Mouse clicks are recorded relative to a reference, so playback still works
when windows have moved. Three anchor kinds:

| Anchor | Meaning |
|--------|---------|
| `window:<title>` | Coordinates relative to the top-left of the named window. The window is found again at playback time. Use `window:` (empty title) to mean *the current foreground window*. |
| `monitor:<N>` | Relative to the top-left of monitor *N* (0 = leftmost). Use this for clicks on the taskbar or empty desktop. |
| `abs` | Absolute screen coordinates. |

The recorder picks an anchor automatically based on where you click:
foreground app windows produce `window:` anchors; taskbar/desktop clicks
produce `monitor:` anchors.

---

## 7. Device-side feedback

Some things happen at the device that the app reacts to:

- **Profile change via the encoder** — the app switches profiles to match and
  re-sends RGB colors.
- **Button press** (encoder push / back / con) — logged in the debug panel.
- **Key press** — the configured Command or Macro for that key runs.
- **Battery status** — sent ~every 30 seconds; updates the battery readout.

---

## 8. Screen lock awareness

When Windows is locked (Win+L, or your screensaver triggers the lock), the
app notifies the device. The device shows a lock icon on the OLED and ignores
key presses until unlocked. This avoids macros firing while you are away.

---

## 9. Tray and minimize

Closing or minimizing the window hides it to the system tray instead of
quitting.

- Double-click (or single-click on most Windows setups) the tray icon to
  restore.
- Right-click the tray icon for **Open** / **Quit**.

Profile changes triggered from the device (via the rotary encoder) are
recorded in the debug log; the app updates state silently while hidden.

---

## 10. Help menu

| Item | What it does |
|------|--------------|
| **Manual** | Opens this document. |
| **Enable Debug** | Shows the *Debug Log* panel for the current session. It logs every BLE packet sent and received, plus high-level state changes. Turned off by default; not persisted across launches. |
| **Info** | Shows the app version, authors, and a link to the project on GitHub. |

---

## 11. Where things live

| Item | Location |
|------|----------|
| Default profile file | `%APPDATA%\BLEDeck\profiles.json` |
| Custom profile files | Anywhere you save them; tracked per session via File → Open |
| App icon | `icon.ico` in the install directory |
| This manual | `manual.md` in the install directory |

The `%APPDATA%\BLEDeck` folder is created automatically on first run. If it
cannot be created (locked-down profile, missing `%APPDATA%`, etc.), the app
falls back to `~/.bledeck` and then to the system temp directory so the app
always starts.

---

## 12. Connection health

- The app pings the device every 10 seconds.
- If the device misses pings for 30 seconds (e.g. the app crashes), it drops
  the connection on its own.
- If the device drops, **Auto-reconnect** retries every 10 seconds.

These intervals are tuned to detect a dead app in under a minute while
tolerating brief radio glitches.

---

## 13. Limitations

- **Windows only.** PyQt5 + bleak + Win32 helpers; no macOS or Linux support.
- **10 profiles max, 16 keys per profile** — protocol limit.
- **Single device.** The app pairs with the first device advertising as
  `BLEDeck`.
- **Macro recorder captures press events only.** Mouse movement paths and
  release timings are not recorded; sleeps between actions are inferred from
  natural pauses.
