from __future__ import annotations

import logging

from PySide6.QtCore import QRect, QSettings, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


LOGGER = logging.getLogger(__name__)
DEFAULT_SIZE = QSize(1200, 800)
MINIMUM_SIZE = QSize(800, 600)


def _read_int(settings: QSettings, key: str, default: int) -> int:
    value = settings.value(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring invalid integer setting %s=%r", key, value)
        return default


def _read_bool(settings: QSettings, key: str, default: bool = False) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def restore_window_state(window: QWidget, settings: QSettings) -> None:
    """Restore a visible, screen-bounded normal geometry and maximized state."""
    primary = QGuiApplication.primaryScreen()
    if primary is None:
        window.resize(DEFAULT_SIZE)
        return

    primary_area = primary.availableGeometry()
    default_x = primary_area.x() + max(0, (primary_area.width() - DEFAULT_SIZE.width()) // 2)
    default_y = primary_area.y() + max(0, (primary_area.height() - DEFAULT_SIZE.height()) // 2)

    saved = QRect(
        _read_int(settings, "window/x", default_x),
        _read_int(settings, "window/y", default_y),
        max(MINIMUM_SIZE.width(), _read_int(settings, "window/width", DEFAULT_SIZE.width())),
        max(MINIMUM_SIZE.height(), _read_int(settings, "window/height", DEFAULT_SIZE.height())),
    )

    screens = QGuiApplication.screens()
    target_screen = next(
        (screen for screen in screens if screen.availableGeometry().intersects(saved)),
        primary,
    )
    area = target_screen.availableGeometry()

    width = min(saved.width(), area.width())
    height = min(saved.height(), area.height())
    x = min(max(saved.x(), area.left()), area.right() - width + 1)
    y = min(max(saved.y(), area.top()), area.bottom() - height + 1)
    window.setGeometry(x, y, width, height)

    if _read_bool(settings, "window/maximized"):
        window.showMaximized()


def save_window_state(window: QWidget, settings: QSettings) -> None:
    """Persist the usable normal geometry even when currently maximized."""
    geometry = window.normalGeometry() if window.isMaximized() else window.geometry()
    settings.setValue("window/x", geometry.x())
    settings.setValue("window/y", geometry.y())
    settings.setValue("window/width", geometry.width())
    settings.setValue("window/height", geometry.height())
    settings.setValue("window/maximized", window.isMaximized())
    settings.sync()

    if settings.status() != QSettings.Status.NoError:
        LOGGER.warning("QSettings reported an error while saving window state")
