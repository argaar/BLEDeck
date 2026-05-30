import logging

from PyQt5.QtWidgets import QPushButton, QSizePolicy

import ble_protocol

logger = logging.getLogger(__name__)


class KeyButton(QPushButton):
    def __init__(self, key_id: int, text: str) -> None:
        super().__init__()
        self.key_id = key_id
        self.key_number = text
        self.key_label = ""
        self.key_color: tuple[int, int, int, int] | None = None
        self.setMinimumSize(70, 70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.is_active = False
        self.update_button_text()
        self.update_button_style()

    def update_button_text(self) -> None:
        if self.key_label:
            if len(self.key_label) > 10 and ' ' in self.key_label:
                words = self.key_label.split(' ')
                if len(words) >= 2:
                    self.setText(f"{self.key_number}\n{'\n'.join(words)}")
                else:
                    self.setText(f"{self.key_number}\n{self.key_label}")
            else:
                self.setText(f"{self.key_number}\n{self.key_label}")
        else:
            self.setText(self.key_number)

    def set_label(self, label: str) -> None:
        self.key_label = label
        self.update_button_text()

    def set_color(self, color_str: str | None) -> None:
        parsed = ble_protocol.parse_color_string(color_str) if color_str else None
        if parsed is not None:
            self.key_color = parsed
        else:
            if color_str:
                logger.warning("Invalid color string '%s'", color_str)
            self.key_color = None
        self.update_button_style()

    def update_button_style(self) -> None:
        if self.is_active:
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
            r, g, b, bri = self.key_color
            brightness = bri / 100.0
            r_adj = int(r * brightness)
            g_adj = int(g * brightness)
            b_adj = int(b * brightness)

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

    def set_active(self, active: bool) -> None:
        self.is_active = active
        self.update_button_style()