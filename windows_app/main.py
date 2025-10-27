import sys
import asyncio
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QLabel, QPushButton, QLineEdit, QComboBox, 
                             QGridLayout, QGroupBox, QStatusBar, QFrame, QTextEdit,
                             QFileDialog, QMessageBox, QCheckBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, pyqtSlot
from PyQt5.QtGui import QPalette, QFont
import qasync
from qasync import QEventLoop

from ble_client import BleakClient, DEVICE_NAME, SERVICE_UUID, CHAR_TX_UUID, CHAR_RX_UUID
from profile_manager import load_profiles, save_profiles


class KeyButton(QPushButton):
    def __init__(self, key_id, text):
        super().__init__(text)
        self.key_id = key_id
        self.setFixedSize(60, 60)
        self.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 2px solid #ccc;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        self.is_active = False
    
    def set_active(self, active):
        self.is_active = active
        if active:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    border: 2px solid #45a049;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 14px;
                    color: white;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #f0f0f0;
                    border: 2px solid #ccc;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
            """)


class BLEDeckGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BLE Deck Control Panel")
        self.setGeometry(100, 100, 800, 600)
        
        # BLE connection state
        self.ble_client = None
        self.is_connected = False
        self.current_profile_index = 0
        
        # Data
        self.profiles = load_profiles()
        self.key_buttons = {}
        self.key_actions = {}
        
        # Setup UI
        self.setup_ui()
        self.load_current_profile()
        
        # Setup timer for periodic ping
        self.ping_timer = QTimer()
        self.ping_timer.timeout.connect(self.send_ping)
        
        # Auto-connect timer - start disabled, can be enabled via UI
        self.connect_timer = QTimer()
        self.connect_timer.timeout.connect(self.auto_connect)
        # Don't start auto-connect by default to prevent connection loops
        
        # Connection monitoring - disabled for now to prevent false disconnects
        self.connection_check_timer = QTimer()
        self.connection_check_timer.timeout.connect(self.check_connection_health)
        
        # Last ping time for connection health
        self.last_ping_response = 0
        self.ping_timeout_count = 0
    
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
        group = QGroupBox("Key Layout (0-9, A-F)")
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
        
        # Action input
        action_layout = QHBoxLayout()
        action_layout.addWidget(QLabel("Action:"))
        self.action_input = QLineEdit()
        self.action_input.setPlaceholderText("Enter command or action...")
        self.action_input.textChanged.connect(self.on_action_changed)
        action_layout.addWidget(self.action_input)
        
        # Browse button for executables
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_for_executable)
        browse_btn.setMaximumWidth(80)
        action_layout.addWidget(browse_btn)
        
        layout.addLayout(action_layout)
        
        # Action examples
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
    
    def update_profile_combo(self):
        self.profile_combo.clear()
        for i, profile in enumerate(self.profiles):
            name = profile.get('name', f'Profile {i}')
            self.profile_combo.addItem(name)
    
    def load_current_profile(self):
        if self.current_profile_index < len(self.profiles):
            profile = self.profiles[self.current_profile_index]
            self.key_actions = profile.get('actions', {})
            
            # Convert string keys to int keys
            if isinstance(list(self.key_actions.keys())[0] if self.key_actions else None, str):
                self.key_actions = {int(k): v for k, v in self.key_actions.items()}
            
            # Update profile name input
            profile_name = profile.get('name', f'Profile {self.current_profile_index}')
            self.profile_name_input.setText(profile_name)
            
            # Update profile combo
            self.profile_combo.setCurrentIndex(self.current_profile_index)
    
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
        
        # Load existing action for this key
        action = self.key_actions.get(key_id, "")
        self.action_input.setText(action)
    
    def on_action_changed(self, text):
        if self.selected_key_id is not None:
            if text.strip():
                self.key_actions[self.selected_key_id] = text.strip()
            elif self.selected_key_id in self.key_actions:
                del self.key_actions[self.selected_key_id]
    
    def save_current_profile(self):
        if self.current_profile_index < len(self.profiles):
            profile = self.profiles[self.current_profile_index]
        else:
            profile = {}
            self.profiles.append(profile)
        
        old_name = profile.get('name', f'Profile {self.current_profile_index}')
        new_name = self.profile_name_input.text() or f'Profile {self.current_profile_index}'
        
        profile['name'] = new_name
        profile['actions'] = self.key_actions.copy()
        
        save_profiles(self.profiles)
        self.update_profile_combo()
        self.log("Profile saved successfully")
        
        # If profile name changed and we're connected, sync with device
        if self.is_connected and old_name != new_name:
            self.log(f"📁 Profile name changed: '{old_name}' → '{new_name}'")
            asyncio.create_task(self.sync_single_profile(self.current_profile_index))
    
    async def sync_single_profile(self, profile_index):
        """Sync a single profile name to the device"""
        if profile_index < len(self.profiles):
            profile_name = self.profiles[profile_index].get('name', f'Profile {profile_index}')
            msg = f"PROFILE_NAME:{profile_index}|{profile_name}"
            await self.send_ble(msg)
    
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
            self.action_input.setText(file_path)
    
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
            await self.send_ble("PING")
            await asyncio.sleep(0.5)  # Small delay
            await self.synchronize_profiles_to_device()
            await asyncio.sleep(0.5)  # Small delay between operations
            await self.send_profile_change()
            
            # Start timers
            self.ping_timer.start(30000)  # Ping every 30 seconds (less aggressive)
            # Disabled connection health check to prevent false disconnects
            # self.connection_check_timer.start(5000)
            
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
            try:
                await self.ble_client.disconnect()
            except:
                pass
        self.ble_client = None
    
    async def disconnect(self):
        self.log("🔌 Starting disconnect process...")
        
        # Stop timers first
        self.ping_timer.stop()
        self.connection_check_timer.stop()
        
        if self.ble_client:
            try:
                # Always try to disconnect, even if is_connected is unreliable
                self.log("🔌 Calling BLE disconnect...")
                await asyncio.wait_for(self.ble_client.disconnect(), timeout=8.0)
                self.log("🔌 BLE disconnect completed")
            except asyncio.TimeoutError:
                self.log("⚠️ Disconnect timeout - forcing cleanup")
            except Exception as e:
                self.log(f"⚠️ Disconnect error: {e}")
        
        self.is_connected = False
        self.ble_client = None
        
        # Update UI
        self.status_label.setText("Status: Disconnected")
        self.connect_btn.setText("Connect")
        self.status_bar.showMessage("Disconnected")
        
        # Reset key states
        for btn in self.key_buttons.values():
            btn.set_active(False)
        
        self.log("✅ Disconnected")
    
    async def send_ble(self, msg):
        if not self.ble_client or not self.is_connected:
            return
            
        try:
            # Send with timeout but don't disconnect on timeout (could be temporary)
            await asyncio.wait_for(
                self.ble_client.write_gatt_char(CHAR_RX_UUID, msg.encode()), 
                timeout=5.0
            )
            self.log(f"→ {msg}")
            
        except asyncio.TimeoutError:
            self.log(f"⚠️ Send timeout: {msg} (keeping connection)")
            # Don't disconnect on timeout - might be temporary
        except Exception as e:
            # Only disconnect on actual BLE errors (device gone, etc.)
            if "not connected" in str(e).lower() or "device" in str(e).lower():
                self.log(f"❌ Device disconnected: {str(e)}")
                await self.disconnect()
            else:
                self.log(f"⚠️ Send failed: {str(e)} (keeping connection)")
    
    async def synchronize_profiles_to_device(self):
        """Send all profile names to the device"""
        self.log(f"📁 Synchronizing {len(self.profiles)} profiles to device...")
        
        for i, profile in enumerate(self.profiles):
            profile_name = profile.get('name', f'Profile {i}')
            # Format: PROFILE_NAME:index|name
            msg = f"PROFILE_NAME:{i}|{profile_name}"
            await self.send_ble(msg)
            await asyncio.sleep(0.1)  # Small delay between profile sends
        
        self.log("📁 Profile synchronization complete")
    
    async def send_profile_change(self):
        msg = f"SET_PROFILE:{self.current_profile_index}"
        await self.send_ble(msg)
        self.log(f"📁 Set device profile to: {self.current_profile_index}")
    
    def send_ping(self):
        if self.is_connected:
            import time
            self.log(f"🏓 Sending ping (last response: {int(time.time() - self.last_ping_response)}s ago)")
            asyncio.create_task(self.send_ble("PING"))
    
    def auto_connect(self):
        if not self.is_connected:
            asyncio.create_task(self.connect())
    
    def check_connection_health(self):
        # Disabled connection health monitoring to prevent false disconnects
        # Only disconnect on actual send/receive failures
        pass
    
    async def handle_notification(self, sender, data):
        try:
            msg = data.decode("utf-8").strip()
            self.log(f"← {msg}")
            
            # Any message is a sign of life - update connection health
            import time
            self.last_ping_response = time.time()
            self.ping_timeout_count = 0
            
            if msg.startswith("ACK:"):
                if "PING" in msg:
                    self.log("🏓 Ping response received")
            elif msg.startswith("PING"):
                await self.send_ble("ACK:PING")
            elif msg.startswith("PROFILE:"):
                try:
                    device_profile_index = int(msg.replace("PROFILE:", ""))
                    self.log(f"📁 Device changed to profile: {device_profile_index}")
                    
                    # Update app to match device profile
                    if 0 <= device_profile_index < len(self.profiles):
                        # Only update if different from current app profile
                        if device_profile_index != self.current_profile_index:
                            self.log(f"📁 Syncing app profile from {self.current_profile_index} → {device_profile_index}")
                            self.sync_profile_from_device(device_profile_index)
                    else:
                        self.log(f"⚠️ Device profile index {device_profile_index} is out of range")
                except ValueError:
                    self.log(f"⚠️ Invalid profile message: {msg}")
            else:
                # Handle key press: format should be "profile_name;key_char"
                try:
                    parts = msg.split(';')
                    if len(parts) == 2:
                        device_profile_name = parts[0]
                        key_char = parts[1].upper()  # Ensure uppercase for consistency
                        
                        # Convert key character to key ID (0-15)
                        key_id = self.char_to_key_id(key_char)
                        if key_id is None:
                            self.log(f"⚠️ Unknown key character: '{key_char}'")
                        
                        self.log(f"🎹 Key pressed: '{key_char}' (ID: {key_id}) on profile '{device_profile_name}'")
                        
                        # Find the profile index by name
                        device_profile_index = None
                        for i, profile in enumerate(self.profiles):
                            if profile.get('name', f'Profile {i}') == device_profile_name:
                                device_profile_index = i
                                break
                        
                        # Light up the key temporarily
                        if key_id in self.key_buttons:
                            self.key_buttons[key_id].set_active(True)
                            QTimer.singleShot(200, lambda: self.key_buttons[key_id].set_active(False))
                        
                        # Execute the action using the device's profile, not the app's current profile
                        await self.execute_key_action_for_profile(key_id, device_profile_index)
                        
                except (ValueError, IndexError):
                    self.log(f"ℹ️ Unhandled message: {msg}")
        
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
        profile_actions = profile.get('actions', {})
        
        # Convert string keys to int if needed
        if isinstance(list(profile_actions.keys())[0] if profile_actions else None, str):
            profile_actions = {int(k): v for k, v in profile_actions.items()}
        
        action = profile_actions.get(key_id)
        profile_name = profile.get('name', f'Profile {profile_index}')
        
        if action:
            try:
                import subprocess
                # Execute the command
                subprocess.Popen(action, shell=True)
                self.log(f"⚡ Executed from '{profile_name}': {action}")
            except Exception as e:
                self.log(f"❌ Action failed from '{profile_name}': {str(e)}")
        else:
            self.log(f"⚠️ No action defined for key {key_id} in profile '{profile_name}'")
    
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
        scrollbar.setValue(scrollbar.maximum())
    
    def closeEvent(self, event):
        """Handle window close event"""
        print("Application closing...")
        
        # Stop timers first
        if hasattr(self, 'ping_timer'):
            self.ping_timer.stop()
        if hasattr(self, 'connect_timer'):
            self.connect_timer.stop()
        if hasattr(self, 'connection_check_timer'):
            self.connection_check_timer.stop()
        
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
        event.accept()


async def main():
    # Create application
    app = QApplication(sys.argv)
    
    # Create and show GUI
    window = BLEDeckGUI()
    window.show()
    
    # This will run until the application exits
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        qasync.run(main())
    except KeyboardInterrupt:
        print("Application interrupted")
    except Exception as e:
        print(f"Application error: {e}")
    finally:
        print("Application terminated")