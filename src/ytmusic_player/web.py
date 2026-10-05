from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView


LOGGER = logging.getLogger(__name__)
YOUTUBE_MUSIC_URL = QUrl("https://music.youtube.com")


class WebSession(QObject):
    """Own the persistent browser profile for the lifetime of the app."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        data_root = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            )
        )
        cache_root = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.CacheLocation
            )
        )
        profile_data = data_root / "webengine"
        profile_cache = cache_root / "webengine"
        profile_data.mkdir(parents=True, exist_ok=True)
        profile_cache.mkdir(parents=True, exist_ok=True)

        self.profile = QWebEngineProfile("YouTubeMusic", self)
        self.profile.setPersistentStoragePath(str(profile_data))
        self.profile.setCachePath(str(profile_cache))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        LOGGER.info("WebEngine profile data: %s", profile_data)

        self.view = QWebEngineView()
        self.page = QWebEnginePage(self.profile, self.view)
        self.view.setPage(self.page)
        self.page.loadStarted.connect(lambda: LOGGER.info("Loading YouTube Music"))
        self.page.loadFinished.connect(self._on_load_finished)

    def create_view(self) -> QWebEngineView:
        return self.view

    def start(self) -> None:
        self.view.setUrl(YOUTUBE_MUSIC_URL)

    @staticmethod
    def _on_load_finished(success: bool) -> None:
        if success:
            LOGGER.info("YouTube Music loaded")
        else:
            LOGGER.error("YouTube Music failed to load")
