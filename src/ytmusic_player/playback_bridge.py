from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWebEngineCore import QWebEnginePage

from .playback_state import (
    AudioState,
    PlaybackDetails,
    PlaybackState,
    PlaybackStateStore,
    PlaybackStatus,
    TrackMetadata,
    utc_now,
)


LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_MS = 1000
SEEK_THRESHOLD_MS = 3000

# This is the sole page-specific metadata extraction script. The WebSocket
# layer receives only PlaybackState instances and contains no DOM knowledge.
READ_PLAYBACK_STATE_SCRIPT = r"""
JSON.stringify((() => {
  const video = document.querySelector('video');
  const bar = document.querySelector('ytmusic-player-bar');
  if (!video) {
    return {
      status: 'unknown', position_ms: null, duration_ms: null,
      volume: null, muted: null, title: null, artist: null, album: null,
      media_id: null, artwork_url: null
    };
  }

  const clean = (value) => {
    if (typeof value !== 'string') return null;
    const normalized = value.replace(/\s+/g, ' ').trim();
    return normalized || null;
  };
  const text = (selector) => clean(bar?.querySelector(selector)?.textContent);
  const bylineLinks = Array.from(bar?.querySelectorAll('.byline a') || [])
    .map((node) => clean(node.textContent)).filter(Boolean);
  const image = bar?.querySelector('#thumbnail img, yt-img-shadow img, img');

  let mediaId = null;
  try {
    const candidate = document.querySelector('ytmusic-player')?.playerApi
      ?.getVideoData?.()?.video_id;
    mediaId = clean(candidate);
  } catch (_) {
    mediaId = null;
  }

  let status = 'unknown';
  if (video.ended) status = 'stopped';
  else if (video.readyState > 0) status = video.paused ? 'paused' : 'playing';

  const finiteMs = (seconds) => Number.isFinite(seconds)
    ? Math.max(0, Math.round(seconds * 1000)) : null;

  return {
    status,
    position_ms: finiteMs(video.currentTime),
    duration_ms: finiteMs(video.duration),
    volume: Number.isFinite(video.volume) ? Math.round(video.volume * 100) : null,
    muted: Boolean(video.muted),
    title: text('.title'),
    artist: bylineLinks.length > 0 ? bylineLinks[0] : null,
    album: bylineLinks.length > 1 ? bylineLinks[bylineLinks.length - 1] : null,
    media_id: mediaId,
    artwork_url: clean(image?.currentSrc || image?.src)
  };
})())
"""


class PlaybackBridge(QObject):
    """Poll YouTube Music and update the canonical PlaybackState."""

    def __init__(
        self,
        page: QWebEnginePage,
        state_store: PlaybackStateStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._page = page
        self._state_store = state_store
        self._page_ready = False
        self._poll_in_flight = False
        self._has_sample = False

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.poll)
        self._page.loadStarted.connect(self._on_load_started)
        self._page.loadFinished.connect(self._on_load_finished)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> None:
        if not self._page_ready or self._poll_in_flight:
            return
        self._poll_in_flight = True
        self._page.runJavaScript(READ_PLAYBACK_STATE_SCRIPT, self._receive_sample)

    def _on_load_started(self) -> None:
        self._page_ready = False

    def _on_load_finished(self, success: bool) -> None:
        self._page_ready = success
        if success:
            self.poll()
        else:
            self._state_store.update(PlaybackState.unknown(), "state_refresh")

    def _receive_sample(self, payload: Any) -> None:
        self._poll_in_flight = False
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, dict):
            LOGGER.debug("Ignoring invalid playback bridge sample")
            return

        try:
            state = self._state_from_payload(payload)
        except (TypeError, ValueError):
            LOGGER.exception("Failed to parse playback bridge sample")
            return

        previous = self._state_store.current
        reason = self._reason_for_change(previous, state)
        if not self._has_sample:
            reason = "state_refresh"
            self._has_sample = True
        self._state_store.update(state, reason)

    @staticmethod
    def _state_from_payload(payload: dict[str, Any]) -> PlaybackState:
        sampled_at = utc_now()
        try:
            status = PlaybackStatus(str(payload.get("status", "unknown")))
        except ValueError:
            status = PlaybackStatus.UNKNOWN

        title = _optional_text(payload.get("title"))
        track = None
        if title is not None:
            track = TrackMetadata(
                title=title,
                artist=_optional_text(payload.get("artist")),
                album=_optional_text(payload.get("album")),
                media_id=_optional_text(payload.get("media_id")),
                artwork_url=_optional_text(payload.get("artwork_url")),
            )

        return PlaybackState(
            playback=PlaybackDetails(
                status=status,
                position_ms=_optional_nonnegative_int(payload.get("position_ms")),
                position_sampled_at=sampled_at,
                duration_ms=_optional_nonnegative_int(payload.get("duration_ms")),
            ),
            track=track,
            audio=AudioState(
                volume=_optional_volume(payload.get("volume")),
                muted=payload.get("muted") if isinstance(payload.get("muted"), bool) else None,
            ),
        )

    @staticmethod
    def _reason_for_change(previous: PlaybackState, current: PlaybackState) -> str | None:
        if previous.track != current.track:
            return "track_changed"
        if previous.playback.status != current.playback.status:
            return "playback_changed"
        if previous.audio != current.audio:
            return "volume_changed"
        if _seek_detected(previous, current):
            return "seek"
        if (
            previous.metadata_available != current.metadata_available
            or previous.playback.duration_ms != current.playback.duration_ms
        ):
            return "state_refresh"
        return None


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, round(value))


def _optional_volume(value: Any) -> int | None:
    result = _optional_nonnegative_int(value)
    if result is None or result > 100:
        return None
    return result


def _seek_detected(previous: PlaybackState, current: PlaybackState) -> bool:
    old_position = previous.playback.position_ms
    new_position = current.playback.position_ms
    if old_position is None or new_position is None:
        return False

    expected = old_position
    if previous.playback.status is PlaybackStatus.PLAYING:
        elapsed = current.playback.position_sampled_at - previous.playback.position_sampled_at
        expected += max(0, round(elapsed.total_seconds() * 1000))
    return abs(new_position - expected) > SEEK_THRESHOLD_MS
