import ctypes
import sys
import asyncio
import html
import logging
import logging.handlers
import os
import queue
import re
import time
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
import qasync
from bleak import BleakGATTCharacteristic
from ble_client import BleakClient, BleakScanner
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QLabel, QPushButton, QLineEdit, QComboBox,
                             QGridLayout, QGroupBox, QStatusBar, QTextEdit,
                             QFileDialog, QMessageBox, QCheckBox, QColorDialog,
                             QDialog, QSlider, QSystemTrayIcon, QMenu, QAction,
                             QActionGroup, QTextBrowser, QDialogButtonBox)
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QIcon, QDesktopServices

from __version__ import APP_NAME, APP_VERSION, APP_AUTHORS, APP_GITHUB_URL
from app_settings import load_settings, save_settings
from ble_client import DEVICE_NAME, SERVICE_UUID, CHAR_TX_UUID, CHAR_RX_UUID
from command_safety import collect_risky_commands
from key_button import KeyButton
from profile_manager import (
    CONFIG_PATH, create_new_profile, load_profiles, load_profiles_from,
    save_profiles, save_profiles_to,
)
import ble_protocol
from action_runner import ActionRunner
from macro_models import macro_from_list, macro_to_list
from win32_utils import (
    is_workstation_locked,
    register_session_notifications,
    unregister_session_notifications,
    WtsMsg,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    WTS_SESSION_UNLOCK,
)

logger = logging.getLogger(__name__)


# Reconnect backoff window: starts at 10 s, doubles per failure, caps at 5 min.
_RECONNECT_BACKOFF_MIN_MS = 10_000
_RECONNECT_BACKOFF_MAX_MS = 5 * 60_000

# Opcode → short label for the raw-packet log line. Module constant so it is
# not reallocated on every incoming notification.
_OP_NAMES = {0x81: "PONG", 0x82: "PROFILE", 0x83: "BUTTON",
             0x84: "KEY", 0x85: "BATTERY", 0x86: "TELEMETRY"}

class _KeepAliveLogFilter(logging.Filter):
    """Drop keep-alive / ping log records from the rotating file handler.

    The UI debug panel still shows them in real time; persisting every ping
    bloats the rotating file with no diagnostic value. Patterns cover both
    the prose log entries (🏓 / "Ping" / "KEEP_ALIVE") and the raw hex-dump
    tags emitted by send_ble / handle_notification ([PING], [PONG]).
    """
    _PATTERNS = (
        "🏓", "Pong received", "Ping sent", "KEEP_ALIVE",
        "[PING]", "[PONG]",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in self._PATTERNS)


_BLEDECK_LOG_LISTENER: "QueueListener | None" = None  # populated in _configure_file_logging


def _configure_file_logging() -> None:
    """Install a rotating file handler under ``%APPDATA%\\BLEDeck\\logs``.

    5 × 20 MB = 100 MB hard cap. KEEP_ALIVE traffic is filtered. Idempotent —
    re-runs are no-ops because we tag the handler with a stable attribute.
    Writes are drained on a background thread via QueueHandler/QueueListener
    so the GUI thread never blocks on disk I/O.
    """
    root = logging.getLogger()
    for h in root.handlers:
        if getattr(h, "_bledeck_file_handler", False):
            return
    log_dir = CONFIG_PATH.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # Fall back silently — caller still has a console logger and the file
        # backup is a nice-to-have, not load-bearing.
        logger.warning("Could not create log dir %s: %s", log_dir, e)
        return
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "bledeck.log",
        maxBytes=20_000_000,   # 20 MB per file
        backupCount=4,          # current + 4 rotated = 5 files × 20 MB = 100 MB
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    handler.addFilter(_KeepAliveLogFilter())

    # Drain writes on a background thread so the GUI thread never blocks on
    # disk I/O. Listener stops in `closeEvent`.
    _log_queue: queue.Queue = queue.Queue(-1)
    listener = QueueListener(_log_queue, handler, respect_handler_level=True)
    listener.start()
    queue_handler = QueueHandler(_log_queue)
    queue_handler._bledeck_file_handler = True  # type: ignore[attr-defined]
    root.addHandler(queue_handler)

    # Stash the listener at module scope so closeEvent can stop it cleanly.
    global _BLEDECK_LOG_LISTENER
    _BLEDECK_LOG_LISTENER = listener

    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


def _resource_path(name: str) -> Path:
    """Resolve resource for both source and PyInstaller frozen build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


_ICON_PATH = str(_resource_path("icon.ico"))

# When BLEDECK_SIM=1 the app talks to the in-process FakeBleakClient instead of
# a real radio. Surface it in the UI so a stale env var cannot silently impersonate
# a real BLEDeck device for an entire session.
_SIMULATOR_MODE = os.environ.get("BLEDECK_SIM") == "1"
_TITLE_PREFIX = "[SIMULATOR] " if _SIMULATOR_MODE else ""


class BLEDeckGUI(QMainWindow):
    def __init__(self, quit_event: asyncio.Event) -> None:
        super().__init__()
        self.setWindowTitle("BLEDeck Control Panel")
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon(_ICON_PATH))

        # Create tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(_ICON_PATH))
        self.tray_icon.setToolTip("BLEDeck Control Panel")

        self.already_minimized = False

        # Create context menu for tray
        tray_menu = QMenu()

        restore_action = QAction("Open", self)
        restore_action.triggered.connect(self.showNormal)
        tray_menu.addAction(restore_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        # Connect double-click on tray icon to restore
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        # Store quit event for proper shutdown
        self.quit_event = quit_event

        # BLE connection state
        self.ble_client = None
        self.is_connected = False
        self._connecting = False
        self.current_profile_index = 0
        self._encryption_pending = False
        # opcode → asyncio.Future. handle_notification resolves each waiter as soon
        # as the matching opcode arrives. Lets connect() bootstrap drive each step
        # off a real ACK instead of a fixed 500 ms sleep.
        self._opcode_waiters: dict[int, asyncio.Future] = {}
        # Exponential backoff for auto-reconnect attempts (ms). Reset to the
        # floor after every successful connect; doubles on each failure up to
        # _RECONNECT_BACKOFF_MAX_MS.
        self._reconnect_backoff_ms = _RECONNECT_BACKOFF_MIN_MS

        # Persistent settings (preferred device MAC, etc.)
        self.app_settings = load_settings()

        # Data
        self.profiles = load_profiles()
        self.profile_file_path: Path | None = CONFIG_PATH
        self.is_dirty = False
        self.mode = "pad"        # "pad" | "edit"
        self.debug_enabled = False
        self.key_buttons = {}
        self.key_configs = {}

        # Setup UI
        self.setup_ui()
        self.load_current_profile()
        self._apply_mode()
        self._apply_debug()
        self._update_title()

        # Setup timer for periodic ping
        self.ping_timer = QTimer()
        self.ping_timer.timeout.connect(self.send_ping)

        # Workstation-lock detection: event-driven via WTSRegisterSessionNotification
        # when available, falling back to the legacy 2.5 s poll. The fallback
        # remains useful on virtualised desktops where the WTS notification
        # never fires reliably.
        self.was_locked = False
        self._session_notifications_registered = False
        try:
            self._session_notifications_registered = register_session_notifications(
                int(self.winId())
            )
        except Exception:
            logger.debug("session notification subscribe failed", exc_info=True)
        self.device_lock_timer = QTimer()
        self.device_lock_timer.timeout.connect(self.screen_locked)
        if not self._session_notifications_registered:
            self.device_lock_timer.start(2500)

        # Auto-connect timer - start disabled, can be enabled via UI
        self.connect_timer = QTimer()
        self.connect_timer.timeout.connect(self.auto_connect)
        # Don't start auto-connect by default to prevent connection loops

        # Last ping time for connection health
        self.last_ping_response = time.time()

        # Coalesce rapid colour edits (slider drag, picker dialog) into ~20 Hz BLE
        # writes. Per-tick sends saturate the link and back up the firmware strip
        # refresh; 50 ms is below human perception of latency on a slider.
        self._color_send_timer = QTimer(self)
        self._color_send_timer.setSingleShot(True)
        self._color_send_timer.setInterval(50)
        self._color_send_timer.timeout.connect(self._flush_pending_color)
        self._pending_color_packet: bytes | None = None

        asyncio.create_task(self.connect())
        if os.environ.get("BLEDECK_SIM") == "1":
            asyncio.create_task(self._run_sim_cli())

        self._action_runner = ActionRunner()

        # Surface a one-shot warning if the loaded profile file contains
        # commands flagged as high-risk (powershell, curl|iex, etc.). Defer
        # to next event-loop tick so the main window paints first.
        QTimer.singleShot(0, lambda: self._warn_about_risky_commands(self.profiles))

    def _collect_risky_commands(self, profiles: list[dict]) -> list[tuple[str, str, str]]:
        """Return list of (profile_name, key_id, command) for any key whose
        command contains a high-risk token. Delegates to
        :func:`command_safety.collect_risky_commands`."""
        return collect_risky_commands(profiles)

    def _warn_about_risky_commands(self, profiles: list[dict]) -> None:
        flagged = self._collect_risky_commands(profiles)
        if not flagged:
            return
        lines = [f"{p} / key {k}: {c}" for p, k, c in flagged[:15]]
        if len(flagged) > 15:
            lines.append(f"... and {len(flagged) - 15} more")
        body = (
            "Profile file contains commands flagged as high-risk:\n\n"
            + "\n".join(lines)
            + "\n\nReview each one before pressing the matching device key. "
              "Untrusted commands run with the same privileges as the app."
        )
        logger.warning("Risky commands flagged in profile file: %d entr%s",
                       len(flagged), "y" if len(flagged) == 1 else "ies")
        QMessageBox.warning(self, "Untrusted commands detected", body)

    def setup_ui(self) -> None:
        self._build_menu_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Top panel - Connection and Profile
        self.top_panel = self.create_top_panel()
        layout.addWidget(self.top_panel)

        # Middle panel - Key Grid
        self.key_panel = self.create_key_panel()
        layout.addWidget(self.key_panel)

        # Bottom panel - Action Configuration (Edit mode only)
        self.action_panel = self.create_action_panel()
        layout.addWidget(self.action_panel)

        # Debug log panel - shown only when Help → Enable Debug is active
        self.log_panel = self._create_log_panel()
        layout.addWidget(self.log_panel)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Disconnected")

    def _build_menu_bar(self) -> None:
        menubar = self.menuBar()

        # --- File menu ---
        file_menu = menubar.addMenu("&File")

        self.action_new = QAction("&New", self)
        self.action_new.setShortcut("Ctrl+N")
        self.action_new.triggered.connect(self.file_new)
        file_menu.addAction(self.action_new)

        self.action_open = QAction("&Open...", self)
        self.action_open.setShortcut("Ctrl+O")
        self.action_open.triggered.connect(self.file_open)
        file_menu.addAction(self.action_open)

        self.action_save = QAction("&Save", self)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.triggered.connect(self.file_save)
        file_menu.addAction(self.action_save)

        file_menu.addSeparator()

        self.action_exit = QAction("E&xit", self)
        self.action_exit.setShortcut("Ctrl+Q")
        self.action_exit.triggered.connect(self.close)
        file_menu.addAction(self.action_exit)

        # --- Mode menu ---
        mode_menu = menubar.addMenu("&Mode")
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self.action_mode_pad = QAction("&Pad", self, checkable=True)
        self.action_mode_pad.setChecked(True)
        self.action_mode_pad.triggered.connect(lambda: self.set_mode("pad"))
        mode_group.addAction(self.action_mode_pad)
        mode_menu.addAction(self.action_mode_pad)

        self.action_mode_edit = QAction("&Edit", self, checkable=True)
        self.action_mode_edit.triggered.connect(lambda: self.set_mode("edit"))
        mode_group.addAction(self.action_mode_edit)
        mode_menu.addAction(self.action_mode_edit)

        # --- Help menu ---
        help_menu = menubar.addMenu("&Help")

        self.action_manual = QAction("&Manual", self)
        self.action_manual.triggered.connect(self.show_manual)
        help_menu.addAction(self.action_manual)

        self.action_enable_debug = QAction("Enable &Debug", self, checkable=True)
        self.action_enable_debug.toggled.connect(self.set_debug)
        help_menu.addAction(self.action_enable_debug)

        self.action_forget_device = QAction("&Forget paired device", self)
        self.action_forget_device.triggered.connect(self._forget_paired_device)
        help_menu.addAction(self.action_forget_device)

        self.action_info = QAction("&Info", self)
        self.action_info.triggered.connect(self.show_info)
        help_menu.addAction(self.action_info)

    def _create_log_panel(self) -> QGroupBox:
        group = QGroupBox("Debug Log")
        v = QVBoxLayout(group)
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(120)
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Debug log will appear here...")
        v.addWidget(self.log_text)
        return group
    
    def create_top_panel(self) -> QGroupBox:
        group = QGroupBox("Connection & Profile")
        layout = QHBoxLayout(group)

        # Connection status
        self.status_label = QLabel("Status: Disconnected")
        layout.addWidget(self.status_label)

        # Battery level (populated once device sends OP_BATTERY_STATUS)
        self.battery_label = QLabel("")
        self.battery_label.setStyleSheet("color: gray;")
        layout.addWidget(self.battery_label)

        # Connect button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn)

        # Auto-reconnect checkbox
        self.auto_reconnect_cb = QCheckBox("Auto-reconnect")
        self.auto_reconnect_cb.toggled.connect(self.toggle_auto_reconnect)
        layout.addWidget(self.auto_reconnect_cb)

        # Profile selection
        layout.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.update_profile_combo()
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        layout.addWidget(self.profile_combo)

        # Profile name input
        self.profile_name_input = QLineEdit()
        self.profile_name_input.setPlaceholderText("Profile name...")
        # Match firmware buffer (40 B including NUL → 39 byte payload). Enforced
        # at the input layer so users see the limit before silent truncation
        # happens in the BLE encoder.
        self.profile_name_input.setMaxLength(39)
        self.profile_name_input.textEdited.connect(self._mark_dirty)
        layout.addWidget(self.profile_name_input)

        # New profile button
        self.new_profile_btn = QPushButton("New Profile")
        self.new_profile_btn.clicked.connect(self.create_new_profile)
        self.new_profile_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        layout.addWidget(self.new_profile_btn)

        # Save profile button — same logic as File → Save
        self.save_profile_btn = QPushButton("Save Profile")
        self.save_profile_btn.clicked.connect(self.file_save)
        layout.addWidget(self.save_profile_btn)

        # Delete profile button
        self.delete_profile_btn = QPushButton("Delete Profile")
        self.delete_profile_btn.clicked.connect(self.delete_current_profile)
        self.delete_profile_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
        layout.addWidget(self.delete_profile_btn)

        # Widgets shown only in Edit mode
        self._edit_only_top_widgets = [
            self.profile_name_input,
            self.new_profile_btn,
            self.save_profile_btn,
            self.delete_profile_btn,
        ]

        return group
    
    def create_key_panel(self) -> QGroupBox:
        group = QGroupBox("Key Layout")
        layout = QGridLayout(group)

        keys = ['0', '1', '2', '3', '4', '5', '6', '7',
                '8', '9', 'A', 'B', 'C', 'D', 'E', 'F']

        for i, key in enumerate(keys):
            row = i // 4
            col = i % 4
            btn = KeyButton(i, key)
            btn.clicked.connect(lambda checked, key_id=i: self._on_key_click(key_id))
            self.key_buttons[i] = btn
            layout.addWidget(btn, row, col)

        return group
    
    def create_action_panel(self) -> QGroupBox:
        group = QGroupBox("Action Configuration")
        layout = QVBoxLayout(group)

        # Selected key display
        self.selected_key_label = QLabel("Selected Key: None")
        layout.addWidget(self.selected_key_label)

        # Label input
        label_layout = QHBoxLayout()
        label_layout.addWidget(QLabel("Label:"))
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Enter key label...")
        self.label_input.textChanged.connect(self.on_label_changed)
        label_layout.addWidget(self.label_input)
        layout.addLayout(label_layout)

        # Color input with picker
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.color_input = QLineEdit()
        self.color_input.setPlaceholderText("e.g., 220,0,0,70")
        self.color_input.textChanged.connect(self.on_color_changed)
        color_layout.addWidget(self.color_input)
        self.color_picker_btn = QPushButton("Pick Color")
        self.color_picker_btn.clicked.connect(self.open_color_picker)
        self.color_picker_btn.setMaximumWidth(100)
        color_layout.addWidget(self.color_picker_btn)
        layout.addLayout(color_layout)

        # Brightness slider
        bri_layout = QHBoxLayout()
        bri_layout.addWidget(QLabel("Brightness:"))
        self.brightness_slider = QSlider(Qt.Horizontal)  # pyright: ignore[reportAttributeAccessIssue]
        self.brightness_slider.setMinimum(0)
        self.brightness_slider.setMaximum(100)
        self.brightness_slider.setValue(70)
        self.brightness_slider.setTickPosition(QSlider.TicksBelow)
        self.brightness_slider.setTickInterval(10)
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        bri_layout.addWidget(self.brightness_slider)
        self.brightness_label = QLabel("70%")
        self.brightness_label.setMinimumWidth(40)
        bri_layout.addWidget(self.brightness_label)
        layout.addLayout(bri_layout)

        # Action type selector
        action_type_layout = QHBoxLayout()
        action_type_layout.addWidget(QLabel("Action:"))
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItems(["Command", "Macro"])
        self.action_type_combo.currentIndexChanged.connect(self.on_action_type_changed)
        action_type_layout.addWidget(self.action_type_combo)
        action_type_layout.addStretch()
        layout.addLayout(action_type_layout)

        # Command row (visible for Command action type)
        self._command_row = QWidget()
        command_v = QVBoxLayout(self._command_row)
        command_v.setContentsMargins(0, 0, 0, 0)
        command_layout = QHBoxLayout()
        command_layout.addWidget(QLabel("Command:"))
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Enter command or action...")
        self.command_input.textChanged.connect(self.on_command_changed)
        command_layout.addWidget(self.command_input)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_for_executable)
        browse_btn.setMaximumWidth(80)
        command_layout.addWidget(browse_btn)
        command_v.addLayout(command_layout)
        examples = QLabel("Examples: notepad.exe, calc.exe, explorer.exe, cmd /c echo Hello")
        examples.setStyleSheet("color: gray; font-style: italic;")
        command_v.addWidget(examples)
        layout.addWidget(self._command_row)

        # Macro row (visible for Macro action type)
        self._macro_row = QWidget()
        macro_h = QHBoxLayout(self._macro_row)
        macro_h.setContentsMargins(0, 0, 0, 0)
        self.macro_summary_label = QLabel("No steps recorded")
        self.macro_summary_label.setStyleSheet("color: gray;")
        macro_h.addWidget(self.macro_summary_label)
        self.edit_macro_btn = QPushButton("Edit Macro...")
        self.edit_macro_btn.clicked.connect(self.open_macro_dialog)
        macro_h.addWidget(self.edit_macro_btn)
        self._macro_row.setVisible(False)
        layout.addWidget(self._macro_row)

        self.selected_key_id = None

        return group

    def on_action_type_changed(self, index: int) -> None:
        is_macro = index == 1
        self._command_row.setVisible(not is_macro)
        self._macro_row.setVisible(is_macro)
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['action_type'] = "macro" if is_macro else "command"
            self._mark_dirty()

    def open_macro_dialog(self) -> None:
        if self.selected_key_id is None:
            QMessageBox.warning(self, "No Key Selected", "Please select a key first.")
            return
        from macro_dialog import MacroDialog
        key_data = self.key_configs.get(self.selected_key_id, {})
        existing_steps = macro_from_list(key_data.get('macro', []))
        key_label = self.key_id_to_char(self.selected_key_id) or str(self.selected_key_id)
        dialog = MacroDialog(key_label, existing_steps, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            steps = dialog.get_steps()
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['macro'] = macro_to_list(steps)
            self._update_macro_summary(len(steps))
            self._mark_dirty()

    def _update_macro_summary(self, step_count: int) -> None:
        if step_count == 0:
            self.macro_summary_label.setText("No steps recorded")
            self.macro_summary_label.setStyleSheet("color: gray;")
        else:
            label = f"{step_count} step{'s' if step_count != 1 else ''}"
            self.macro_summary_label.setText(label)
            self.macro_summary_label.setStyleSheet("color: green;")
    
    def restore_from_tray(self) -> None:
        self.already_minimized = False
        self.showNormal()
        self.activateWindow()

    def on_tray_icon_activated(self, reason) -> None:
        """
        reason is an enum value. Different PyQt versions expose enums differently;
        check for DoubleClick first, otherwise fall back to Trigger (single click).
        """
        # Try to get enum attributes safely
        dd = getattr(QSystemTrayIcon, "DoubleClick", None)
        trig = getattr(QSystemTrayIcon, "Trigger", None)

        # If DoubleClick available, use it. Otherwise use Trigger as a reliable fallback.
        if dd is not None and reason == dd:
            self.restore_from_tray()
        elif trig is not None and reason == trig:
            # Many Windows setups send Trigger (single click) rather than DoubleClick
            self.restore_from_tray()

    def update_profile_combo(self) -> None:
        # Save current selection
        current_index = self.profile_combo.currentIndex()

        # Block signals to prevent triggering profile change
        self.profile_combo.blockSignals(True)

        # Update combo box items
        self.profile_combo.clear()
        for i, profile in enumerate(self.profiles):
            name = profile.get('name', f'Profile {i}')
            self.profile_combo.addItem(name)

        # Restore selection if valid
        if 0 <= current_index < len(self.profiles):
            self.profile_combo.setCurrentIndex(current_index)

        # Unblock signals
        self.profile_combo.blockSignals(False)
    
    def load_current_profile(self) -> None:
        if self.current_profile_index < len(self.profiles):
            profile = self.profiles[self.current_profile_index]
            self.key_configs = profile.get('keys', {})

            # Convert string keys to int keys
            if self.key_configs and isinstance(next(iter(self.key_configs.keys())), str):
                self.key_configs = {int(k): v for k, v in self.key_configs.items()}

            # Update profile name input
            profile_name = profile.get('name', f'Profile {self.current_profile_index}')
            self.profile_name_input.setText(profile_name)

            # Update profile combo
            self.profile_combo.setCurrentIndex(self.current_profile_index)

            # Update all button labels and colors
            for key_id, btn in self.key_buttons.items():
                key_data = self.key_configs.get(key_id, {})
                btn.set_label(key_data.get('label', ''))
                btn.set_color(key_data.get('color', ''))
    
    def on_profile_changed(self, index) -> None:
        self.current_profile_index = index
        self.load_current_profile()
        if self.is_connected:
            self.log(f"📁 Profile changed to: {self.profiles[index].get('name', f'Profile {index}')}")
            asyncio.create_task(self.send_profile_change())
    
    def _on_key_click(self, key_id: int) -> None:
        if self.mode == "pad":
            asyncio.create_task(
                self.execute_key_action_for_profile(key_id, self.current_profile_index)
            )
        else:
            self.on_key_selected(key_id)

    def on_key_selected(self, key_id) -> None:
        self.selected_key_id = key_id
        key_name = self.key_id_to_char(key_id)
        self.selected_key_label.setText(f"Selected Key: {key_name} (ID: {key_id})")

        # Load existing data for this key
        key_data = self.key_configs.get(key_id, {})
        self.label_input.setText(key_data.get('label', ''))
        self.color_input.setText(key_data.get('color', ''))
        self.command_input.setText(key_data.get('command', ''))

        # Load action type
        action_type = key_data.get('action_type', 'command')
        self.action_type_combo.blockSignals(True)
        self.action_type_combo.setCurrentIndex(1 if action_type == 'macro' else 0)
        self.action_type_combo.blockSignals(False)
        self._command_row.setVisible(action_type != 'macro')
        self._macro_row.setVisible(action_type == 'macro')
        self._update_macro_summary(len(macro_from_list(key_data.get('macro', []))))

        # Update brightness slider
        color_str = key_data.get('color', '')
        if color_str:
            try:
                parts = color_str.split(',')
                if len(parts) == 4:
                    brightness = int(parts[3])
                    self.brightness_slider.blockSignals(True)
                    self.brightness_slider.setValue(brightness)
                    self.brightness_label.setText(f"{brightness}%")
                    self.brightness_slider.blockSignals(False)
            except (ValueError, TypeError):
                self.log(f"Color code: '{color_str}' is invalid")

    def on_label_changed(self, text) -> None:
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['label'] = text.strip()
            # Update button label
            self.key_buttons[self.selected_key_id].set_label(text.strip())
            self._mark_dirty()

    def on_color_changed(self, text) -> None:
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['color'] = text.strip()
            # Update button color
            self.key_buttons[self.selected_key_id].set_color(text.strip())
            # Send notification to change single RGB on BLEDeck
            self.send_rgb(color=text.strip())
            self._mark_dirty()

    def on_command_changed(self, text) -> None:
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['command'] = text.strip()
            self._mark_dirty()

    def ensure_key_data_exists(self) -> None:
        """Ensure the selected key has a dictionary entry"""
        if self.selected_key_id is not None:
            if self.selected_key_id not in self.key_configs:
                self.key_configs[self.selected_key_id] = {'label': '', 'color': '', 'command': ''}

    def open_color_picker(self) -> None:
        """Open color picker dialog"""
        if self.selected_key_id is None:
            QMessageBox.warning(self, "No Key Selected", "Please select a key first.")
            return

        # Get current color if exists
        current_color = QColor(128, 128, 128)  # Default gray
        color_str = self.color_input.text()
        if color_str:
            try:
                parts = color_str.split(',')
                if len(parts) >= 3:
                    r, g, b = map(int, parts[:3])
                    current_color = QColor(r, g, b)
            except (ValueError, TypeError):
                self.log(f"Color code: '{color_str}' is invalid")

        # Open color dialog
        color = QColorDialog.getColor(current_color, self, "Select Key Color")

        if color.isValid():
            # Get RGB values
            r, g, b = color.red(), color.green(), color.blue()
            # Get current brightness or default to 70
            brightness = self.brightness_slider.value()

            # Update color input
            color_string = f"{r},{g},{b},{brightness}"
            self.color_input.setText(color_string)

    def on_brightness_changed(self, value) -> None:
        """Handle brightness slider change"""
        self.brightness_label.setText(f"{value}%")

        if self.selected_key_id is not None:
            # Update the color string with new brightness
            color_str = self.color_input.text()
            if color_str:
                try:
                    parts = color_str.split(',')
                    if len(parts) >= 3:
                        r, g, b = parts[:3]
                        new_color_str = f"{r},{g},{b},{value}"
                        self.color_input.blockSignals(True)
                        self.color_input.setText(new_color_str)
                        self.color_input.blockSignals(False)
                        # Manually trigger color change
                        self.on_color_changed(new_color_str)
                except (ValueError, TypeError):
                    self.log(f"Color code: '{color_str}' is invalid")
    
    def create_new_profile(self) -> None:
        """Create a new empty profile"""
        profile_count = len(self.profiles) + 1
        new_profile = create_new_profile(f"New Profile {profile_count}")
        self.profiles.append(new_profile)

        # Switch to the new profile
        self.current_profile_index = len(self.profiles) - 1
        self.key_configs = {}

        # Update UI
        self.update_profile_combo()
        self.profile_combo.setCurrentIndex(self.current_profile_index)
        self.profile_name_input.setText(new_profile['name'])

        # Clear all button labels and colors
        for btn in self.key_buttons.values():
            btn.set_label('')
            btn.set_color('')

        # Clear the action panel
        if hasattr(self, 'label_input'):
            self.label_input.clear()
        if hasattr(self, 'color_input'):
            self.color_input.clear()
        if hasattr(self, 'command_input'):
            self.command_input.clear()

        self._mark_dirty()
        self.log(f"Created new profile: {new_profile['name']}")
        self.log("Remember to save it before closing or switching profile")

    def _flush_current_profile_to_list(self) -> tuple[str, str]:
        """Sync UI state (name + key_configs) into self.profiles list.
        Returns (old_name, new_name) for the active profile."""
        if self.current_profile_index < len(self.profiles):
            profile = self.profiles[self.current_profile_index]
        else:
            profile = {}
            self.profiles.append(profile)

        old_name = profile.get('name', f'Profile {self.current_profile_index}')
        new_name = self.profile_name_input.text() or f'Profile {self.current_profile_index}'
        profile['name'] = new_name

        filtered_keys = {}
        for k, v in self.key_configs.items():
            has_command = bool(v.get('command', '').strip())
            has_macro = v.get('action_type') == 'macro' and bool(v.get('macro'))
            if has_command or has_macro:
                filtered_keys[str(k)] = v
        profile['keys'] = filtered_keys
        return old_name, new_name

    def save_current_profile(self) -> bool:
        """Persist current profiles list to self.profile_file_path.
        Returns True on success."""
        old_name, new_name = self._flush_current_profile_to_list()

        target = self.profile_file_path
        if target is None:
            # New unsaved file - delegate to save_as flow
            return self._save_as_flow()

        if not save_profiles_to(target, self.profiles):
            QMessageBox.critical(self, "Save failed", f"Could not write {target}")
            return False

        self.is_dirty = False
        self.update_profile_combo()
        self._update_title()
        self.log(f"Profile saved to {target}")

        if self.is_connected and old_name != new_name:
            self.log(f"📁 Profile name changed: '{old_name}' → '{new_name}'")
            asyncio.create_task(self.synchronize_profiles_to_device())
        return True

    def _save_as_flow(self) -> bool:
        """Prompt the user: save as default (APPDATA) or pick a custom path."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Save Profiles")
        box.setText("Where should this new profile file be saved?")
        default_btn = box.addButton("Save as Default", QMessageBox.AcceptRole)
        custom_btn = box.addButton("Save As...", QMessageBox.ActionRole)
        cancel_btn = box.addButton(QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return False
        if clicked is default_btn:
            target = CONFIG_PATH
            if target.exists():
                confirm = QMessageBox.warning(
                    self, "Overwrite default?",
                    f"The default profile file already exists:\n{target}\n\n"
                    "Saving will overwrite it. Continue?",
                    QMessageBox.Yes | QMessageBox.Cancel,
                    QMessageBox.Cancel,
                )
                if confirm != QMessageBox.Yes:
                    return False
        else:
            path_str, _ = QFileDialog.getSaveFileName(
                self, "Save Profiles As", str(CONFIG_PATH.parent / "profiles.json"),
                "JSON Files (*.json);;All Files (*.*)"
            )
            if not path_str:
                return False
            target = Path(path_str)

        if not save_profiles_to(target, self.profiles):
            QMessageBox.critical(self, "Save failed", f"Could not write {target}")
            return False

        self.profile_file_path = target
        self.is_dirty = False
        self.update_profile_combo()
        self._update_title()
        self.log(f"Profile saved to {target}")
        return True

    # --- File menu actions ---------------------------------------------------

    def file_save(self) -> None:
        self.save_current_profile()

    def file_new(self) -> None:
        if not self._confirm_discard_changes():
            return
        new_profile = create_new_profile("New Profile")
        self.profiles = [new_profile]
        self.current_profile_index = 0
        self.key_configs = {}
        self.profile_file_path = None
        self.is_dirty = True
        self.update_profile_combo()
        self.profile_combo.setCurrentIndex(0)
        self.load_current_profile()
        self._update_title()
        self.log("Started new profile file (unsaved)")

    def file_open(self) -> None:
        if not self._confirm_discard_changes():
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open Profiles", str(CONFIG_PATH.parent),
            "JSON Files (*.json);;All Files (*.*)"
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            profiles = load_profiles_from(path)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Open failed", f"Could not read {path}:\n{e}")
            return
        if not profiles:
            QMessageBox.warning(self, "Empty file", "The selected file contains no profiles.")
            return
        self.profiles = profiles
        self.profile_file_path = path
        self.current_profile_index = 0
        self.is_dirty = False
        self.update_profile_combo()
        self.profile_combo.setCurrentIndex(0)
        self.load_current_profile()
        self._update_title()
        self.log(f"Loaded profiles from {path}")
        if self.is_connected:
            asyncio.create_task(self.synchronize_profiles_to_device())
            asyncio.create_task(self.send_profile_change())

    def _confirm_discard_changes(self) -> bool:
        """Returns True if it is safe to discard the current in-memory edits."""
        if not self.is_dirty:
            return True
        reply = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Save before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Cancel:
            return False
        if reply == QMessageBox.Save:
            return self.save_current_profile()
        return True

    # --- Mode / Debug / Title ------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._apply_mode()

    def _apply_mode(self) -> None:
        is_edit = self.mode == "edit"
        self.action_panel.setVisible(is_edit)
        for w in getattr(self, "_edit_only_top_widgets", []):
            w.setVisible(is_edit)
        # Keep menu actions in sync if called programmatically
        self.action_mode_edit.setChecked(is_edit)
        self.action_mode_pad.setChecked(not is_edit)
        # Resize window to fit visible content
        if is_edit:
            self.resize(900, 700)
        else:
            self.resize(520, 460)

    def set_debug(self, enabled: bool) -> None:
        self.debug_enabled = enabled
        self._apply_debug()

    def _apply_debug(self) -> None:
        self.log_panel.setVisible(self.debug_enabled)

    def _mark_dirty(self, *_args) -> None:
        if not self.is_dirty:
            self.is_dirty = True
            self._update_title()

    def _update_title(self) -> None:
        base = APP_NAME
        if self.profile_file_path is None:
            suffix = " — [Unsaved]"
        elif self.profile_file_path != CONFIG_PATH:
            suffix = f" — {self.profile_file_path}"
        else:
            suffix = ""
        dirty = "*" if self.is_dirty else ""
        self.setWindowTitle(f"{_TITLE_PREFIX}{base}{suffix}{dirty}")

    # --- Help menu actions ---------------------------------------------------

    def show_manual(self) -> None:
        manual_path = _resource_path("manual.md")
        dlg = QDialog(self)
        dlg.setWindowTitle("BLEDeck Manual")
        dlg.resize(820, 680)
        v = QVBoxLayout(dlg)
        viewer = QTextBrowser(dlg)
        viewer.setOpenExternalLinks(True)
        try:
            text = manual_path.read_text(encoding="utf-8")
            viewer.setHtml(self._render_manual_html(text))
        except OSError as e:
            viewer.setPlainText(f"Could not load manual.md:\n{e}")
        v.addWidget(viewer)
        # Extra buttons: let the user pop the source file open in their default
        # browser/editor or jump to the canonical GitHub copy. Solves the "I want
        # to share / print this section" friction the in-app viewer can't satisfy.
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)

        github_btn = buttons.addButton("View source on GitHub", QDialogButtonBox.ActionRole)
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(f"{APP_GITHUB_URL}/blob/main/windows_app/manual.md")
        ))

        open_btn = buttons.addButton("Open in browser", QDialogButtonBox.ActionRole)
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(manual_path))
        ))

        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        v.addWidget(buttons)
        dlg.exec_()

    @staticmethod
    def _render_manual_html(md_text: str) -> str:
        """Convert markdown to HTML for QTextBrowser. Falls back to plain
        Qt markdown if the `markdown` package is unavailable."""
        try:
            import markdown
            body = markdown.markdown(
                md_text,
                extensions=["tables", "fenced_code", "sane_lists", "toc"],
                output_format="html",
            )
        except ImportError:
            return f"<pre>{html.escape(md_text)}</pre>"
        css = """
        <style>
            body { font-family: 'Segoe UI', sans-serif; font-size: 10pt; }
            h1 { font-size: 18pt; }
            h2 { font-size: 14pt; border-bottom: 1px solid #ccc;
                 padding-bottom: 4px; margin-top: 18px; }
            h3 { font-size: 12pt; }
            code { background: #f3f3f3; padding: 1px 4px; border-radius: 3px;
                   font-family: Consolas, monospace; }
            pre { background: #f3f3f3; padding: 8px; border-radius: 4px;
                  font-family: Consolas, monospace; }
            table { border-collapse: collapse; margin: 8px 0; }
            th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
            th { background: #efefef; }
            blockquote { border-left: 3px solid #ccc; margin: 8px 0;
                         padding: 4px 12px; color: #555; }
            hr { border: none; border-top: 1px solid #ddd; margin: 16px 0; }
        </style>
        """
        return f"<html><head>{css}</head><body>{body}</body></html>"

    def _forget_paired_device(self) -> None:
        """Drop the cached preferred-device MAC. The next scan will pick the
        first BLEDeck found, then re-pin to whatever the user picks next."""
        current = self.app_settings.get("preferred_device_mac")
        if not current:
            QMessageBox.information(
                self, "Forget paired device",
                "No device is currently pinned. The next successful connect "
                "will pin its MAC automatically.",
            )
            return
        confirm = QMessageBox.question(
            self, "Forget paired device",
            f"Forget the pinned device ({current})?\n\n"
            "Next scan will pick whichever BLEDeck answers first, then re-pin "
            "to it. Use this when you swap to a different physical device.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        self.app_settings["preferred_device_mac"] = None
        if save_settings(self.app_settings):
            self.log(f"📌 Forgot pinned device: {current}")
            QMessageBox.information(
                self, "Forget paired device",
                "Pinned device cleared. Next scan picks the first BLEDeck found.",
            )
        else:
            QMessageBox.warning(
                self, "Forget paired device",
                "Could not write app_settings.json. Check %APPDATA% permissions.",
            )

    def show_info(self) -> None:
        authors = ", ".join(APP_AUTHORS)
        html = (
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version: {APP_VERSION}</p>"
            f"<p>Author(s): {authors}</p>"
            f'<p>GitHub: <a href="{APP_GITHUB_URL}">{APP_GITHUB_URL}</a></p>'
        )
        box = QMessageBox(self)
        box.setWindowTitle("About BLEDeck")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec_()
    
    def sync_profile_from_device(self, device_profile_index: int) -> None:
        """Update app profile to match device profile (called when device encoder changes profile)"""
        # Snapshot once so list-mutation during this method can't make us
        # re-index into a stale length.
        profiles_snapshot = self.profiles
        if not (0 <= device_profile_index < len(profiles_snapshot)):
            return
        profile = profiles_snapshot[device_profile_index]
        self.current_profile_index = device_profile_index

        # Update combo box without triggering the change event (to avoid sending back to device)
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(device_profile_index)
        self.profile_combo.blockSignals(False)

        # Load the profile data (actions, name, etc.)
        self.load_current_profile()

        profile_name = profile.get('name', f'Profile {device_profile_index}')
        self.log(f"✅ App profile synced to: '{profile_name}'")
        if self.isMinimized():
            self.tray_icon.showMessage(
                "Profile Changed",
                f"'{profile_name}' is the profile now in use.",
                QIcon(_ICON_PATH),
                500
            )
        # Send back the colors
        self.send_rgb()
    
    def parse_color_string(self, color_str: str) -> ble_protocol.RGBW:
        """Parse color string 'R,G,B,W' into tuple (r, g, b, w)"""
        result = ble_protocol.parse_color_string(color_str)
        if result is None:
            if color_str:
                self.log(f"⚠️ Error parsing color '{color_str}'")
            return (0, 0, 0, 0)
        return result

    def _flush_pending_color(self) -> None:
        """Send the most recent pending colour packet, if any."""
        packet = self._pending_color_packet
        self._pending_color_packet = None
        if packet is None or not self.is_connected:
            return
        asyncio.create_task(self.send_ble(packet))

    def send_rgb(self, color: str | None = None) -> None:
        """Send RGB color(s) to device using binary protocol.

        Single-key updates from rapid UI edits (slider drag, colour text box,
        picker dialog) are coalesced through ``_color_send_timer`` so we don't
        saturate the BLE link. Bulk ``set_all_rgb_keys`` pushes are still
        dispatched immediately — they're one-shot boot/profile-change events.
        """
        if color:
            r, g, b, w = self.parse_color_string(color)
            packet = ble_protocol.set_rgb_key(
                        self.selected_key_id,
                        r, g, b, w
                    )
            self._pending_color_packet = packet
            self._color_send_timer.start()  # restarts countdown on each edit
            return

        # Send all 16 key colors
        rgbw_list = []
        profile_keys = self.profiles[self.current_profile_index].get("keys", {})

        # Build list of 16 RGBW tuples in order (0-15)
        for i in range(16):
            key_data = profile_keys.get(str(i), {})
            color_str = key_data.get('color', '0,0,0,0')
            rgbw_list.append(self.parse_color_string(color_str))
        packet = ble_protocol.set_all_rgb_keys(rgbw_list)
        asyncio.create_task(self.send_ble(packet))

    def delete_current_profile(self) -> None:
        if len(self.profiles) <= 1:
            QMessageBox.warning(self, "Cannot Delete", "Cannot delete the last profile. At least one profile must exist.")
            return
        
        profile_name = self.profiles[self.current_profile_index].get('name', f'Profile {self.current_profile_index}')
        reply = QMessageBox.question(self, "Delete Profile", 
                                   f"Are you sure you want to delete profile '{profile_name}'?",
                                   QMessageBox.Yes | QMessageBox.No, 
                                   QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # Remove the profile
            del self.profiles[self.current_profile_index]

            # Adjust current index if needed
            if self.current_profile_index >= len(self.profiles):
                self.current_profile_index = len(self.profiles) - 1

            # Mark dirty — user must save manually (matches other mutations)
            self._mark_dirty()
            self.update_profile_combo()
            self.load_current_profile()
            self._update_title()
            self.log(f"Profile '{profile_name}' deleted")
            
            # Resync all profiles with device after deletion
            if self.is_connected:
                asyncio.create_task(self.synchronize_profiles_to_device())
                # Update current profile on device
                asyncio.create_task(self.send_profile_change())
    
    def browse_for_executable(self) -> None:
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(
            self,
            "Select Executable",
            "",
            "Executable Files (*.exe);;Batch Files (*.bat);;All Files (*.*)"
        )

        if file_path:
            # Use quotes if path contains spaces
            if ' ' in file_path:
                file_path = f'"{file_path}"'
            self.command_input.setText(file_path)
    
    def toggle_connection(self) -> None:
        if self.is_connected:
            self.log("🔌 Manual disconnect requested")
            asyncio.create_task(self.manual_disconnect())
        else:
            self.log("🔌 Manual connect requested") 
            asyncio.create_task(self.connect())
    
    async def manual_disconnect(self) -> None:
        # Stop auto-connect when manually disconnecting
        self.connect_timer.stop()
        await self.disconnect()
        # Only restart auto-connect if checkbox is enabled
        if self.auto_reconnect_cb.isChecked():
            QTimer.singleShot(
                30000,
                lambda: self.connect_timer.start(self._reconnect_backoff_ms),
            )  # 30 second delay before resuming auto-reconnect
    
    def toggle_auto_reconnect(self, checked: bool) -> None:
        if checked:
            self.log("🔄 Auto-reconnect enabled")
            if not self.is_connected:
                self.connect_timer.start(self._reconnect_backoff_ms)
        else:
            self.log("🔄 Auto-reconnect disabled")
            self.connect_timer.stop()
    
    async def _await_opcode(self, opcode: int, timeout: float = 1.0) -> bool:
        """Wait for the next incoming packet with the given opcode.

        Returns True on receipt, False on timeout. Callers should treat False as
        "device did not reply; continue with the bootstrap anyway" — we do not
        want a flaky link to wedge the connect path forever.
        """
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._opcode_waiters[opcode] = fut
        try:
            await asyncio.wait_for(fut, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            self.log(f"⏳ Timeout waiting for opcode 0x{opcode:02X}")
            return False
        finally:
            self._opcode_waiters.pop(opcode, None)

    async def connect(self) -> None:
        if self._connecting or self.is_connected:
            return
        self._connecting = True
        self.status_label.setText("Status: Connecting...")
        self.status_bar.showMessage("Connecting...")
        try:
            self.log("Scanning for BLEDeck...")

            # Primary scan: filter by service UUID (works when UUID is in the
            # advertisement packet).
            devices = await asyncio.wait_for(
                BleakScanner.discover(timeout=4.0, service_uuids=[SERVICE_UUID]),
                timeout=6.0,
            )

            if not devices:
                # WinRT's BluetoothLEAdvertisementFilter only inspects the
                # advertisement payload, not the scan response. ESP32 typically
                # puts the service UUID in the scan response, so the primary
                # scan may return nothing. Fall back to a name-based scan.
                self.log("UUID scan found nothing, trying name scan...")
                all_devs = await asyncio.wait_for(
                    BleakScanner.discover(timeout=4.0),
                    timeout=6.0,
                )
                devices = [d for d in all_devs if d.name and DEVICE_NAME in d.name]

            # Prefer the previously-paired MAC when present (rules out the
            # "colleague's BLEDeck wins the race" failure mode). Falls back to
            # name match, then any service-UUID hit.
            preferred = self.app_settings.get("preferred_device_mac")
            target = None
            if preferred:
                target = next(
                    (d for d in devices if d.address.upper() == preferred.upper()),
                    None,
                )
                if target is not None:
                    self.log(f"Matched preferred device {preferred}")
            if target is None:
                target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
            if target is None and devices:
                target = devices[0]
                self.log(f"Found device by service UUID: {target.address}")

            if not target:
                self.log("❌ Device not found")
                self.log("   • Is Bluetooth enabled in Windows Settings?")
                self.log("   • Is the device powered on (OLED lit)?")
                self.log("   • See docs/troubleshooting.md → Connection table for more")
                self.status_label.setText("Status: Disconnected")
                self.status_bar.showMessage("Device not found — see logs")
                return
            
            self.log(f"Found device: {target.name} ({target.address})")
            self.ble_client = BleakClient(target.address, disconnected_callback=self._on_ble_disconnected)
            
            # Connect with timeout
            await asyncio.wait_for(self.ble_client.connect(), timeout=10.0)

            # Verify connection
            if not self.ble_client.is_connected:
                raise Exception("Connection failed after connect call")

            # Verify the connected peripheral actually exposes the expected
            # GATT service and characteristics. Raises before trusting any
            # notifications — prevents acting on a rogue peripheral that only
            # spoofs the service UUID in its advertisement.
            svc = self.ble_client.services.get_service(SERVICE_UUID)
            if svc is None:
                raise RuntimeError(
                    f"GATT service {SERVICE_UUID} not found — possible rogue device"
                )
            if (svc.get_characteristic(CHAR_TX_UUID) is None
                    or svc.get_characteristic(CHAR_RX_UUID) is None):
                raise RuntimeError(
                    "Expected GATT characteristics missing — possible rogue device"
                )
            
            self.is_connected = True
            
            # Start notifications with error handling
            try:
                await self.ble_client.start_notify(CHAR_TX_UUID, self.handle_notification)
            except Exception as e:
                self.log(f"❌ Failed to start notifications: {e}")
                await self.disconnect()
                return
            
            # Update UI
            self.status_label.setText("Status: Connected")
            self.connect_btn.setText("Disconnect")
            self.status_bar.showMessage(f"Connected to {target.address}")
            
            # Reset connection health tracking
            self.last_ping_response = time.time()

            # Pin this MAC as preferred (only persisted on the first save —
            # subsequent connects to the same MAC do nothing).
            current_mac = (self.app_settings.get("preferred_device_mac") or "").upper()
            if target.address and target.address.upper() != current_mac:
                self.app_settings["preferred_device_mac"] = target.address
                if save_settings(self.app_settings):
                    self.log(f"📌 Pinned preferred device MAC: {target.address}")

            # Reset reconnect backoff after a clean handshake.
            self._reconnect_backoff_ms = _RECONNECT_BACKOFF_MIN_MS

            # Send HELLO first; device replies with DEVICE_TELEMETRY (firmware version,
            # uptime, free heap, BLE error count). Wait on it so we know the device is
            # truly alive and the protocol versions match before we push profile data.
            try:
                await self.send_ble(ble_protocol.hello(APP_VERSION))
            except Exception:
                logger.exception("HELLO send failed")
            await self._await_opcode(ble_protocol.OP_DEVICE_TELEMETRY, timeout=1.5)

            # Ping to confirm round-trip, then push profiles.
            await self.send_ble(ble_protocol.keep_alive())
            await self._await_opcode(ble_protocol.OP_KEEP_ALIVE_REPLY, timeout=1.0)

            await self.synchronize_profiles_to_device()
            await self.send_profile_change()

            # Start timers
            self.ping_timer.start(10000)  # Ping every 10 seconds

            self.log(f"✅ Connected to {target.address}")
            
        except asyncio.TimeoutError:
            self.log("❌ Connection timeout")
            await self.cleanup_failed_connection()
            self.status_label.setText("Status: Disconnected")
            self.status_bar.showMessage("Disconnected")
            self._bump_reconnect_backoff()
        except Exception as e:
            self.log(f"❌ Connection failed: {str(e)}")
            await self.cleanup_failed_connection()
            self.status_label.setText("Status: Disconnected")
            self.status_bar.showMessage("Disconnected")
            self._bump_reconnect_backoff()
        finally:
            self._connecting = False

    def _bump_reconnect_backoff(self) -> None:
        """Double the auto-reconnect interval up to the configured cap and,
        if auto-reconnect is enabled, restart the timer with the new value."""
        self._reconnect_backoff_ms = min(
            self._reconnect_backoff_ms * 2,
            _RECONNECT_BACKOFF_MAX_MS,
        )
        if self.auto_reconnect_cb.isChecked() and not self.is_connected:
            self.connect_timer.start(self._reconnect_backoff_ms)
            secs = self._reconnect_backoff_ms / 1000
            self.log(f"⏳ Next reconnect attempt in {secs:.0f}s")
    
    async def cleanup_failed_connection(self) -> None:
        self.is_connected = False
        if self.ble_client:
            await self.ble_client.disconnect()
        self.ble_client = None
    
    async def disconnect(self) -> None: # pyright: ignore[reportIncompatibleMethodOverride]
        # Prevent multiple simultaneous disconnects
        if not self.is_connected:
            return

        self.log("🔌 Starting disconnect process...")

        # Mark as disconnected immediately to prevent new operations
        self.is_connected = False
        self._encryption_pending = False

        # Stop timers first
        self.ping_timer.stop()
        
        if self.ble_client:
            try:
                # Always try to disconnect, even if is_connected is unreliable
                self.log("🔌 Calling BLE disconnect...")
                await asyncio.wait_for(self.ble_client.disconnect(), timeout=8.0)
                self.log("🔌 BLE disconnect completed")
            except asyncio.TimeoutError:
                self.log("⚠️ Disconnect timeout - forcing cleanup")
            except asyncio.CancelledError:
                self.log("⚠️ Disconnect cancelled")
            except Exception as e:
                self.log(f"⚠️ Disconnect error (ignored): {e}")
            finally:
                self.ble_client = None
        
        # Update UI
        self.status_label.setText("Status: Disconnected")
        self.battery_label.setText("")
        self.connect_btn.setText("Connect")
        self.status_bar.showMessage("Disconnected")

        # Reset key states
        for btn in self.key_buttons.values():
            btn.set_active(False)
        
        self.log("✅ Disconnected")

    def _on_ble_disconnected(self, client: BleakClient) -> None:
        """Bleak calls this from its thread when the device drops unexpectedly."""
        QTimer.singleShot(0, lambda: asyncio.create_task(self._handle_unexpected_disconnect()))

    async def _handle_unexpected_disconnect(self) -> None:
        if not self.is_connected:
            return
        self.log("❌ Device disconnected unexpectedly")
        await self.disconnect()
        if self.auto_reconnect_cb.isChecked():
            self.log("🔄 Auto-reconnect: retrying in 10s...")
            self.connect_timer.start(10000)

    async def _run_sim_cli(self) -> None:
        """Loopback mode (BLEDECK_SIM=1): run simulator REPL in this process.

        When the REPL exits (user types `q` / `quit` / `exit`, or stdin is
        closed) we tear the GUI down too — running the app without its CLI
        partner is rarely useful in simulator mode and the previous
        behaviour stranded the app foreground until the user killed it.
        """
        from simulator._context import get_state, get_active_client
        from simulator.cli import run_cli
        loop = asyncio.get_event_loop()
        state = get_state()

        async def _send(data: bytes) -> None:
            client = get_active_client()
            if client:
                await client.push_event(data)  # type: ignore[attr-defined]

        try:
            await run_cli(state, _send, loop)
        finally:
            logger.info("Simulator CLI exited — shutting down GUI")
            # Schedule the shutdown on the Qt thread so the cleanup path
            # (closeEvent → disconnect → quit_event.set) runs normally.
            QTimer.singleShot(0, self.close)

    async def send_ble(self, data: bytes) -> None:
        """Send binary data to BLE device"""
        if not self.ble_client or not self.is_connected:
            return

        try:
            # Check if client is still valid before sending
            if not self.ble_client.is_connected:
                asyncio.create_task(self._handle_unexpected_disconnect())
                return

            # Send with timeout but don't disconnect on timeout (could be temporary)
            try:
                await asyncio.wait_for(
                    self.ble_client.write_gatt_char(CHAR_RX_UUID, data),
                    timeout=5.0
                )
            except asyncio.CancelledError:
                # Task was cancelled (likely during disconnect) - this is normal
                self.log("⚠️ Send cancelled")
                return

            # Log in hex format for binary data (with opcode hint)
            opcode_hint = ""
            if len(data) >= 2:
                op = data[1]
                op_names = {0x01:"PING", 0x02:"CHG_PROF", 0x03:"SYNC", 0x04:"RGB_KEY", 0x05:"RGB_ALL", 0x06:"LOCK", 0x07:"HELLO"}
                opcode_hint = f" [{op_names.get(op, f'0x{op:02X}')}]"
            self.log(f"→ {data.hex()}{opcode_hint}")

        except asyncio.TimeoutError:
            self.log("⚠️ Send timeout (keeping connection)")
            # Don't disconnect on timeout - might be temporary
        except (OSError, BrokenPipeError) as e:
            # Connection broken errors
            self.log(f"❌ Connection error: {str(e)}")
            await self.disconnect()
        except Exception as e:
            # Only disconnect on actual BLE errors (device gone, etc.)
            if "not connected" in str(e).lower() or "device" in str(e).lower():
                self.log(f"❌ Device disconnected: {str(e)}")
                await self.disconnect()
            else:
                if "insufficient encryption" in str(e).lower():
                    self._encryption_pending = True
                self.log(f"⚠️ Send failed: {str(e)} (keeping connection)")
    
    async def synchronize_profiles_to_device(self) -> None:
        """Send all profile names to the device using binary protocol"""
        self.log(f"📁 Synchronizing {len(self.profiles)} profiles to device...")

        # Build profiles dictionary (1-indexed for device)
        profiles_dict = {}
        for i, profile in enumerate(self.profiles):
            profile_name = profile.get('name', f'Profile {i}')
            profiles_dict[i + 1] = profile_name  # Device uses 1-based indexing
            self.log(f"  Profile {i+1}: '{profile_name}'")

        packet = ble_protocol.sync_profiles(profiles_dict)
        self.log(f"  Packet size: {len(packet)} bytes")
        await self.send_ble(packet)

        self.log("📁 Profile synchronization complete")
    
    async def send_profile_change(self) -> None:
        """Send complete profile data to device when app changes profiles"""
        profile = self.profiles[self.current_profile_index]
        profile_name = profile.get('name', f'Profile {self.current_profile_index}')
        profile_keys = profile.get("keys", {})

        self.log(f"📁 Sending profile change to device: {self.current_profile_index} - '{profile_name}'")

        # Build list of 16 RGBW tuples in order (0-15)
        rgbw_list = []
        for i in range(16):
            key_data = profile_keys.get(str(i), {})
            color_str = key_data.get('color', '0,0,0,0')
            rgbw_list.append(self.parse_color_string(color_str))

        # Send CHANGE_PROFILE command with profile index (1-based) and name
        profile_packet = ble_protocol.change_profile(
            self.current_profile_index + 1,  # Device uses 1-based indexing
            profile_name
        )
        await self.send_ble(profile_packet)

        rgb_packet = ble_protocol.set_all_rgb_keys(
            rgbw_list
        )
        await self.send_ble(rgb_packet)

    async def _resync_after_encryption(self) -> None:
        """Re-sync profiles to device after BLE encryption is established on first pair."""
        # No ACK opcode signals "encryption settled" — yield briefly so Qt can
        # repaint and the firmware's encryption handshake completes before we
        # push profile data on the now-encrypted link.
        await asyncio.sleep(0.05)
        if not self.is_connected:
            return
        self.log("🔐 Encryption established — re-syncing profiles...")
        await self.synchronize_profiles_to_device()
        await self.send_profile_change()

    def send_ping(self) -> None:
        if self.is_connected:
            self.log(f"🏓 Sending ping (last response: {int(time.time() - self.last_ping_response)}s ago)")
            packet = ble_protocol.keep_alive()
            asyncio.create_task(self.send_ble(packet))
    
    def auto_connect(self) -> None:
        if not self.is_connected:
            asyncio.create_task(self.connect())
    
    def handle_notification(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Sync bleak callback — schedules async processing on the running loop."""
        asyncio.create_task(self._process_notification(sender, data))

    async def _process_notification(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle incoming binary protocol packets from device"""
        try:
            # Check if we're still connected
            if not self.is_connected:
                return

            # Any message is a sign of life - update connection health
            self.last_ping_response = time.time()

            if self._encryption_pending:
                self._encryption_pending = False
                asyncio.create_task(self._resync_after_encryption())

            # Log raw data (with opcode hint)
            opcode_hint = ""
            if len(data) >= 2:
                op = data[1]
                opcode_hint = f" [{_OP_NAMES.get(op, f'0x{op:02X}')}]"
            self.log(f"← {data.hex()}{opcode_hint}")

            # Parse binary packet
            try:
                opcode, payload = ble_protocol.BLEPacket.parse(data)
            except ValueError as e:
                self.log(f"⚠️ Invalid packet: {e}")
                return

            # Resolve any pending opcode waiter before the dispatch chain runs.
            # The connect() bootstrap parks on these futures so the next step
            # only fires once the device has actually acknowledged the prior
            # one. Resolution is non-terminal — dispatch still runs below.
            waiter = self._opcode_waiters.get(opcode)
            if waiter is not None and not waiter.done():
                waiter.set_result(payload)

            # Handle different opcodes
            try:
                if opcode == ble_protocol.OP_KEEP_ALIVE_REPLY:
                    self.log("🏓 Ping response received")

                elif opcode == ble_protocol.OP_PROFILE_CHANGED:
                    device_profile_index = ble_protocol.parse_profile_changed(payload)
                    self.log(f"📁 Device changed to profile: {device_profile_index}")

                    # Update app to match device profile (device uses 0-based indexing)
                    if 0 <= device_profile_index < len(self.profiles):
                        # Only update if different from current app profile
                        if device_profile_index != self.current_profile_index:
                            self.log(f"📁 Syncing app profile from {self.current_profile_index} → {device_profile_index}")
                            self.sync_profile_from_device(device_profile_index)
                    else:
                        self.log(f"⚠️ Device profile index {device_profile_index} is out of range")

                elif opcode == ble_protocol.OP_KEY_PRESSED:
                    profile_index, key_char = ble_protocol.parse_key_pressed(payload)

                    # Bound device-controlled profile index before dispatch.
                    if not (0 <= profile_index < len(self.profiles)):
                        self.log(f"⚠️ KEY_PRESSED bad profile {profile_index}")
                        return

                    key_char = key_char.upper()
                    key_id = self.char_to_key_id(key_char)
                    if key_id is None:
                        self.log(f"⚠️ Unknown key character: '{key_char}'")
                        return

                    self.log(f"🎹 Key pressed: '{key_char}' (ID: {key_id}) on profile {profile_index}")

                    # Light up the key temporarily
                    if key_id in self.key_buttons:
                        self.key_buttons[key_id].set_active(True)
                        QTimer.singleShot(200, lambda: self.key_buttons[key_id].set_active(False))

                    # Execute the action using the device's profile
                    await self.execute_key_action_for_profile(key_id, profile_index)

                elif opcode == ble_protocol.OP_BUTTON_PRESSED:
                    profile_index, button_name = ble_protocol.parse_button_pressed(payload)
                    if not (0 <= profile_index < len(self.profiles)):
                        self.log(f"⚠️ BUTTON_PRESSED: profile index {profile_index} out of range")
                        return
                    self.log(f"🔘 Button pressed: '{button_name}' on profile {profile_index}")
                    # You can add button-specific handling here if needed

                elif opcode == ble_protocol.OP_BATTERY_STATUS:
                    percent = ble_protocol.parse_battery_status(payload)
                    if percent == 255:
                        self.log("🔋 Battery: USB / no battery")
                    else:
                        self.log(f"🔋 Battery: {percent}%")
                    self.update_battery_display(percent)

                elif opcode == ble_protocol.OP_DEVICE_TELEMETRY:
                    telemetry = ble_protocol.parse_device_telemetry(payload)
                    self.log(
                        "📟 Device telemetry: fw={fw} proto={p} uptime={u}s "
                        "reset={r} free_heap={h}B ble_errors={e}".format(
                            fw=telemetry["firmware_version"],
                            p=telemetry["protocol_version"],
                            u=telemetry["uptime_ms"] // 1000,
                            r=telemetry["reset_reason"],
                            h=telemetry["free_heap"],
                            e=telemetry["ble_error_count"],
                        )
                    )
                    if telemetry["protocol_version"] != ble_protocol.PROTOCOL_VERSION:
                        msg = (
                            "Protocol version mismatch: app speaks v"
                            f"{ble_protocol.PROTOCOL_VERSION}, device speaks v"
                            f"{telemetry['protocol_version']}. "
                            "Behaviour may diverge; upgrade firmware or app."
                        )
                        self.log(f"⚠️ {msg}")
                        logger.critical(msg)
                        self.status_bar.showMessage(
                            f"⚠️ Protocol mismatch (app v{ble_protocol.PROTOCOL_VERSION} "
                            f"vs device v{telemetry['protocol_version']})"
                        )

                else:
                    self.log(f"⚠️ Unknown opcode: 0x{opcode:02X}")
            except ValueError as e:
                self.log(f"⚠️ Malformed opcode 0x{opcode:02X}: {e}")

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("❌ Notification handler error")
    
    async def execute_key_action_for_profile(self, key_id: int, profile_index: int) -> None:
        """Execute action for a specific profile. Caller must bounds-check profile_index."""
        profile = self.profiles[profile_index]
        profile_keys = profile.get('keys', {})

        if profile_keys and isinstance(next(iter(profile_keys.keys())), str):
            profile_keys = {int(k): v for k, v in profile_keys.items()}

        key_data = profile_keys.get(key_id)
        profile_name = profile.get('name', f'Profile {profile_index}')

        if key_data:
            self.log(f"⚡ Key {key_id} in '{profile_name}'")
            # log_fn may be called from a worker thread — proxy to main thread
            def thread_safe_log(msg: str) -> None:
                QTimer.singleShot(0, lambda: self.log(msg))
            self._action_runner.run(key_data, key_id, profile_index, thread_safe_log)
        else:
            self.log(f"⚠️ No action defined for key {key_id} in profile '{profile_name}'")
    
    def char_to_key_id(self, key_char: str) -> int | None:
        """Convert key character to key ID (0-15)"""
        # Key mapping: 0-9 = IDs 0-9, A-F = IDs 10-15
        key_mapping = {
            '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
            'A': 10, 'B': 11, 'C': 12, 'D': 13, 'E': 14, 'F': 15
        }
        return key_mapping.get(key_char)
    
    def key_id_to_char(self, key_id: int) -> str | None:
        """Convert key ID to character"""
        if 0 <= key_id <= 9:
            return str(key_id)
        elif 10 <= key_id <= 15:
            return chr(ord('A') + key_id - 10)  # 10->A, 11->B, etc.
        return None
    
    def update_battery_display(self, percent: int) -> None:
        if percent == 255:
            self.battery_label.setText("USB")
        else:
            self.battery_label.setText(f"Bat: {percent}%")

    def log(self, message: str) -> None:
        # Skip the work entirely for chatty keep-alive records when the debug
        # panel is hidden — the file handler filter would drop them anyway and
        # we'd waste a Qt repaint on each ping cycle.
        if not self.debug_enabled:
            for p in _KeepAliveLogFilter._PATTERNS:
                if p in message:
                    return
        self.log_text.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())  # pyright: ignore[reportOptionalMemberAccess]
        # Also persist to the rotating file log (keep-alive lines are dropped
        # by `_KeepAliveLogFilter`, so chatty pings don't bloat history).
        logger.info(message)

    # ------------------------------------------------------------------
    # Native event hook — receive WM_WTSSESSION_CHANGE for instant lock
    # detection. PyQt5 hands us a `voidptr` pointing at the native MSG
    # struct; ctypes reads the first three fields.
    # ------------------------------------------------------------------
    def nativeEvent(self, eventType, message):  # type: ignore[override]
        if eventType == b"windows_generic_MSG":
            try:
                msg = WtsMsg.from_address(int(message))
            except (TypeError, ValueError):
                return False, 0
            if msg.message == WM_WTSSESSION_CHANGE:
                if msg.wParam == WTS_SESSION_LOCK and not self.was_locked:
                    self.was_locked = True
                    if self.is_connected:
                        asyncio.create_task(self.send_ble(ble_protocol.lock_device(True)))
                    self.log("🔒 Screen locked (WTS event)")
                elif msg.wParam == WTS_SESSION_UNLOCK and self.was_locked:
                    self.was_locked = False
                    if self.is_connected:
                        asyncio.create_task(self.send_ble(ble_protocol.lock_device(False)))
                    self.log("🔓 Screen unlocked (WTS event)")
        return False, 0
    
    def screen_locked(self) -> None:
        """Detect workstation lock and notify the device."""
        if not self.is_connected:
            return

        is_locked = is_workstation_locked()

        if is_locked and not self.was_locked:
            packet = ble_protocol.lock_device(True)
            asyncio.create_task(self.send_ble(packet))
            self.was_locked = True
            self.log("🔒 Screen locked: True")
        elif self.was_locked and not is_locked:
            packet = ble_protocol.lock_device(False)
            asyncio.create_task(self.send_ble(packet))
            self.was_locked = False
            self.log("🔒 Screen locked: False")

    def changeEvent(self, event): # pyright: ignore[reportIncompatibleMethodOverride]
        """Intercept minimize event and hide window instead."""
        if event.type() == event.WindowStateChange:
            if self.isMinimized():
                QTimer.singleShot(0, self.hide)
                if not self.already_minimized:
                    self.tray_icon.showMessage(
                        "Minimized to tray",
                        "Your app is still running here.",
                        QIcon(_ICON_PATH),
                        1000
                    )
                    self.already_minimized = True
        super().changeEvent(event)

    def closeEvent(self, event): # pyright: ignore[reportIncompatibleMethodOverride]
        """Handle window close event"""
        if not self._confirm_discard_changes():
            event.ignore()
            return

        logger.info("Application closing...")

        # Stop timers first
        if hasattr(self, 'ping_timer'):
            self.ping_timer.stop()
        if hasattr(self, 'connect_timer'):
            self.connect_timer.stop()
        if hasattr(self, 'device_lock_timer'):
            self.device_lock_timer.stop()

        # Release the WTS session-change subscription if we registered it.
        if getattr(self, "_session_notifications_registered", False):
            try:
                unregister_session_notifications(int(self.winId()))
            except Exception:
                logger.debug("WTS unregister failed", exc_info=True)

        # Drain + stop the background log writer so the rotating file flushes
        # pending records before the process exits.
        global _BLEDECK_LOG_LISTENER
        if _BLEDECK_LOG_LISTENER is not None:
            try:
                _BLEDECK_LOG_LISTENER.stop()
            except Exception:
                logger.debug("log listener stop failed", exc_info=True)
            _BLEDECK_LOG_LISTENER = None

        # Properly disconnect from device if connected
        if self.is_connected and self.ble_client:
            try:
                # Get the current event loop
                try:
                    loop = asyncio.get_running_loop()
                    # Create a task for disconnect and wait for it
                    disconnect_task = loop.create_task(self.disconnect())
                    # Use QTimer to wait for disconnect to complete before closing
                    self._disconnect_task = disconnect_task

                    def check_disconnect():
                        # Poll until disconnect() finishes, but cap the wait so
                        # a wedged BLE stack can never make the window
                        # un-closable. ~10s ceiling > disconnect()'s own 8s
                        # timeout, so the happy path is unchanged; this branch
                        # only fires if that inner bound is ever removed.
                        self._close_polls = getattr(self, "_close_polls", 0) + 1
                        if disconnect_task.done() or self._close_polls > 100:
                            if not disconnect_task.done():
                                logger.warning(
                                    "BLE disconnect did not finish in time — forcing quit"
                                )
                            else:
                                logger.info("BLE disconnect completed")
                            logger.info("Application closed gracefully")
                            # Signal the quit event to terminate the event loop
                            self.quit_event.set()
                            QApplication.quit()
                        else:
                            QTimer.singleShot(100, check_disconnect)

                    QTimer.singleShot(100, check_disconnect)
                    event.ignore()  # Don't close yet, wait for disconnect
                    return

                except RuntimeError:
                    # No event loop running, force cleanup
                    logger.info("No event loop - forcing cleanup")
                    self.is_connected = False
                    self.ble_client = None
            except Exception as e:
                logger.exception("Error during disconnect")
                self.is_connected = False
                self.ble_client = None

        logger.info("Application closed gracefully")
        # Signal the quit event to terminate the event loop
        self.quit_event.set()
        QApplication.quit()
        event.accept()

async def main() -> None:
    _configure_file_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("BLEDeck")
    app.setApplicationDisplayName("BLEDeck")
    app.setWindowIcon(QIcon(_ICON_PATH))

    # Create event for proper shutdown
    quit_event = asyncio.Event()

    # Create and show GUI
    window = BLEDeckGUI(quit_event)
    window.show()

    # Wait for the quit event to be set (when window closes)
    await quit_event.wait()

if __name__ == "__main__":
    try:
        qasync.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted")
    except Exception as e:
        logger.exception("Application error: %s", e)
    finally:
        logger.info("Application terminated")
