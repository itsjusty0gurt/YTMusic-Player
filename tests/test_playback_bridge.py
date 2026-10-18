from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QCoreApplication, QObject, QEventLoop, QTimer, Signal

from ytmusic_player.playback_bridge import (
    INSTALL_PLAYBACK_OBSERVER_SCRIPT,
    READ_PLAYBACK_STATE_SCRIPT,
    PlaybackBridge,
)
from ytmusic_player.playback_state import (
    AudioState,
    PlaybackDetails,
    PlaybackState,
    PlaybackStateStore,
    PlaybackStatus,
    TrackMetadata,
)


def _state(
    *,
    title: str | None = "Track A",
    artist: str | None = "Artist A",
    album: str | None = "Album A",
    media_id: str | None = None,
    artwork: str | None = "https://example.test/a.jpg",
    position_ms: int = 1000,
) -> PlaybackState:
    sampled_at = datetime(2026, 1, 1, tzinfo=UTC)
    return PlaybackState(
        playback=PlaybackDetails(
            status=PlaybackStatus.PAUSED,
            position_ms=position_ms,
            position_sampled_at=sampled_at,
            duration_ms=180_000,
        ),
        track=(
            TrackMetadata(title, artist, album, media_id, artwork)
            if title is not None
            else None
        ),
        audio=AudioState(volume=50, muted=False),
    )


def _payload(**overrides) -> dict:
    payload = {
        "status": "playing",
        "position_ms": 12_345,
        "duration_ms": 234_000,
        "volume": 72,
        "muted": False,
        "title": "  Track   Title  ",
        "artist": " Artist Name ",
        "album": " Album Name ",
        "media_id": None,
        "artwork_url": "https://example.test/art.jpg",
    }
    payload.update(overrides)
    return payload


def test_reader_is_scoped_to_current_player_bar_and_has_semantic_fallbacks() -> None:
    assert "document.querySelector('ytmusic-player-bar')" in READ_PLAYBACK_STATE_SCRIPT
    assert "yt-formatted-string.title" in READ_PLAYBACK_STATE_SCRIPT
    assert "yt-formatted-string.byline" in READ_PLAYBACK_STATE_SCRIPT
    assert "playerData?.title" in READ_PLAYBACK_STATE_SCRIPT
    assert "playerData?.author" in READ_PLAYBACK_STATE_SCRIPT
    assert "document.querySelectorAll" not in READ_PLAYBACK_STATE_SCRIPT


def test_observer_watches_player_bar_and_video_events() -> None:
    assert "new MutationObserver" in INSTALL_PLAYBACK_OBSERVER_SCRIPT
    assert "closest?.('ytmusic-player-bar')" in INSTALL_PLAYBACK_OBSERVER_SCRIPT
    assert "'play', 'pause', 'ended'" in INSTALL_PLAYBACK_OBSERVER_SCRIPT


def test_payload_produces_complete_canonical_metadata() -> None:
    state = PlaybackBridge._state_from_payload(_payload())
    assert state.metadata_available is True
    assert state.track == TrackMetadata(
        title="Track Title",
        artist="Artist Name",
        album="Album Name",
        media_id=None,
        artwork_url="https://example.test/art.jpg",
    )
    assert state.playback.status is PlaybackStatus.PLAYING
    assert state.playback.position_ms == 12_345
    assert state.playback.duration_ms == 234_000
    assert state.audio == AudioState(volume=72, muted=False)


def test_optional_metadata_can_be_null_without_disabling_metadata() -> None:
    state = PlaybackBridge._state_from_payload(
        _payload(album=None, media_id=None, artwork_url=None)
    )
    assert state.metadata_available is True
    assert state.track is not None
    assert state.track.title == "Track Title"
    assert state.track.artist == "Artist Name"
    assert state.track.album is None
    assert state.track.media_id is None
    assert state.track.artwork_url is None


def test_missing_title_cleanly_disables_metadata() -> None:
    state = PlaybackBridge._state_from_payload(_payload(title=None, artist=None))
    assert state.metadata_available is False
    assert state.track is None


def test_missing_artist_cleanly_disables_metadata() -> None:
    state = PlaybackBridge._state_from_payload(_payload(artist="  "))
    assert state.metadata_available is False
    assert state.track is None


def test_same_normalized_title_artist_is_not_a_track_change() -> None:
    previous = _state(title="Track  A", artist="ARTIST A", artwork="old")
    current = _state(title=" track a ", artist="artist a", artwork="new")
    assert PlaybackBridge._reason_for_change(previous, current) == "state_refresh"


def test_changed_media_id_is_a_track_change() -> None:
    previous = _state(media_id="video-a")
    current = _state(media_id="video-b")
    assert PlaybackBridge._reason_for_change(previous, current) == "track_changed"


def test_changed_title_or_artist_without_media_id_is_a_track_change() -> None:
    previous = _state(media_id=None)
    assert PlaybackBridge._reason_for_change(
        previous, _state(title="Track B", media_id=None)
    ) == "track_changed"
    assert PlaybackBridge._reason_for_change(
        previous, _state(artist="Artist B", media_id=None)
    ) == "track_changed"


def test_position_only_change_does_not_publish_track_change() -> None:
    previous = _state(position_ms=1000)
    current = _state(position_ms=1000)
    current = PlaybackState(
        playback=PlaybackDetails(
            status=current.playback.status,
            position_ms=2000,
            position_sampled_at=current.playback.position_sampled_at + timedelta(seconds=1),
            duration_ms=current.playback.duration_ms,
        ),
        track=current.track,
        audio=current.audio,
    )
    assert PlaybackBridge._reason_for_change(previous, current) is None


class _FakePage(QObject):
    loadStarted = Signal()
    loadFinished = Signal(bool)

    def setWebChannel(self, channel) -> None:
        self.channel = channel

    def runJavaScript(self, script, callback=None) -> None:
        self.last_script = script


def test_rapid_partial_samples_are_coalesced() -> None:
    QCoreApplication.instance() or QCoreApplication([])
    store = PlaybackStateStore()
    bridge = PlaybackBridge(_FakePage(), store)
    observed = []
    store.state_changed.connect(lambda state, reason: observed.append((state, reason)))

    bridge._queue_sample(_payload(title="Partial", artist=None))
    bridge._queue_sample(_payload(title="Final", artist="Final Artist"))
    loop = QEventLoop()
    QTimer.singleShot(500, loop.quit)
    loop.exec()

    assert len(observed) == 1
    assert observed[0][0].track is not None
    assert observed[0][0].track.title == "Final"
    assert observed[0][0].track.artist == "Final Artist"
    assert observed[0][1] == "state_refresh"
