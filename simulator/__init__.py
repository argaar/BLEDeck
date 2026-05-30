import sys
from pathlib import Path

_WINDOWS_APP = Path(__file__).parent.parent / "windows_app"
if str(_WINDOWS_APP) not in sys.path:
    sys.path.insert(0, str(_WINDOWS_APP))
