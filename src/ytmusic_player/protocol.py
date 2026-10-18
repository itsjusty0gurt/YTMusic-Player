from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import Any

from .metadata import APP_VERSION
from .playback_commands import PLAYBACK_COMMANDS
from .playback_state import PlaybackState, isoformat_utc, utc_now


PROTOCOL_VERSION = 1
SUPPORTED_VERSIONS = (PROTOCOL_VERSION,)
SERVER_NAME = "YouTube Music Desktop"
SERVER_VERSION = APP_VERSION
POSITION_SYNC_INTERVAL_MS = 10_000
MAX_MESSAGE_BYTES = 64 * 1024
MAX_CLIENT_TEXT_LENGTH = 128

COMMANDS = PLAYBACK_COMMANDS


class ProtocolViolation(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class HelloRequest:
    protocol_version: int
    client_name: str
    client_version: str


@dataclass(frozen=True, slots=True)
class GetStateRequest:
    request_id: str | None


@dataclass(frozen=True, slots=True)
class CommandRequest:
    request_id: str
    command: str
    args: dict[str, Any]


class SequenceCounter:
    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


def parse_json_message(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolViolation("message_too_large", "Message exceeds the maximum allowed size.")
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProtocolViolation("malformed_json", "Message is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ProtocolViolation("invalid_request", "Message must be a JSON object.")
    return value


def parse_hello(message: dict[str, Any], expected_token: str) -> HelloRequest:
    if message.get("type") != "hello":
        raise ProtocolViolation("authentication_required", "The first message must be an authenticated hello.")

    versions = message.get("protocol_versions")
    if not isinstance(versions, list) or not versions or any(
        isinstance(version, bool) or not isinstance(version, int) for version in versions
    ):
        raise ProtocolViolation("invalid_request", "protocol_versions must be a non-empty integer array.")

    compatible = sorted(set(versions).intersection(SUPPORTED_VERSIONS), reverse=True)
    if not compatible:
        raise ProtocolViolation("unsupported_protocol_version", "No mutually supported protocol version.")

    auth = message.get("auth")
    token = auth.get("token") if isinstance(auth, dict) else None
    if not isinstance(token, str) or not hmac.compare_digest(token, expected_token):
        raise ProtocolViolation("invalid_authentication", "Authentication failed.")

    client = message.get("client")
    if not isinstance(client, dict):
        raise ProtocolViolation("invalid_request", "client must be an object.")
    name = _bounded_text(client.get("name"), "client.name")
    version = _bounded_text(client.get("version"), "client.version")

    return HelloRequest(
        protocol_version=compatible[0],
        client_name=name,
        client_version=version,
    )


def parse_authenticated_message(message: dict[str, Any]) -> GetStateRequest | CommandRequest:
    message_type = message.get("type")
    if message_type == "get_state":
        _require_protocol_version(message)
        request_id = message.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise ProtocolViolation("invalid_request", "request_id must be a string when supplied.")
        return GetStateRequest(request_id=request_id)

    if message_type == "command":
        _require_protocol_version(message)
        request_id = message.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ProtocolViolation("invalid_request", "A non-empty request_id is required.")

        command = message.get("command")
        if not isinstance(command, str):
            raise ProtocolViolation("invalid_request", "command must be a string.")
        if command not in COMMANDS:
            raise ProtocolViolation("unsupported_command", "Unsupported command.")

        args = message.get("args", {})
        if not isinstance(args, dict):
            raise ProtocolViolation("invalid_argument", "args must be an object.")
        _validate_command_args(command, args)
        return CommandRequest(request_id=request_id, command=command, args=args)

    raise ProtocolViolation("unsupported_message_type", "Unknown message type.")


def hello_response() -> dict[str, Any]:
    return {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION,
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "capabilities": {
            "commands": list(COMMANDS),
            "artwork_transport": "url",
            "position_sync_interval_ms": POSITION_SYNC_INTERVAL_MS,
        },
    }


def state_message(
    state: PlaybackState,
    sequence: int,
    reason: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    track = None
    if state.metadata_available and state.track is not None:
        track = {
            "title": state.track.title,
            "artist": state.track.artist,
            "album": state.track.album,
            "media_id": state.track.media_id,
            "artwork": {"url": state.track.artwork_url},
        }

    result: dict[str, Any] = {
        "type": "state",
        "protocol_version": PROTOCOL_VERSION,
        "sequence": sequence,
        "reason": reason,
        "sent_at": isoformat_utc(utc_now()),
        "metadata_available": state.metadata_available,
        "playback": {
            "status": state.playback.status.value,
            "position_ms": state.playback.position_ms,
            "position_sampled_at": isoformat_utc(state.playback.position_sampled_at),
            "duration_ms": state.playback.duration_ms,
        },
        "track": track,
        "audio": {
            "volume": state.audio.volume,
            "muted": state.audio.muted,
        },
    }
    if request_id is not None:
        result["request_id"] = request_id
    return result


def command_result(
    request: CommandRequest,
    ok: bool,
    error_code: str | None = None,
    error_message_text: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "command_result",
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "command": request.command,
        "ok": ok,
    }
    if not ok:
        result["error"] = {
            "code": error_code or "command_failed",
            "message": error_message_text or "The playback command could not be dispatched.",
        }
    return result


def error_response(code: str, message: str) -> dict[str, Any]:
    return {
        "type": "error",
        "protocol_version": PROTOCOL_VERSION,
        "error": {"code": code, "message": message},
    }


def serialize_message(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def _require_protocol_version(message: dict[str, Any]) -> None:
    version = message.get("protocol_version")
    if isinstance(version, bool) or version != PROTOCOL_VERSION:
        raise ProtocolViolation("unsupported_protocol_version", "Unsupported protocol version.")


def _validate_command_args(command: str, args: dict[str, Any]) -> None:
    if command == "set_volume":
        volume = args.get("volume")
        if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
            raise ProtocolViolation("invalid_argument", "volume must be an integer from 0 to 100.")
    elif command == "set_muted":
        if not isinstance(args.get("muted"), bool):
            raise ProtocolViolation("invalid_argument", "muted must be a boolean.")


def _bounded_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolViolation("invalid_request", f"{field} must be a non-empty string.")
    value = value.strip()
    if len(value) > MAX_CLIENT_TEXT_LENGTH:
        raise ProtocolViolation("invalid_request", f"{field} is too long.")
    return value
