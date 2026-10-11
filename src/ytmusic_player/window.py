from __future__ import annotations

import logging

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QStyle, QSystemTrayIcon

from .resources import application_icon
from .settings import restore_window_state, save_window_state
from .web import WebSession


LOGGER = logging.getLogger(__name__)


class PlayerWindow(QMainWindow):
    def __init__(self, settings: QSettings, web_session: WebSession) -> None:
        super().__init__()
        self._settings = settings
        self._exit_requested = False

        self.setWindowTitle("YouTube Music")
        self.setMinimumSize(800, 600)
        self.setCentralWidget(web_session.create_view())

        icon = application_icon()
        if icon.isNull():
            icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.setWindowIcon(icon)

        self._toggle_action = QAction("Hide Player", self)
        self._toggle_action.triggered.connect(self.toggle_visibility)

        self._exit_action = QAction("Exit", self)
        self._exit_action.triggered.connect(self.request_exit)

        tray_menu = QMenu()
        tray_menu.addAction(self._toggle_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self._exit_action)

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("YouTube Music Desktop")
        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)

        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self._tray_available:
            self._tray.show()
        else:
            LOGGER.warning("System tray is unavailable; closing the window will exit")

        restore_window_state(self, self._settings)

    def persist_window_state(self) -> None:
        save_window_state(self, self._settings)

    def toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.persist_window_state()
            self.hide()
            self._toggle_action.setText("Show Player")
            LOGGER.info("Player hidden to system tray")
        else:
            self.show()
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
            self._toggle_action.setText("Hide Player")
            LOGGER.info("Player shown")

    def request_exit(self) -> None:
        LOGGER.info("Exit requested")
        self._exit_requested = True
        self.persist_window_state()
        self._tray.hide()
        self.close()
        QApplication.quit()

    def prepare_for_shutdown(self) -> None:
        """Remove the tray icon before the Qt event loop exits."""
        self._tray.hide()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API name)
        self.persist_window_state()
        if self._exit_requested or not self._tray_available:
            event.accept()
            return

        event.ignore()
        self.hide()
        self._toggle_action.setText("Show Player")
        LOGGER.info("Close intercepted; player hidden to system tray")

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if not self.isVisible() or self.isMinimized():
                self.toggle_visibility()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()
