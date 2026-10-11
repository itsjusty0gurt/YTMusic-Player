from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


ICON_DIRECTORY = Path(__file__).resolve().parent / "assets" / "icons"
PRIMARY_ICON_PATH = ICON_DIRECTORY / "red_play_button_with_headphones.png"


def application_icon() -> QIcon:
    """Return the shared window and tray icon."""
    return QIcon(str(PRIMARY_ICON_PATH))
