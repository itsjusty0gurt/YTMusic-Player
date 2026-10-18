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
FALLBACK_POLL_INTERVAL_MS = 5000
OBSERVER_TRANSPORT_INTERVAL_MS = 500
SAMPLE_DEBOUNCE_MS = 300
SEEK_THRESHOLD_MS = 3000

# All YouTube-specific DOM assumptions live here. Metadata is scoped to the
# active player bar; page-wide title/byline matches are deliberately avoided.
STATE_READER_BODY = r"""
  const clean = (value) => {
    if (typeof value !== 'string') return null;
    const normalized = value.replace(/\s+/g, ' ').trim();
    return normalized || null;
  };
  const bar = document.querySelector('ytmusic-player-bar');
  const video = document.querySelector(
    'ytmusic-player-page video, #movie_player video, video'
  );
  if (!video) {
    return {
      status: 'unknown', position_ms: null, duration_ms: null,
      volume: null, muted: null, title: null, artist: null, album: null,
      media_id: null, artwork_url: null
    };
  }

  const text = (...selectors) => {
    for (const selector of selectors) {
      const value = clean(bar?.querySelector(selector)?.textContent);
      if (value) return value;
    }
    return null;
  };
  const byline = bar?.querySelector(
    'yt-formatted-string.byline, .byline.ytmusic-player-bar, .byline'
  );
  const bylineLinks = Array.from(byline?.querySelectorAll('a') || [])
    .map((node) => clean(node.textContent)).filter(Boolean);
  const image = bar?.querySelector(
    '#thumbnail img, .thumbnail-image-wrapper img, yt-img-shadow img'
  );

  let playerData = null;
  try {
    playerData = document.querySelector('ytmusic-player')?.playerApi
      ?.getVideoData?.() || null;
  } catch (_) {
    playerData = null;
  }

  let mediaId = clean(playerData?.video_id);
  if (!mediaId) {
    const activeTrackLink = bar?.querySelector(
      '.title a[href*="watch?v="], a.yt-simple-endpoint[href*="watch?v="]'
    );
    try {
      mediaId = clean(new URL(activeTrackLink?.href || '', location.href)
        .searchParams.get('v'));
    } catch (_) {
      mediaId = null;
    }
  }

  const title = text(
    'yt-formatted-string.title', '.title.ytmusic-player-bar', '.title'
  ) || clean(playerData?.title);
  const artist = bylineLinks[0] || clean(playerData?.author);
  const album = bylineLinks.length > 1
    ? bylineLinks[bylineLinks.length - 1] : null;

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
    title,
    artist,
    album,
    media_id: mediaId,
    artwork_url: clean(image?.currentSrc || image?.src)
  };
"""

READ_PLAYBACK_STATE_SCRIPT = "JSON.stringify((() => {" + STATE_READER_BODY + "})())"

# The observer handles YouTube Music's in-page player updates. A slow Python
# poll remains as a reliability fallback and refreshes playback position.
INSTALL_PLAYBACK_OBSERVER_SCRIPT = r"""
(() => {
  const install = () => {
    if (window.__ytMusicDesktopObserverInstalled) {
      window.__ytMusicDesktopScheduleSample?.();
      return;
    }
    const readState = () => {
      %s
    };
      let debounceHandle = null;
      const schedule = () => {
        clearTimeout(debounceHandle);
        debounceHandle = setTimeout(() => {
          window.__ytMusicDesktopSample = JSON.stringify(readState());
          window.__ytMusicDesktopSampleRevision =
            (window.__ytMusicDesktopSampleRevision || 0) + 1;
        }, %d);
      };
      window.__ytMusicDesktopScheduleSample = schedule;

      const concernsPlayerBar = (mutation) => {
        const target = mutation.target?.nodeType === Node.ELEMENT_NODE
          ? mutation.target : mutation.target?.parentElement;
        if (target?.closest?.('ytmusic-player-bar')) return true;
        return Array.from(mutation.addedNodes || []).some((node) =>
          node.nodeType === Node.ELEMENT_NODE &&
          (node.matches?.('ytmusic-player-bar') ||
           node.querySelector?.('ytmusic-player-bar'))
        );
      };
      const observer = new MutationObserver((mutations) => {
        if (mutations.some(concernsPlayerBar)) schedule();
      });
      observer.observe(document.body || document.documentElement, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['src', 'title', 'aria-label']
      });

      const attachVideoEvents = () => {
        const video = document.querySelector(
          'ytmusic-player-page video, #movie_player video, video'
        );
        if (!video || video.__ytMusicDesktopObserved) return;
        video.__ytMusicDesktopObserved = true;
        for (const eventName of [
          'play', 'pause', 'ended', 'emptied', 'loadedmetadata',
          'durationchange', 'volumechange', 'seeking', 'seeked'
        ]) {
          video.addEventListener(eventName, schedule, {passive: true});
        }
      };
      new MutationObserver(attachVideoEvents).observe(
        document.body || document.documentElement,
        {subtree: true, childList: true}
      );
      attachVideoEvents();
      window.__ytMusicDesktopObserverInstalled = true;
      schedule();
  };
  install();
})()
""" % (STATE_READER_BODY, SAMPLE_DEBOUNCE_MS)

READ_OBSERVER_SAMPLE_SCRIPT = r"""
(() => {
  const revision = window.__ytMusicDesktopSampleRevision || 0;
  if (!revision || revision === window.__ytMusicDesktopReadRevision) return null;
  window.__ytMusicDesktopReadRevision = revision;
  return window.__ytMusicDesktopSample || null;
})()
"""


class PlaybackBridge(QObject):
    """Observe YouTube Music and update the canonical PlaybackState."""

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
        self._pending_payload: dict[str, Any] | None = None

        self._sample_timer = QTimer(self)
        self._sample_timer.setSingleShot(True)
        self._sample_timer.setInterval(SAMPLE_DEBOUNCE_MS)
        self._sample_timer.timeout.connect(self._process_pending_sample)

        self._timer = QTimer(self)
        self._timer.setInterval(FALLBACK_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.poll)
        self._observer_timer = QTimer(self)
        self._observer_timer.setInterval(OBSERVER_TRANSPORT_INTERVAL_MS)
        self._observer_timer.timeout.connect(self._read_observer_sample)
        self._page.loadStarted.connect(self._on_load_started)
        self._page.loadFinished.connect(self._on_load_finished)

    def start(self) -> None:
        self._timer.start()
        self._observer_timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._observer_timer.stop()
        self._sample_timer.stop()

    def poll(self) -> None:
        if not self._page_ready or self._poll_in_flight:
            return
        self._poll_in_flight = True
        self._page.runJavaScript(READ_PLAYBACK_STATE_SCRIPT, self._receive_poll_sample)

    def _on_load_started(self) -> None:
        self._page_ready = False
        self._has_sample = False
        self._pending_payload = None
        self._sample_timer.stop()

    def _on_load_finished(self, success: bool) -> None:
        self._page_ready = success
        if success:
            self._page.runJavaScript(INSTALL_PLAYBACK_OBSERVER_SCRIPT)
            self.poll()
        else:
            self._state_store.update(PlaybackState.unknown(), "state_refresh")

    def _receive_poll_sample(self, payload: Any) -> None:
        self._poll_in_flight = False
        self._queue_sample(payload)

    def _read_observer_sample(self) -> None:
        if self._page_ready:
            self._page.runJavaScript(
                READ_OBSERVER_SAMPLE_SCRIPT,
                self._queue_sample,
            )

    def _queue_sample(self, payload: Any) -> None:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, dict):
            LOGGER.debug("Ignoring invalid playback bridge sample")
            return
        self._pending_payload = payload
        self._sample_timer.start()

    def _process_pending_sample(self) -> None:
        payload = self._pending_payload
        self._pending_payload = None
        if payload is None:
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
        artist = _optional_text(payload.get("artist"))
        track = None
        if title is not None and artist is not None:
            track = TrackMetadata(
                title=title,
                artist=artist,
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
        if _track_identity_changed(previous.track, current.track):
            return "track_changed"
        if previous.playback.status != current.playback.status:
            return "playback_changed"
        if previous.audio != current.audio:
            return "volume_changed"
        if _seek_detected(previous, current):
            return "seek"
        if (
            previous.track != current.track
            or previous.metadata_available != current.metadata_available
            or previous.playback.duration_ms != current.playback.duration_ms
        ):
            return "state_refresh"
        return None


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def _normalized_identity_text(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _track_identity_changed(
    previous: TrackMetadata | None,
    current: TrackMetadata | None,
) -> bool:
    if previous is None or current is None:
        return previous is not current
    if previous.media_id and current.media_id:
        return previous.media_id != current.media_id
    return (
        _normalized_identity_text(previous.title),
        _normalized_identity_text(previous.artist),
    ) != (
        _normalized_identity_text(current.title),
        _normalized_identity_text(current.artist),
    )


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
