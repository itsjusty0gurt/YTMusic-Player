from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from ytmusic_player.playback_state import (
    AudioState,
    PlaybackDetails,
    PlaybackState,
    PlaybackStatus,
    TrackMetadata,
)
from ytmusic_player.protocol import (
    CommandRequest,
    ProtocolViolation,
    SequenceCounter,
    command_result,
    hello_response,
    parse_authenticated_message,
    parse_hello,
    parse_json_message,
    state_message,
)


TOKEN = "test-token-that-is-long-enough-for-authentication"


def hello(token: str = TOKEN, versions: list[int] | None = None) -> dict:
    return {
        "type": "hello",
        "protocol_versions": versions or [1],
        "client": {"name": "Test Client", "version": "1.0"},
        "auth": {"token": token},
    }


def test_hello_parsing_and_highest_supported_version() -> None:
    parsed = parse_hello(hello(versions=[99, 1]), TOKEN)
    assert parsed.protocol_version == 1
    assert parsed.client_name == "Test Client"


def test_unsupported_version_rejected() -> None:
    with pytest.raises(ProtocolViolation, match="No mutually") as raised:
        parse_hello(hello(versions=[2]), TOKEN)
    assert raised.value.code == "unsupported_protocol_version"


def test_valid_and_invalid_token_authentication() -> None:
    assert parse_hello(hello(), TOKEN).protocol_version == 1
    with pytest.raises(ProtocolViolation) as raised:
        parse_hello(hello("wrong-token"), TOKEN)
    assert raised.value.code == "invalid_authentication"


def test_initial_state_can_follow_successful_hello() -> None:
    parse_hello(hello(), TOKEN)
    response = hello_response()
    snapshot = state_message(PlaybackState.unknown(), 1, "initial")
    assert response["type"] == "hello"
    assert snapshot["type"] == "state"
    assert snapshot["reason"] == "initial"
    assert snapshot["sequence"] == 1


def test_valid_command_parsing() -> None:
    request = parse_authenticated_message(
        {
            "type": "command",
            "protocol_version": 1,
            "request_id": "abc123",
            "command": "next",
        }
    )
    assert isinstance(request, CommandRequest)
    assert request.command == "next"
    assert request.args == {}


def test_missing_request_id_rejected() -> None:
    with pytest.raises(ProtocolViolation) as raised:
        parse_authenticated_message(
            {"type": "command", "protocol_version": 1, "command": "next"}
        )
    assert raised.value.code == "invalid_request"


def test_unsupported_command_rejected() -> None:
    with pytest.raises(ProtocolViolation) as raised:
        parse_authenticated_message(
            {
                "type": "command",
                "protocol_version": 1,
                "request_id": "1",
                "command": "seek",
            }
        )
    assert raised.value.code == "unsupported_command"


@pytest.mark.parametrize("value", [-1, 101, 1.5, True, "50", None])
def test_invalid_set_volume_values_rejected(value: object) -> None:
    with pytest.raises(ProtocolViolation) as raised:
        parse_authenticated_message(
            {
                "type": "command",
                "protocol_version": 1,
                "request_id": "1",
                "command": "set_volume",
                "args": {"volume": value},
            }
        )
    assert raised.value.code == "invalid_argument"


@pytest.mark.parametrize("value", [0, 50, 100])
def test_valid_set_volume_values(value: int) -> None:
    request = parse_authenticated_message(
        {
            "type": "command",
            "protocol_version": 1,
            "request_id": "1",
            "command": "set_volume",
            "args": {"volume": value},
        }
    )
    assert isinstance(request, CommandRequest)


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_invalid_set_muted_values_rejected(value: object) -> None:
    with pytest.raises(ProtocolViolation) as raised:
        parse_authenticated_message(
            {
                "type": "command",
                "protocol_version": 1,
                "request_id": "1",
                "command": "set_muted",
                "args": {"muted": value},
            }
        )
    assert raised.value.code == "invalid_argument"


def test_malformed_json_rejected() -> None:
    with pytest.raises(ProtocolViolation) as raised:
        parse_json_message("{not-json")
    assert raised.value.code == "malformed_json"


def test_oversized_message_rejected() -> None:
    with pytest.raises(ProtocolViolation) as raised:
        parse_json_message('{"value":"' + ("x" * 70_000) + '"}')
    assert raised.value.code == "message_too_large"


def test_unknown_message_type_rejected() -> None:
    with pytest.raises(ProtocolViolation) as raised:
        parse_authenticated_message({"type": "mystery", "protocol_version": 1})
    assert raised.value.code == "unsupported_message_type"


def test_command_result_success_and_failure() -> None:
    request = CommandRequest("abc", "next", {})
    success = command_result(request, True)
    failure = command_result(request, False, "player_unavailable", "Unavailable.")
    assert success == {
        "type": "command_result",
        "protocol_version": 1,
        "request_id": "abc",
        "command": "next",
        "ok": True,
    }
    assert failure["ok"] is False
    assert failure["error"]["code"] == "player_unavailable"


def test_sequence_progression() -> None:
    sequence = SequenceCounter()
    assert [sequence.next(), sequence.next(), sequence.next()] == [1, 2, 3]


def test_null_optional_metadata_serialization() -> None:
    sampled_at = datetime(2026, 10, 4, 19, 30, tzinfo=UTC)
    state = PlaybackState(
        PlaybackDetails(PlaybackStatus.PAUSED, 123, sampled_at, 500),
        TrackMetadata("Title", None, None, None, None),
        AudioState(50, False),
    )
    message = state_message(state, 1, "state_refresh")
    assert message["track"]["artist"] is None
    assert message["track"]["album"] is None
    assert message["track"]["media_id"] is None
    assert message["track"]["artwork"]["url"] is None


def test_unknown_and_stopped_remain_distinct() -> None:
    unknown = PlaybackState.unknown()
    stopped = PlaybackState(
        PlaybackDetails(PlaybackStatus.STOPPED, 0, datetime.now(UTC), None),
        None,
        AudioState(None, None),
    )
    assert state_message(unknown, 1, "initial")["playback"]["status"] == "unknown"
    assert state_message(stopped, 2, "playback_changed")["playback"]["status"] == "stopped"


def test_token_is_not_present_in_normal_protocol_log_output(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    parse_hello(hello(), TOKEN)
    logging.getLogger("ytmusic_player.test").info("WebSocket client handshake succeeded")
    assert TOKEN not in caplog.text
