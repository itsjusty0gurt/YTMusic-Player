from __future__ import annotations

import ctypes
import logging
import sys

from .metadata import APP_USER_MODEL_ID


LOGGER = logging.getLogger(__name__)


def set_windows_app_user_model_id() -> bool:
    """Set the process identity used by the Windows shell and taskbar."""
    if sys.platform != "win32":
        return False

    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        LOGGER.exception("Unable to set the Windows AppUserModelID")
        return False

    if result != 0:
        LOGGER.warning("Windows rejected the AppUserModelID with HRESULT %#x", result)
        return False
    return True
