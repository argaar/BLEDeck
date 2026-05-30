"""Windows-specific utility helpers (ctypes)."""
from __future__ import annotations
import ctypes
import ctypes.wintypes
import logging

logger = logging.getLogger(__name__)

_DESKTOP_CLASSES = frozenset({"Shell_TrayWnd", "Progman", "WorkerW", "DV2ControlHost"})

# Win32 constants for OpenInputDesktop / GetUserObjectInformationW
_DESKTOP_SWITCHDESKTOP = 0x0100
_UOI_NAME = 2

# Win32 session-notification constants (wtsapi32 + winuser).
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0


class WtsMsg(ctypes.Structure):
    """Subset of the MSG struct sufficient to read `message` + `wParam`.

    The PyQt5 `nativeEvent` callback passes a native pointer to the full MSG
    structure; only the first three fields are needed to dispatch session
    notifications.
    """
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("message", ctypes.wintypes.UINT),
        ("wParam", ctypes.wintypes.WPARAM),
    ]


def register_session_notifications(hwnd: int) -> bool:
    """Subscribe ``hwnd`` to WM_WTSSESSION_CHANGE for the current session.

    Returns True on success. False on any failure (very old Windows / lacking
    wtsapi32.dll). The caller should fall back to polling.
    """
    try:
        return bool(
            ctypes.windll.wtsapi32.WTSRegisterSessionNotification(
                ctypes.wintypes.HWND(hwnd), NOTIFY_FOR_THIS_SESSION
            )
        )
    except (OSError, ctypes.ArgumentError, AttributeError):
        logger.debug("WTSRegisterSessionNotification failed", exc_info=True)
        return False


def unregister_session_notifications(hwnd: int) -> None:
    try:
        ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(
            ctypes.wintypes.HWND(hwnd)
        )
    except (OSError, ctypes.ArgumentError, AttributeError):
        logger.debug("WTSUnRegisterSessionNotification failed", exc_info=True)


def is_workstation_locked() -> bool:
    """
    Return True when the workstation is on the secure desktop (locked, UAC
    prompt, Ctrl+Alt+Del screen).

    Uses OpenInputDesktop + GetUserObjectInformationW which is the documented
    Win32 way to read the active desktop name. The previous heuristic
    `GetForegroundWindow() == 0` produced false positives during fullscreen
    transitions and UAC prompts.
    """
    try:
        user32 = ctypes.windll.user32  # canonical lowercase
        h = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
        if not h:
            # No access to the input desktop → secure desktop is active.
            return True
        try:
            buf = ctypes.create_unicode_buffer(256)
            needed = ctypes.wintypes.DWORD()
            ok = user32.GetUserObjectInformationW(
                h, _UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)
            )
            if not ok:
                return False
            # "Default" = normal interactive desktop; anything else (Winlogon,
            # ScreenSaver, etc.) means the user-visible session is not Default.
            return buf.value.lower() != "default"
        finally:
            user32.CloseDesktop(h)
    except (OSError, ctypes.ArgumentError, AttributeError):
        logger.debug("is_workstation_locked failed", exc_info=True)
        return False


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",    ctypes.c_ulong),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork",    ctypes.wintypes.RECT),
        ("dwFlags",   ctypes.c_ulong),
    ]

_MonitorEnumProc = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_size_t,                        # HMONITOR
    ctypes.c_size_t,                        # HDC
    ctypes.POINTER(ctypes.wintypes.RECT),   # LPRECT
    ctypes.c_ssize_t,                       # LPARAM
)
_EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


# ── public helpers ──────────────────────────────────────────────────────────

def get_foreground_window_rect() -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) of the current foreground window, or None."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = ctypes.wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect.left, rect.top, rect.right, rect.bottom
    except (OSError, ctypes.ArgumentError, AttributeError):
        logger.debug("get_foreground_window_rect failed", exc_info=True)
    return None


def get_monitor_rect(index: int) -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) for monitor at `index` (0 = leftmost)."""
    monitors = _enum_monitors()
    if 0 <= index < len(monitors):
        return monitors[index][1]
    return None


def get_window_at_point(x: int, y: int) -> tuple[str, tuple[int, int, int, int] | None]:
    """
    Return (anchor_str, rect) for the element under screen point (x, y).

    anchor_str values:
      "window:<title>"  — relative to a named top-level window
      "monitor:<N>"     — relative to monitor N left-top (taskbar / desktop clicks)
      "abs"             — fall back to absolute (no usable window found)
    """
    try:
        pt = ctypes.wintypes.POINT(x, y)
        hwnd = ctypes.windll.user32.WindowFromPoint(pt)
        if hwnd:
            hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2)  # GA_ROOT
            cls_buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, cls_buf, 256)
            if cls_buf.value not in _DESKTOP_CLASSES:
                title_buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 256)
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                return (f"window:{title_buf.value}",
                        (rect.left, rect.top, rect.right, rect.bottom))
    except (OSError, ctypes.ArgumentError, AttributeError):
        logger.debug("get_window_at_point failed", exc_info=True)

    return _monitor_anchor_at_point(x, y)


def find_window_by_title(title: str) -> tuple[int, int, int, int] | None:
    """
    Find first visible window whose title contains `title` (case-insensitive).
    Empty title → returns current foreground window rect.
    """
    if not title:
        return get_foreground_window_rect()

    results: list[tuple[int, int, int, int]] = []
    title_lower = title.lower()

    def _cb(hwnd: int, _: int) -> int:
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        if (title_lower in buf.value.lower()
                and ctypes.windll.user32.IsWindowVisible(hwnd)):
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            results.append((rect.left, rect.top, rect.right, rect.bottom))
            return 0  # stop on first match
        return 1

    cb_wrapper = _EnumWindowsProc(_cb)
    ctypes.windll.user32.EnumWindows(cb_wrapper, 0)
    return results[0] if results else None


# ── private helpers ─────────────────────────────────────────────────────────

def _enum_monitors() -> list[tuple[int, tuple[int, int, int, int]]]:
    """Return (hmonitor_int, rect) pairs sorted by left edge (index 0 = leftmost)."""
    results: list[tuple[int, tuple[int, int, int, int]]] = []

    def _cb(hmon: int, _hdc: int, lprect, _lparam: int) -> int:
        r = lprect.contents
        results.append((hmon, (r.left, r.top, r.right, r.bottom)))
        return 1

    cb_wrapper = _MonitorEnumProc(_cb)
    ctypes.windll.user32.EnumDisplayMonitors(None, None, cb_wrapper, 0)
    results.sort(key=lambda t: t[1][0])  # sort by left edge
    return results


def _monitor_anchor_at_point(x: int, y: int) -> tuple[str, tuple[int, int, int, int] | None]:
    try:
        pt = ctypes.wintypes.POINT(x, y)
        hmonitor = ctypes.windll.user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST

        monitors = _enum_monitors()
        idx = next((i for i, (hm, _) in enumerate(monitors) if hm == hmonitor), 0)

        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))
        r = info.rcMonitor
        return f"monitor:{idx}", (r.left, r.top, r.right, r.bottom)
    except (OSError, ctypes.ArgumentError, AttributeError):
        logger.debug("_monitor_anchor_at_point failed", exc_info=True)
    return "abs", None
