from __future__ import annotations

import ctypes
import os


QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4
SUPPRESS_NOTIFICATION_STATES = {
    QUNS_BUSY,
    QUNS_RUNNING_D3D_FULL_SCREEN,
    QUNS_PRESENTATION_MODE,
}


def enable_per_monitor_dpi_awareness() -> bool:
    """Enable the best available Windows DPI-awareness mode before Tk is created."""
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
        context = ctypes.c_void_p(-4 & ((1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1))
        if user32.SetProcessDpiAwarenessContext(context):
            return True
    except (AttributeError, OSError):
        pass

    try:
        shcore = ctypes.windll.shcore
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        return shcore.SetProcessDpiAwareness(2) in (0,)
    except (AttributeError, OSError):
        pass

    try:
        return bool(user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def user_notification_state() -> int | None:
    """Return SHQueryUserNotificationState, or None when unavailable."""
    if os.name != "nt":
        return None
    state = ctypes.c_int()
    try:
        result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except (AttributeError, OSError):
        return None
    if result != 0:
        return None
    return int(state.value)


def should_suppress_overlay_notifications() -> bool:
    state = user_notification_state()
    return state in SUPPRESS_NOTIFICATION_STATES
