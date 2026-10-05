from __future__ import annotations

import json

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, QUrl
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtWebSockets import QWebSocket

from ytmusic_player.playback_state import PlaybackStateStore
from ytmusic_player.websocket_server import LocalWebSocketServer


TOKEN = "integration-test-token-with-sufficient-length"


class FakeController(QObject):
    def dispatch(self, command, args, callback) -> None:
        callback(True, None, None)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _exchange(port: int, token: str, expected_messages: int) -> tuple[list[dict], bool]:
    _app()
    socket = QWebSocket()
    loop = QEventLoop()
    messages: list[dict] = []
    disconnected = False

    def on_connected() -> None:
        socket.sendTextMessage(
            json.dumps(
                {
                    "type": "hello",
                    "protocol_versions": [1],
                    "client": {"name": "Integration Test", "version": "1"},
                    "auth": {"token": token},
                }
            )
        )

    def on_message(text: str) -> None:
        messages.append(json.loads(text))
        if len(messages) >= expected_messages:
            loop.quit()

    def on_disconnected() -> None:
        nonlocal disconnected
        disconnected = True
        loop.quit()

    socket.connected.connect(on_connected)
    socket.textMessageReceived.connect(on_message)
    socket.disconnected.connect(on_disconnected)
    socket.open(QUrl(f"ws://127.0.0.1:{port}"))
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    socket.close()
    QCoreApplication.processEvents()
    return messages, disconnected


def test_valid_handshake_sends_hello_then_initial_state(tmp_path) -> None:
    _app()
    store = PlaybackStateStore()
    server = LocalWebSocketServer(
        store,
        FakeController(),
        TOKEN,
        tmp_path / "connection.json",
        preferred_port=0,
    )
    port = server.start()
    try:
        messages, _ = _exchange(port, TOKEN, 2)
        assert [message["type"] for message in messages] == ["hello", "state"]
        assert messages[1]["reason"] == "initial"
    finally:
        server.stop()


def test_invalid_authentication_is_rejected(tmp_path) -> None:
    _app()
    server = LocalWebSocketServer(
        PlaybackStateStore(),
        FakeController(),
        TOKEN,
        tmp_path / "connection.json",
        preferred_port=0,
    )
    port = server.start()
    try:
        messages, disconnected = _exchange(port, "wrong-token", 1)
        assert messages[0]["error"]["code"] == "invalid_authentication"
        assert disconnected or len(messages) == 1
    finally:
        server.stop()


def test_busy_preferred_port_uses_fallback(tmp_path) -> None:
    _app()
    blocker = QTcpServer()
    assert blocker.listen(QHostAddress("127.0.0.1"), 0)
    preferred = blocker.serverPort()
    server = LocalWebSocketServer(
        PlaybackStateStore(),
        FakeController(),
        TOKEN,
        tmp_path / "connection.json",
        preferred_port=preferred,
    )
    try:
        actual = server.start()
        assert actual != preferred
        assert actual > 0
    finally:
        server.stop()
        blocker.close()


def test_two_clients_remain_independent(tmp_path) -> None:
    _app()
    server = LocalWebSocketServer(
        PlaybackStateStore(),
        FakeController(),
        TOKEN,
        tmp_path / "connection.json",
        preferred_port=0,
    )
    port = server.start()
    first = QWebSocket()
    second = QWebSocket()
    loop = QEventLoop()
    received = {first: [], second: []}

    hello_text = json.dumps(
        {
            "type": "hello",
            "protocol_versions": [1],
            "client": {"name": "Multi-client Test", "version": "1"},
            "auth": {"token": TOKEN},
        }
    )

    first.connected.connect(lambda: first.sendTextMessage(hello_text))
    second.connected.connect(lambda: second.sendTextMessage(hello_text))

    def receive(socket: QWebSocket, text: str) -> None:
        received[socket].append(json.loads(text))
        if len(received[first]) >= 2 and len(received[second]) >= 2:
            loop.quit()

    first.textMessageReceived.connect(lambda text: receive(first, text))
    second.textMessageReceived.connect(lambda text: receive(second, text))
    first.open(QUrl(f"ws://127.0.0.1:{port}"))
    second.open(QUrl(f"ws://127.0.0.1:{port}"))
    QTimer.singleShot(3000, loop.quit)
    loop.exec()

    assert len(received[first]) >= 2
    assert len(received[second]) >= 2
    first.close()
    QCoreApplication.processEvents()

    second.sendTextMessage(
        json.dumps(
            {
                "type": "get_state",
                "protocol_version": 1,
                "request_id": "still-connected",
            }
        )
    )
    retry_loop = QEventLoop()
    second.textMessageReceived.connect(lambda _text: retry_loop.quit())
    QTimer.singleShot(3000, retry_loop.quit)
    retry_loop.exec()

    try:
        assert received[second][-1]["type"] == "state"
        assert received[second][-1]["request_id"] == "still-connected"
    finally:
        second.close()
        server.stop()
