import sys
import asyncio
import logging
import subprocess
import time
import qasync
import ctypes
from typing import Any
from bleak import BleakClient, BleakGATTCharacteristic, BleakScanner
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QLabel, QPushButton, QLineEdit, QComboBox,
                             QGridLayout, QGroupBox, QStatusBar, QTextEdit,
                             QFileDialog, QMessageBox, QCheckBox, QColorDialog,
                             QSlider, QSystemTrayIcon, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QIcon

from ble_client import DEVICE_NAME, CHAR_TX_UUID, CHAR_RX_UUID
from key_button import KeyButton
from profile_manager import load_profiles, save_profiles, create_new_profile
import ble_protocol

logger = logging.getLogger(__name__)


class BLEDeckGUI(QMainWindow):
    def __init__(self, quit_event: asyncio.Event) -> None:
        super().__init__()
        self.setWindowTitle("BLEDeck Control Panel")
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon("icon.ico"))
        
        # Create tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.ico"))
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

        # Data
        self.profiles = load_profiles()
        self.key_buttons = {}
        self.key_configs = {}

        # Setup UI
        self.setup_ui()
        self.load_current_profile()

        # Setup timer for periodic ping
        self.ping_timer = QTimer()
        self.ping_timer.timeout.connect(self.send_ping)

        # Setup timer to detect locked workstation
        self.was_locked = False
        self.device_lock_timer = QTimer()
        self.device_lock_timer.timeout.connect(self.screen_locked)
        self.device_lock_timer.start(2500)

        # Auto-connect timer - start disabled, can be enabled via UI
        self.connect_timer = QTimer()
        self.connect_timer.timeout.connect(self.auto_connect)
        # Don't start auto-connect by default to prevent connection loops

        # Last ping time for connection health
        self.last_ping_response = time.time()

        asyncio.create_task(self.connect())
    
    def setup_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Top panel - Connection and Profile
        top_panel = self.create_top_panel()
        layout.addWidget(top_panel)
        
        # Middle panel - Key Grid
        key_panel = self.create_key_panel()
        layout.addWidget(key_panel)
        
        # Bottom panel - Action Configuration
        action_panel = self.create_action_panel()
        layout.addWidget(action_panel)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Disconnected")
    
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
        layout.addWidget(self.profile_name_input)

        # New profile button
        new_btn = QPushButton("New Profile")
        new_btn.clicked.connect(self.create_new_profile)
        new_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        layout.addWidget(new_btn)

        # Save profile button
        save_btn = QPushButton("Save Profile")
        save_btn.clicked.connect(self.save_current_profile)
        layout.addWidget(save_btn)

        # Delete profile button
        delete_btn = QPushButton("Delete Profile")
        delete_btn.clicked.connect(self.delete_current_profile)
        delete_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
        layout.addWidget(delete_btn)

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
            btn.clicked.connect(lambda checked, key_id=i: self.on_key_selected(key_id))
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

        # Color picker button
        self.color_picker_btn = QPushButton("Pick Color")
        self.color_picker_btn.clicked.connect(self.open_color_picker)
        self.color_picker_btn.setMaximumWidth(100)
        color_layout.addWidget(self.color_picker_btn)

        layout.addLayout(color_layout)

        # brightness slider
        bri_layout = QHBoxLayout()
        bri_layout.addWidget(QLabel("Brightness:"))
        self.brightness_slider = QSlider(Qt.Horizontal) # pyright: ignore[reportAttributeAccessIssue]
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

        # Command input
        command_layout = QHBoxLayout()
        command_layout.addWidget(QLabel("Command:"))
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Enter command or action...")
        self.command_input.textChanged.connect(self.on_command_changed)
        command_layout.addWidget(self.command_input)

        # Browse button for executables
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_for_executable)
        browse_btn.setMaximumWidth(80)
        command_layout.addWidget(browse_btn)

        layout.addLayout(command_layout)

        # Command examples
        examples = QLabel("Examples: notepad.exe, calc.exe, explorer.exe, cmd /c echo Hello")
        examples.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(examples)

        # Debug log
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(100)
        self.log_text.setPlaceholderText("Debug log will appear here...")
        layout.addWidget(self.log_text)

        self.selected_key_id = None

        return group
    
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
    
    def on_key_selected(self, key_id) -> None:
        self.selected_key_id = key_id
        key_name = self.key_id_to_char(key_id)
        self.selected_key_label.setText(f"Selected Key: {key_name} (ID: {key_id})")

        # Load existing data for this key
        key_data = self.key_configs.get(key_id, {})
        self.label_input.setText(key_data.get('label', ''))
        self.color_input.setText(key_data.get('color', ''))
        self.command_input.setText(key_data.get('command', ''))

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

    def on_color_changed(self, text) -> None:
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['color'] = text.strip()
            # Update button color
            self.key_buttons[self.selected_key_id].set_color(text.strip())
            # Send notification to change single RGB on BLEDeck
            self.send_rgb(color=text.strip())

    def on_command_changed(self, text) -> None:
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['command'] = text.strip()

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

        self.log(f"Created new profile: {new_profile['name']}")
        self.log("Remember to save it before closing or switching profile")

    def save_current_profile(self) -> None:
        if self.current_profile_index < len(self.profiles):
            profile = self.profiles[self.current_profile_index]
        else:
            profile = {}
            self.profiles.append(profile)

        old_name = profile.get('name', f'Profile {self.current_profile_index}')
        new_name = self.profile_name_input.text() or f'Profile {self.current_profile_index}'

        profile['name'] = new_name
        # Convert int keys to string keys for JSON serialization, filtering out empty keys
        filtered_keys = {}
        for k, v in self.key_configs.items():
            # Only save if at least command is not empty
            if v.get('command', '').strip():
                filtered_keys[str(k)] = v

        profile['keys'] = filtered_keys

        save_profiles(self.profiles)
        self.update_profile_combo()
        self.log("Profile saved successfully")

        # If profile name changed and we're connected, sync with device
        if self.is_connected and old_name != new_name:
            self.log(f"📁 Profile name changed: '{old_name}' → '{new_name}'")
            asyncio.create_task(self.synchronize_profiles_to_device())
    
    def sync_profile_from_device(self, device_profile_index: int) -> None:
        """Update app profile to match device profile (called when device encoder changes profile)"""
        self.current_profile_index = device_profile_index
        
        # Update combo box without triggering the change event (to avoid sending back to device)
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(device_profile_index)
        self.profile_combo.blockSignals(False)
        
        # Load the profile data (actions, name, etc.)
        self.load_current_profile()
        
        profile_name = self.profiles[device_profile_index].get('name', f'Profile {device_profile_index}')
        self.log(f"✅ App profile synced to: '{profile_name}'")
        if self.isMinimized():
            self.tray_icon.showMessage(
                "Profile Changed",
                f"'{profile_name}' is the profile now in use.",
                QIcon("icon.ico"),
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

    def send_rgb(self, color: str | None = None) -> None:
        """Send RGB color(s) to device using binary protocol"""
        if color:
            r, g, b, w = self.parse_color_string(color)
            packet = ble_protocol.set_rgb_key(
                        self.selected_key_id,
                        r, g, b, w
                    )
        else:
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
            
            # Save and update UI
            save_profiles(self.profiles)
            self.update_profile_combo()
            self.load_current_profile()
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
            QTimer.singleShot(30000, lambda: self.connect_timer.start(10000))  # 30 second delay
    
    def toggle_auto_reconnect(self, checked: bool) -> None:
        if checked:
            self.log("🔄 Auto-reconnect enabled")
            if not self.is_connected:
                self.connect_timer.start(10000)  # Start trying to connect
        else:
            self.log("🔄 Auto-reconnect disabled")
            self.connect_timer.stop()
    
    async def connect(self) -> None:
        if self._connecting or self.is_connected:
            return
        self._connecting = True
        try:
            self.log("Scanning for BLEDeck...")
            
            # Scan with timeout
            devices = await asyncio.wait_for(
                BleakScanner.discover(timeout=8.0), 
                timeout=10.0
            )
            
            target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
            
            if not target:
                self.log("❌ Device not found")
                return
            
            self.log(f"Found device: {target.name} ({target.address})")
            self.ble_client = BleakClient(target.address, disconnected_callback=self._on_ble_disconnected)
            
            # Connect with timeout
            await asyncio.wait_for(self.ble_client.connect(), timeout=10.0)
            
            # Verify connection
            if not self.ble_client.is_connected:
                raise Exception("Connection failed after connect call")
            
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
            
            # Send initial ping and synchronize profiles
            packet = ble_protocol.keep_alive()
            await self.send_ble(packet)
            await asyncio.sleep(0.5)  # Small delay
            await self.synchronize_profiles_to_device()
            await asyncio.sleep(0.5)  # Small delay between operations
            await self.send_profile_change()
            
            # Start timers
            self.ping_timer.start(30000)  # Ping every 30 seconds
            
            self.log(f"✅ Connected to {target.address}")
            
        except asyncio.TimeoutError:
            self.log("❌ Connection timeout")
            await self.cleanup_failed_connection()
        except Exception as e:
            self.log(f"❌ Connection failed: {str(e)}")
            await self.cleanup_failed_connection()
        finally:
            self._connecting = False
    
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
                op_names = {0x01:"PING", 0x02:"CHG_PROF", 0x03:"SYNC", 0x04:"RGB_KEY", 0x05:"RGB_ALL", 0x06:"LOCK"}
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

            # Log raw data (with opcode hint)
            opcode_hint = ""
            if len(data) >= 2:
                op = data[1]
                op_names = {0x81:"PONG", 0x82:"PROFILE", 0x83:"BUTTON", 0x84:"KEY", 0x85:"BATTERY"}
                opcode_hint = f" [{op_names.get(op, f'0x{op:02X}')}]"
            self.log(f"← {data.hex()}{opcode_hint}")

            # Parse binary packet
            try:
                opcode, payload = ble_protocol.BLEPacket.parse(data)
            except ValueError as e:
                self.log(f"⚠️ Invalid packet: {e}")
                return

            # Handle different opcodes
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
                key_char = key_char.upper()

                # Convert key character to key ID (0-15)
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
                self.log(f"🔘 Button pressed: '{button_name}' on profile {profile_index}")
                # You can add button-specific handling here if needed

            elif opcode == ble_protocol.OP_BATTERY_STATUS:
                percent = ble_protocol.parse_battery_status(payload)
                if percent == 255:
                    self.log("🔋 Battery: USB / no battery")
                else:
                    self.log(f"🔋 Battery: {percent}%")
                self.update_battery_display(percent)

            else:
                self.log(f"⚠️ Unknown opcode: 0x{opcode:02X}")

        except Exception:
            logger.exception("❌ Notification handler error")
    
    async def execute_key_action_for_profile(self, key_id: int, profile_index: int) -> None:
        """Execute action for a specific profile"""
        if profile_index is None or profile_index >= len(self.profiles):
            self.log(f"⚠️ Invalid profile index: {profile_index}")
            return

        profile = self.profiles[profile_index]
        profile_keys = profile.get('keys', {})

        # Convert string keys to int if needed
        if profile_keys and isinstance(next(iter(profile_keys.keys())), str):
            profile_keys = {int(k): v for k, v in profile_keys.items()}

        key_data = profile_keys.get(key_id)
        profile_name = profile.get('name', f'Profile {profile_index}')

        if key_data:
            try:
                # Extract command from the key data
                command = key_data.get('command', '')

                if command:
                    # Execute the command with error capture
                    # Use CREATE_NO_WINDOW flag on Windows to prevent console windows
                    startupinfo = None
                    if sys.platform == 'win32':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                    process = subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=startupinfo,
                        text=True
                    )

                    self.log(f"⚡ Executed from '{profile_name}': {command}")

                    # Check for errors in a background task
                    asyncio.create_task(self._check_command_errors(process, command, profile_name))
                else:
                    self.log(f"⚠️ No command defined for key {key_id} in profile '{profile_name}'")
            except Exception as e:
                self.log(f"❌ Action failed from '{profile_name}': {str(e)}")
        else:
            self.log(f"⚠️ No action defined for key {key_id} in profile '{profile_name}'")

    async def _check_command_errors(self, process: Any, command: str, profile_name: str) -> None:
        """Check if a command produced errors"""
        try:
            # Wait for the process to complete (with timeout)
            stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(process.communicate),
                timeout=5.0
            )

            # Check return code and stderr
            if process.returncode != 0 and stderr:
                # Extract meaningful error message
                error_lines = stderr.strip().split('\n')
                # Get the most relevant error line (usually the last non-empty one)
                error_msg = next((line for line in reversed(error_lines) if line.strip()), stderr.strip())
                self.log(f"❌ Command error from '{profile_name}': {error_msg}")
                self.log(f"   Command: {command}")
            elif process.returncode != 0:
                self.log(f"⚠️ Command exited with code {process.returncode} from '{profile_name}'")

        except asyncio.TimeoutError:
            # Command is still running after timeout - this is fine, it's probably a long-running process
            pass
        except Exception as e:
            self.log(f"⚠️ Error checking command status: {str(e)}")
    
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
        self.log_text.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum()) # pyright: ignore[reportOptionalMemberAccess]
    
    def screen_locked(self) -> None:
        """
        Find if the user has locked their screen.
        """
        if self.is_connected:
            user32 = ctypes.windll.User32
            # Detect if the workstation is locked (Windows)          
            # If the foreground window is 0, the screen is locked
            is_locked = user32.GetForegroundWindow() == 0
            
            if is_locked:
                packet = ble_protocol.lock_device(True)
                asyncio.create_task(self.send_ble(packet))
                self.was_locked = True
                self.log("🔒 Screen locked: True")
            elif self.was_locked and not is_locked:
                packet = ble_protocol.lock_device(False)
                asyncio.create_task(self.send_ble(packet))
                self.was_locked = False
                self.log("🔒 Screen locked: False")
            else:
                pass

    def changeEvent(self, event): # pyright: ignore[reportIncompatibleMethodOverride]
        """Intercept minimize event and hide window instead."""
        if event.type() == event.WindowStateChange:
            if self.isMinimized():
                QTimer.singleShot(0, self.hide)
                if not self.already_minimized:
                    self.tray_icon.showMessage(
                        "Minimized to tray",
                        "Your app is still running here.",
                        QIcon("icon.ico"),
                        1000
                    )
                    self.already_minimized = True
        super().changeEvent(event)

    def closeEvent(self, event): # pyright: ignore[reportIncompatibleMethodOverride]
        """Handle window close event"""
        logger.info("Application closing...")

        # Stop timers first
        if hasattr(self, 'ping_timer'):
            self.ping_timer.stop()
        if hasattr(self, 'connect_timer'):
            self.connect_timer.stop()
        if hasattr(self, 'device_lock_timer'):
            self.device_lock_timer.stop()

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
                        if disconnect_task.done():
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
    app = QApplication(sys.argv)
    app.setApplicationName("BLEDeck")
    app.setApplicationDisplayName("BLEDeck")
    app.setWindowIcon(QIcon("icon.ico"))

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
