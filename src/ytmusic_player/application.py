from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtWidgets import QApplication

from .connection_info import (
    connection_file_path,
    get_or_create_token,
    instance_lock_file_path,
    token_file_path,
)
from .logging_setup import configure_logging
from .metadata import APP_VERSION, APPLICATION_NAME, DISPLAY_NAME, ORGANIZATION_NAME
from .playback_bridge import PlaybackBridge
from .playback_controller import PlaybackController
from .playback_state import PlaybackStateStore
from .resources import application_icon
from .single_instance import SingleInstanceLock
from .web import WebSession
from .websocket_server import LocalWebSocketServer
from .window import PlayerWindow
from .windows_identity import set_windows_app_user_model_id


LOGGER = logging.getLogger(__name__)


class PlayerApplication:
    """Create and retain the Qt objects that make up the application."""

    def __init__(self, argv: list[str]) -> None:
        set_windows_app_user_model_id()
        QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
        QCoreApplication.setApplicationName(APPLICATION_NAME)
        QCoreApplication.setApplicationVersion(APP_VERSION)
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

        self.qt_app = QApplication(argv)
        self.qt_app.setApplicationDisplayName(DISPLAY_NAME)
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.qt_app.setWindowIcon(application_icon())

        log_path = configure_logging()
        LOGGER.info("Starting YouTube Music Desktop")
        LOGGER.info("Log file: %s", log_path)

        self.instance_lock = SingleInstanceLock(instance_lock_file_path())
        self.already_running = not self.instance_lock.acquire()
        if self.already_running:
            LOGGER.info("Another YouTube Music Desktop instance is already running")
            return

        self._shutdown_complete = False
        self.settings = QSettings()
        try:
            self.web_session = WebSession(self.qt_app)
            self.window = PlayerWindow(self.settings, self.web_session)
            self.playback_state = PlaybackStateStore(self.qt_app)
            self.playback_controller = PlaybackController(
                self.web_session.page,
                self.qt_app,
            )
            self.playback_bridge = PlaybackBridge(
                self.web_session.page,
                self.playback_state,
                self.qt_app,
            )
            self.websocket_server: LocalWebSocketServer | None = None
            self._start_local_api()
            self.playback_bridge.start()
            self.web_session.start()
            self.qt_app.aboutToQuit.connect(self._shutdown)
        except Exception:
            self.instance_lock.release()
            raise

    def run(self) -> int:
        if self.already_running:
            return 0
        self.window.show()
        return self.qt_app.exec()

    def _shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        LOGGER.info("Shutting down")
        self.window.prepare_for_shutdown()
        if self.websocket_server is not None:
            self.websocket_server.stop()
        self.playback_bridge.stop()
        self.window.persist_window_state()
        self.settings.sync()
        self.instance_lock.release()

    def _start_local_api(self) -> None:
        try:
            token = get_or_create_token(token_file_path())
            server = LocalWebSocketServer(
                self.playback_state,
                self.playback_controller,
                token,
                connection_file_path(),
                self.qt_app,
            )
            server.start()
            self.websocket_server = server
        except Exception:
            LOGGER.exception("Unable to start the local WebSocket API")


def run(argv: list[str] | None = None) -> int:
    application = PlayerApplication(sys.argv if argv is None else argv)
    return application.run()
