from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtWidgets import QApplication

from .connection_info import connection_file_path, get_or_create_token, token_file_path
from .logging_setup import configure_logging
from .playback_bridge import PlaybackBridge
from .playback_controller import PlaybackController
from .playback_state import PlaybackStateStore
from .web import WebSession
from .websocket_server import LocalWebSocketServer
from .window import PlayerWindow


LOGGER = logging.getLogger(__name__)
ORGANIZATION_NAME = "YouTubeMusicDesktop"
APPLICATION_NAME = "YouTubeMusicDesktop"


class PlayerApplication:
    """Create and retain the Qt objects that make up the application."""

    def __init__(self, argv: list[str]) -> None:
        QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
        QCoreApplication.setApplicationName(APPLICATION_NAME)
        QCoreApplication.setApplicationVersion("0.1.0")
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

        self.qt_app = QApplication(argv)
        self.qt_app.setQuitOnLastWindowClosed(False)

        log_path = configure_logging()
        LOGGER.info("Starting YouTube Music Desktop")
        LOGGER.info("Log file: %s", log_path)

        self.settings = QSettings()
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

    def run(self) -> int:
        self.window.show()
        return self.qt_app.exec()

    def _shutdown(self) -> None:
        LOGGER.info("Shutting down")
        if self.websocket_server is not None:
            self.websocket_server.stop()
        self.playback_bridge.stop()
        self.window.persist_window_state()
        self.settings.sync()

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
