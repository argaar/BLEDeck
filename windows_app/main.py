import sys
import asyncio
import qasync
import ctypes
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QLabel, QPushButton, QLineEdit, QComboBox,
                             QGridLayout, QGroupBox, QStatusBar, QTextEdit,
                             QFileDialog, QMessageBox, QCheckBox, QColorDialog,
                             QSlider, QSystemTrayIcon, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QIcon

from ble_client import BleakClient, DEVICE_NAME, CHAR_TX_UUID, CHAR_RX_UUID
from profile_manager import load_profiles, save_profiles
import ble_protocol

class KeyButton(QPushButton):
    def __init__(self, key_id, text):
        super().__init__()
        self.key_id = key_id
        self.key_number = text
        self.key_label = ""
        self.key_color = None  # Store as (r, g, b, brightness)
        self.setFixedSize(80, 80)
        self.is_active = False
        self.update_button_text()
        self.update_button_style()

    def update_button_text(self):
        """Update the button text to show key number and label"""
        if self.key_label:
            # Split long labels with spaces into two lines
            if len(self.key_label) > 10 and ' ' in self.key_label:
                # Find the best split point (closest to middle)
                words = self.key_label.split(' ')
                if len(words) >= 2:
                    self.setText(f"{self.key_number}\n{'\n'.join(words)}")
                else:
                    self.setText(f"{self.key_number}\n{self.key_label}")
            else:
                self.setText(f"{self.key_number}\n{self.key_label}")
        else:
            self.setText(self.key_number)

    def set_label(self, label):
        """Set the label for this key"""
        self.key_label = label
        self.update_button_text()

    def set_color(self, color_str):
        """Set the color from a string like '220,0,0,70'"""
        if color_str:
            try:
                parts = color_str.strip().split(',')
                if len(parts) == 4:
                    # Filter out empty strings and convert to int
                    values = []
                    for p in parts:
                        p = p.strip()
                        if p == '':
                            # Empty value, use default 0
                            values.append(0)
                        else:
                            values.append(int(p))
                    r, g, b, brightness = values
                    # Clamp values to valid ranges
                    r = max(0, min(255, r))
                    g = max(0, min(255, g))
                    b = max(0, min(255, b))
                    brightness = max(0, min(100, brightness))
                    self.key_color = (r, g, b, brightness)
                else:
                    self.key_color = None
            except (ValueError, AttributeError) as e:
                print(f"Warning: Invalid color string '{color_str}': {e}")
                self.key_color = None
        else:
            self.key_color = None
        self.update_button_style()

    def update_button_style(self):
        """Update the button stylesheet based on color and active state"""
        if self.is_active:
            # Active state - use green
            self.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    border: 2px solid #45a049;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 9px;
                    color: white;
                }
            """)
        elif self.key_color:
            # Use the custom color with brightness
            r, g, b, bri = self.key_color
            # Apply brightness (0-100) as a brightness factor
            brightness = bri / 100.0
            r_adj = int(r * brightness)
            g_adj = int(g * brightness)
            b_adj = int(b * brightness)

            # Calculate text color based on brightness (dark text for light backgrounds)
            text_color = "black" if (r_adj + g_adj + b_adj) > 382 else "white"

            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgb({r_adj}, {g_adj}, {b_adj});
                    border: 2px solid rgb({max(0, r_adj-20)}, {max(0, g_adj-20)}, {max(0, b_adj-20)});
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 9px;
                    color: {text_color};
                }}
                QPushButton:hover {{
                    background-color: rgb({min(255, r_adj+20)}, {min(255, g_adj+20)}, {min(255, b_adj+20)});
                }}
            """)
        else:
            # Default gray style
            self.setStyleSheet("""
                QPushButton {
                    background-color: #f0f0f0;
                    border: 2px solid #ccc;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 9px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
            """)

    def set_active(self, active):
        self.is_active = active
        self.update_button_style()

class BLEDeckGUI(QMainWindow):
    def __init__(self, quit_event):
        super().__init__()
        self.setWindowTitle("BLEDeck Control Panel")
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon("icon.ico"))
        
        # Create tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.ico"))  # put your own icon path here
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
        self.device_lock_timer = QTimer()
        self.device_lock_timer.timeout.connect(self.screen_locked)
        #self.device_lock_timer.start(5000)

        # Auto-connect timer - start disabled, can be enabled via UI
        self.connect_timer = QTimer()
        self.connect_timer.timeout.connect(self.auto_connect)
        # Don't start auto-connect by default to prevent connection loops

        # Last ping time for connection health
        self.last_ping_response = 0
        self.ping_timeout_count = 0

        asyncio.create_task(self.connect())
    
    def setup_ui(self):
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
    
    def create_top_panel(self):
        group = QGroupBox("Connection & Profile")
        layout = QHBoxLayout(group)
        
        # Connection status
        self.status_label = QLabel("Status: Disconnected")
        layout.addWidget(self.status_label)
        
        # Connect button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn)
        
        # Auto-reconnect checkbox
        self.auto_reconnect_cb = QCheckBox("Auto-reconnect")
        self.auto_reconnect_cb.stateChanged.connect(self.toggle_auto_reconnect)
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
    
    def create_key_panel(self):
        group = QGroupBox("Key Layout")
        layout = QGridLayout(group)
        
        # Create 16 key buttons in a 4x4 grid
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
    
    def create_action_panel(self):
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
    
    def restore_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def on_tray_icon_activated(self, reason):
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
        else:
            # As a final fallback compare numeric value for DoubleClick (often 3)
            try:
                if int(reason) == 3:  
                    self.restore_from_tray()
            except Exception:
                pass

    def update_profile_combo(self):
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
    
    def load_current_profile(self):
        if self.current_profile_index < len(self.profiles):
            profile = self.profiles[self.current_profile_index]
            self.key_configs = profile.get('keys', {})

            # Convert string keys to int keys
            if isinstance(list(self.key_configs.keys())[0] if self.key_configs else None, str):
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
    
    def on_profile_changed(self, index):
        self.current_profile_index = index
        self.load_current_profile()
        if self.is_connected:
            self.log(f"📁 Profile changed to: {self.profiles[index].get('name', f'Profile {index}')}")
            asyncio.create_task(self.send_profile_change())
    
    def on_key_selected(self, key_id):
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
            except AttributeError:
                self.log(f"Color code: '{color_str}' is invalid")

    def on_label_changed(self, text):
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['label'] = text.strip()
            # Update button label
            self.key_buttons[self.selected_key_id].set_label(text.strip())

    def on_color_changed(self, text):
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['color'] = text.strip()
            # Update button color
            self.key_buttons[self.selected_key_id].set_color(text.strip())
            # Send notification to change single RGB on BLEDeck
            self.send_rgb(color=text.strip())

    def on_command_changed(self, text):
        if self.selected_key_id is not None:
            self.ensure_key_data_exists()
            self.key_configs[self.selected_key_id]['command'] = text.strip()

    def ensure_key_data_exists(self):
        """Ensure the selected key has a dictionary entry"""
        if self.selected_key_id is not None:
            if self.selected_key_id not in self.key_configs:
                self.key_configs[self.selected_key_id] = {'label': '', 'color': '', 'command': ''}

    def open_color_picker(self):
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
            except AttributeError:
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

    def on_brightness_changed(self, value):
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
                except AttributeError:
                    self.log(f"Color code: {color_str}' is invalid")
    
    def create_new_profile(self):
        """Create a new empty profile"""
        # Create a new profile with a default name
        profile_count = len(self.profiles) + 1
        new_profile = {
            "name": f"New Profile {profile_count}",
            "keys": {
                "0": {"label": "", "color": "", "command": ""},
                "1": {"label": "", "color": "", "command": ""},
                "2": {"label": "", "color": "", "command": ""},
                "3": {"label": "", "color": "", "command": ""},
                "4": {"label": "", "color": "", "command": ""},
                "5": {"label": "", "color": "", "command": ""},
                "6": {"label": "", "color": "", "command": ""},
                "7": {"label": "", "color": "", "command": ""},
                "8": {"label": "", "color": "", "command": ""},
                "9": {"label": "", "color": "", "command": ""},
                "10": {"label": "", "color": "", "command": ""},
                "11": {"label": "", "color": "", "command": ""},
                "12": {"label": "", "color": "", "command": ""},
                "13": {"label": "", "color": "", "command": ""},
                "14": {"label": "", "color": "", "command": ""},
                "15": {"label": "", "color": "", "command": ""}
            }
        }

        # Add to profiles list
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

    def save_current_profile(self):
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
            asyncio.create_task(self.sync_single_profile(self.current_profile_index))
    
    async def sync_single_profile(self, profile_index):
        """Sync a single profile name to the device - with binary protocol we sync all"""
        # With the binary protocol, we just resync all profiles
        await self.synchronize_profiles_to_device()
    
    def sync_profile_from_device(self, device_profile_index):
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
    
    def send_rgb(self, color=None):
        """Send RGB color(s) to device using binary protocol"""
        if color:
            # Send single key color
            try:
                parts = color.strip().split(',')
                if len(parts) == 4:
                    # Parse and validate each value
                    values = []
                    for p in parts:
                        p = p.strip()
                        if p == '':
                            values.append(0)
                        else:
                            values.append(int(p))
                    r, g, b, w = values

                    # Clamp to valid ranges
                    r = max(0, min(255, r))
                    g = max(0, min(255, g))
                    b = max(0, min(255, b))
                    w = max(0, min(100, w))

                    packet = ble_protocol.set_rgb_key(
                        self.current_profile_index,
                        self.selected_key_id,
                        r, g, b, w
                    )
                    asyncio.create_task(self.send_ble(packet))
                else:
                    self.log(f"⚠️ Invalid color format (expected R,G,B,W): {color}")
            except (ValueError, IndexError) as e:
                self.log(f"⚠️ Error parsing color '{color}': {e}")
                return
        else:
            # Send all 16 key colors
            rgbw_list = []
            profile_keys = self.profiles[self.current_profile_index].get("keys", {})

            # Build list of 16 RGBW tuples in order (0-15)
            for i in range(16):
                key_data = profile_keys.get(str(i), {})
                color_str = key_data.get('color', '0,0,0,0')

                try:
                    if color_str:
                        parts = color_str.strip().split(',')
                        if len(parts) == 4:
                            # Parse and validate each value
                            values = []
                            for p in parts:
                                p = p.strip()
                                if p == '':
                                    values.append(0)
                                else:
                                    values.append(int(p))
                            r, g, b, w = values

                            # Clamp to valid ranges
                            r = max(0, min(255, r))
                            g = max(0, min(255, g))
                            b = max(0, min(255, b))
                            w = max(0, min(100, w))

                            rgbw_list.append((r, g, b, w))
                        else:
                            rgbw_list.append((0, 0, 0, 0))
                    else:
                        rgbw_list.append((0, 0, 0, 0))
                except (ValueError, IndexError) as e:
                    self.log(f"⚠️ Invalid color for key {i}: '{color_str}' - using default")
                    rgbw_list.append((0, 0, 0, 0))

            packet = ble_protocol.set_all_rgb_keys(rgbw_list)
            asyncio.create_task(self.send_ble(packet))

    def delete_current_profile(self):
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
    
    def browse_for_executable(self):
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
    
    def toggle_connection(self):
        if self.is_connected:
            self.log("🔌 Manual disconnect requested")
            asyncio.create_task(self.manual_disconnect())
        else:
            self.log("🔌 Manual connect requested") 
            asyncio.create_task(self.connect())
    
    async def manual_disconnect(self):
        # Stop auto-connect when manually disconnecting
        self.connect_timer.stop()
        await self.disconnect()
        # Only restart auto-connect if checkbox is enabled
        if self.auto_reconnect_cb.isChecked():
            QTimer.singleShot(30000, self.connect_timer.start)  # 30 second delay
    
    def toggle_auto_reconnect(self, checked):
        if checked:
            self.log("🔄 Auto-reconnect enabled")
            if not self.is_connected:
                self.connect_timer.start(10000)  # Start trying to connect
        else:
            self.log("🔄 Auto-reconnect disabled")
            self.connect_timer.stop()
    
    async def connect(self):
        try:
            from bleak import BleakScanner
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
            self.ble_client = BleakClient(target.address)
            
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
            import time
            self.last_ping_response = time.time()
            self.ping_timeout_count = 0
            
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
    
    async def cleanup_failed_connection(self):
        self.is_connected = False
        if self.ble_client:
            await self.ble_client.disconnect()
        self.ble_client = None
    
    async def disconnect(self): # pyright: ignore[reportIncompatibleMethodOverride]
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
        self.connect_btn.setText("Connect")
        self.status_bar.showMessage("Disconnected")
        
        # Reset key states
        for btn in self.key_buttons.values():
            btn.set_active(False)
        
        self.log("✅ Disconnected")
    
    async def send_ble(self, data):
        """Send binary data to BLE device"""
        if not self.ble_client or not self.is_connected:
            return

        try:
            # Convert to bytes if needed (for backwards compatibility)
            if isinstance(data, str):
                data = data.encode()

            # Check if client is still valid before sending
            if not self.ble_client.is_connected:
                self.log("⚠️ Cannot send - not connected")
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
            self.log(f"⚠️ Send timeout (keeping connection)")
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
    
    async def synchronize_profiles_to_device(self):
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
    
    async def send_profile_change(self):
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

            try:
                if color_str:
                    parts = color_str.strip().split(',')
                    if len(parts) == 4:
                        # Parse and validate each value
                        values = []
                        for p in parts:
                            p = p.strip()
                            if p == '':
                                values.append(0)
                            else:
                                values.append(int(p))
                        r, g, b, w = values

                        # Clamp to valid ranges
                        r = max(0, min(255, r))
                        g = max(0, min(255, g))
                        b = max(0, min(255, b))
                        w = max(0, min(100, w))

                        rgbw_list.append((r, g, b, w))
                    else:
                        rgbw_list.append((0, 0, 0, 0))
                else:
                    rgbw_list.append((0, 0, 0, 0))
            except (ValueError, IndexError):
                rgbw_list.append((0, 0, 0, 0))

        # Send CHANGE_PROFILE command with profile index (1-based), name, and colors
        packet = ble_protocol.change_profile(
            self.current_profile_index + 1,  # Device uses 1-based indexing
            profile_name,
            rgbw_list
        )
        await self.send_ble(packet)
    
    def send_ping(self):
        if self.is_connected:
            import time
            self.log(f"🏓 Sending ping (last response: {int(time.time() - self.last_ping_response)}s ago)")
            packet = ble_protocol.keep_alive()
            asyncio.create_task(self.send_ble(packet))
    
    def auto_connect(self):
        if not self.is_connected:
            asyncio.create_task(self.connect())
    
    async def handle_notification(self, sender, data):
        """Handle incoming binary protocol packets from device"""
        try:
            # Check if we're still connected
            if not self.is_connected:
                return

            # Any message is a sign of life - update connection health
            import time
            self.last_ping_response = time.time()
            self.ping_timeout_count = 0

            # Log raw data (with opcode hint)
            opcode_hint = ""
            if len(data) >= 2:
                op = data[1]
                op_names = {0x81:"PONG", 0x82:"PROFILE", 0x83:"BUTTON", 0x84:"KEY"}
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

            else:
                self.log(f"⚠️ Unknown opcode: 0x{opcode:02X}")

        except Exception as e:
            self.log(f"❌ Notification error: {str(e)}")
    
    async def execute_key_action(self, key_id):
        """Execute action for current app profile"""
        await self.execute_key_action_for_profile(key_id, self.current_profile_index)
    
    async def execute_key_action_for_profile(self, key_id, profile_index):
        """Execute action for a specific profile"""
        if profile_index is None or profile_index >= len(self.profiles):
            self.log(f"⚠️ Invalid profile index: {profile_index}")
            return

        profile = self.profiles[profile_index]
        profile_keys = profile.get('keys', {})

        # Convert string keys to int if needed
        if isinstance(list(profile_keys.keys())[0] if profile_keys else None, str):
            profile_keys = {int(k): v for k, v in profile_keys.items()}

        key_data = profile_keys.get(key_id)
        profile_name = profile.get('name', f'Profile {profile_index}')

        if key_data:
            try:
                # Extract command from the key data
                command = key_data.get('command', '')

                if command:
                    import subprocess
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

    async def _check_command_errors(self, process, command, profile_name):
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
    
    def char_to_key_id(self, key_char):
        """Convert key character to key ID (0-15)"""
        # Key mapping: 0-9 = IDs 0-9, A-F = IDs 10-15
        key_mapping = {
            '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
            'A': 10, 'B': 11, 'C': 12, 'D': 13, 'E': 14, 'F': 15
        }
        return key_mapping.get(key_char)
    
    def key_id_to_char(self, key_id):
        """Convert key ID to character"""
        if 0 <= key_id <= 9:
            return str(key_id)
        elif 10 <= key_id <= 15:
            return chr(ord('A') + key_id - 10)  # 10->A, 11->B, etc.
        return None
    
    def log(self, message):
        self.log_text.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum()) # pyright: ignore[reportOptionalMemberAccess]
    
    def screen_locked(self):
        """
        Find if the user has locked their screen.
        """
        if self.is_connected:
            user32 = ctypes.windll.User32
            is_locked = (user32.GetForegroundWindow() % 10 == 0)
            packet = ble_protocol.lock_device(is_locked)
            asyncio.create_task(self.send_ble(packet))

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
        print("Application closing...")

        # Stop timers first
        if hasattr(self, 'ping_timer'):
            self.ping_timer.stop()
        if hasattr(self, 'connect_timer'):
            self.connect_timer.stop()
        if hasattr(self, 'device_lock_timer'):
            self.connect_timer.stop()

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
                            print("BLE disconnect completed")
                            print("Application closed gracefully")
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
                    print("No event loop - forcing cleanup")
                    self.is_connected = False
                    self.ble_client = None
            except Exception as e:
                print(f"Error during disconnect: {e}")
                self.is_connected = False
                self.ble_client = None

        print("Application closed gracefully")
        # Signal the quit event to terminate the event loop
        self.quit_event.set()
        QApplication.quit()
        event.accept()

async def main():
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
        print("Application interrupted")
    except Exception as e:
        print(f"Application error: {e}")
    finally:
        print("Application terminated")
