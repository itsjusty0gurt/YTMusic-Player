from __future__ import annotations

import json

from ytmusic_player.connection_info import (
    ConnectionInfo,
    get_or_create_token,
    remove_connection_info,
    write_connection_info,
)


def test_connection_info_serialization_and_removal(tmp_path) -> None:
    path = tmp_path / "connection.json"
    info = ConnectionInfo([1], "127.0.0.1", 17823, "secret", 123)
    write_connection_info(path, info)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "protocol_versions": [1],
        "host": "127.0.0.1",
        "port": 17823,
        "token": "secret",
        "pid": 123,
    }
    assert not list(tmp_path.glob("*.tmp"))
    remove_connection_info(path, info)
    assert not path.exists()


def test_persistent_token_is_reused(tmp_path) -> None:
    path = tmp_path / "api_token"
    first = get_or_create_token(path)
    second = get_or_create_token(path)
    assert first == second
    assert len(first) >= 32
