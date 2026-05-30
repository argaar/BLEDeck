# Contributing to BLEDeck

Thanks for considering a contribution. BLEDeck is a BLE macro pad with three independent components in one repo — firmware, Windows app, and a software simulator. See the root [`README.md`](README.md) for the project overview.

This guide tells you how to get a working dev environment, where things live, and what we expect in pull requests.

---

## Quick start

Prerequisites:

- **Python 3.12 or later** — for `windows_app/` and `simulator/`.
- **PlatformIO** (CLI or VS Code extension) — for `firmware/`. Only needed if you touch C++.
- **Windows 10 / 11** — the desktop app is Windows-only (Win32 APIs, WinRT BLE).

Clone and set up the Windows app:

```bash
git clone https://github.com/argaar/BLEDeck.git
cd BLEDeck/windows_app
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Or, from inside an activated venv, run `windows_app\setup-dev.bat` to install runtime + dev dependencies and verify the test suite passes in one go.

For the simulator, you can reuse the `windows_app` venv (bleak is already there). See [`simulator/README.md`](simulator/README.md).

For firmware: copy `firmware/src/credentials.h.example` to `firmware/src/credentials.h`, fill in your WiFi + OTA password, then `pio run --target upload`.

---

## Repo layout

| Folder | What it is | README |
|--------|-----------|--------|
| `firmware/` | ESP32 firmware (C++17, Arduino, PlatformIO) | [firmware/README.md](firmware/README.md) |
| `windows_app/` | PyQt5 desktop app (Python 3.12, bleak) | [windows_app/README.md](windows_app/README.md) |
| `simulator/` | Software emulator of the device (Python 3.12, WinRT) | [simulator/README.md](simulator/README.md) |
| `docs/` | BLE protocol reference + debugging notes | — |
| `debug/` | Stand-alone protocol decoder script | — |
| `pcb/` | KiCad project | [pcb/README.md](pcb/README.md) |

Each component is independent — you can work on one without touching the others.

---

## Branching & PR flow

1. Branch off `main`. Name the branch after what you are doing (`feature/macro-import`, `fix/battery-calibration`, etc.).
2. Keep the PR focused on a single concern. Split unrelated changes into separate PRs.
3. Link the related issue in the PR description (`Closes #42`).
4. The PR template (in `.github/PULL_REQUEST_TEMPLATE.md`) covers tests, docs, and component checkboxes — fill it in.

---

## Commit messages

Format: `[component] description`

- **Components:** `windows_app`, `firmware`, `simulator`, `pcb`, `enclosure`, `common`, `misc`, `docs`.
- Multi-component in one commit: `[comp1] desc1 [comp2] desc2`.
- Imperative verbs: `add`, `fix`, `update`, `remove`, `refactor`, `enable`.
- No trailing period. Keep each component block under ~72 characters.

Examples:

```
[windows_app] add macro import dialog
[firmware] fix battery calibration on USB-only boot
[pcb] version 1.1 [firmware] enable 16 rgb keys
[simulator] add loopback mode
```

---

## Tests

Both Python test suites must stay green:

```bash
pytest windows_app/tests/
pytest simulator/tests/
```

When you change behaviour, add or update tests. New modules without tests should be the exception, not the rule.

Firmware does not have an automated test suite — verify changes with `pio run` (clean build) and a manual smoke test on real hardware. If you do not have hardware, mention that in the PR so a maintainer can run the device-side check.

---

## Documentation

If your change is user-visible or alters how the code is wired together, update docs in the same PR:

- Component README (`firmware/`, `windows_app/`, or `simulator/`) for any feature, dependency, or behaviour change.
- Root `README.md` if the change is user-visible.
- `CHANGELOG.md` — add an entry under the matching component section.

### Protocol changes (adding or changing an opcode)

The BLE protocol is defined in several files that must stay in sync. When you add or change an opcode, update **all** of these in the same PR — never add an opcode on only one side:

| File | What to change |
|------|----------------|
| `firmware/src/protocolparser.h` | Add to `enum Opcode`; update the protocol comment block |
| `firmware/src/main.cpp` | Add a `handlePacket()` case (commands) and/or a `sendXxx()` helper (events) |
| `windows_app/ble_protocol.py` | Add the opcode constant + builder/parser function |
| `windows_app/main.py` | Handle it in `handle_notification()`; update the `_OP_NAMES` dict |
| `docs/ble_protocol_reference.md` | Opcode table + payload-format section |
| `docs/protocol_debugging.md` | Common-packets section |
| `docs/hex_quick_reference.md` | Quick opcode reference + example |
| `debug/protocol_decoder.py` | Opcode constant, `OPCODE_NAMES`, decoder case, test example |

Profile indices are **1-based in commands**, **0-based in events** — keep that convention.

---

## Code style

- **Minimal diffs.** Do not reformat, reorder, or rename surrounding code.
- **Python:** type hints on all function signatures; `pathlib` over `os.path`; explicit `utf-8` encoding on file I/O.
- **No new runtime dependencies without discussion.** Open an issue first if you need to add one.

---

## Filing issues

When reporting a bug, please include:

- Operating system (Windows 10 / 11) and Python version.
- Firmware version (`firmware/src/version.h` or About dialog on the device).
- Windows app version (Help → Info).
- Exact steps to reproduce, plus any relevant log output (enable Help → Enable Debug to capture protocol traffic).

Open issues on the [GitHub issue tracker](https://github.com/argaar/BLEDeck/issues).
