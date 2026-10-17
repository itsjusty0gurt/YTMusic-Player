from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from ytmusic_player.playback_controller import PlaybackController
from ytmusic_player.protocol import COMMANDS, hello_response


class FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        self._callbacks.append(callback)

    def emit(self, *args: object) -> None:
        for callback in self._callbacks:
            callback(*args)


class FakePage:
    def __init__(self, result: dict[str, Any]) -> None:
        self.loadStarted = FakeSignal()
        self.loadFinished = FakeSignal()
        self.result = result
        self.scripts: list[str] = []

    def runJavaScript(
        self,
        script: str,
        callback: Callable[[str], None],
    ) -> None:
        self.scripts.append(script)
        callback(json.dumps(self.result))


def dispatch(page: FakePage, command: str) -> tuple[bool, str | None, str | None]:
    controller = PlaybackController(page)  # type: ignore[arg-type]
    page.loadFinished.emit(True)
    received: list[tuple[bool, str | None, str | None]] = []
    controller.dispatch(command, {}, lambda *result: received.append(result))
    assert len(received) == 1
    return received[0]


@pytest.mark.parametrize(("command", "label"), [("next", "Next"), ("previous", "Previous")])
def test_track_control_uses_scoped_semantic_native_button(
    command: str,
    label: str,
) -> None:
    page = FakePage({"ok": True})

    assert dispatch(page, command) == (True, None, None)
    script = page.scripts[0]
    assert "document.querySelector('ytmusic-player-bar')" in script
    assert "bar.querySelectorAll('button, [role=\"button\"]')" in script
    assert "node.getAttribute('aria-label')" in script
    assert "node.getAttribute('title')" in script
    assert f"findPlayerControl('{label}')" in script
    assert "bar.querySelector(fallbackSelector)" in script
    assert "document.querySelector('ytmusic-player-bar .next-button')" not in script
    assert "document.querySelector('ytmusic-player-bar .previous-button')" not in script
    assert script.index("bar.querySelectorAll('button") < script.index(
        "bar.querySelector(fallbackSelector)"
    )


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("next", "Next track control is unavailable."),
        ("previous", "Previous track control is unavailable."),
    ],
)
def test_track_control_fails_cleanly_when_no_usable_control_exists(
    command: str,
    message: str,
) -> None:
    page = FakePage(
        {"ok": False, "code": "player_unavailable", "message": message}
    )

    assert dispatch(page, command) == (False, "player_unavailable", message)


@pytest.mark.parametrize(
    "command",
    ["play", "pause", "play_pause", "set_volume", "set_muted"],
)
def test_existing_control_dispatch_remains_supported(command: str) -> None:
    page = FakePage({"ok": True})
    assert dispatch(page, command) == (True, None, None)


def test_protocol_capabilities_use_controller_supported_commands() -> None:
    advertised = hello_response()["capabilities"]["commands"]

    assert COMMANDS is PlaybackController.supported_commands
    assert advertised == list(PlaybackController.supported_commands)
    assert "next" in advertised
    assert "previous" in advertised
    assert "seek" not in advertised
