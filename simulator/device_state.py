from dataclasses import dataclass, field
from typing import Tuple

RGBW = Tuple[int, int, int, int]
_DEFAULT_RGBW: RGBW = (0, 0, 0, 0)


@dataclass
class DeviceState:
    profiles: dict[int, str] = field(default_factory=dict)
    current_profile_index: int = 0  # 0-based
    rgb_matrix: list[RGBW] = field(default_factory=lambda: [_DEFAULT_RGBW] * 16)
    locked: bool = False
    battery_percent: int = 80
