from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from PySide6.QtCore import QObject, Signal


class PlaybackStatus(str, Enum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PlaybackDetails:
    status: PlaybackStatus
    position_ms: int | None
    position_sampled_at: datetime
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class TrackMetadata:
    title: str
    artist: str | None
    album: str | None
    media_id: str | None
    artwork_url: str | None


@dataclass(frozen=True, slots=True)
class AudioState:
    volume: int | None
    muted: bool | None


@dataclass(frozen=True, slots=True)
class PlaybackState:
    playback: PlaybackDetails
    track: TrackMetadata | None
    audio: AudioState

    @property
    def metadata_available(self) -> bool:
        return bool(
            self.track is not None
            and self.track.title.strip()
            and self.track.artist
            and self.track.artist.strip()
        )

    @classmethod
    def unknown(cls) -> PlaybackState:
        return cls(
            playback=PlaybackDetails(
                status=PlaybackStatus.UNKNOWN,
                position_ms=None,
                position_sampled_at=utc_now(),
                duration_ms=None,
            ),
            track=None,
            audio=AudioState(volume=None, muted=None),
        )


class PlaybackStateStore(QObject):
    """Own the single canonical playback state used throughout the app."""

    state_changed = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = PlaybackState.unknown()

    @property
    def current(self) -> PlaybackState:
        return self._state

    def update(self, state: PlaybackState, reason: str | None = None) -> None:
        self._state = state
        if reason is not None:
            self.state_changed.emit(state, reason)
