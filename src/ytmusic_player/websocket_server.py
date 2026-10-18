from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import (
    QWebSocket,
    QWebSocketCorsAuthenticator,
    QWebSocketProtocol,
    QWebSocketServer,
)

from .connection_info import (
    ConnectionInfo,
    new_connection_info,
    remove_connection_info,
    write_connection_info,
)
from .playback_controller import PlaybackController
from .playback_state import PlaybackState, PlaybackStateStore, PlaybackStatus
from .protocol import (
    MAX_MESSAGE_BYTES,
    POSITION_SYNC_INTERVAL_MS,
    CommandRequest,
    GetStateRequest,
    ProtocolViolation,
    SequenceCounter,
    command_result,
    error_response,
    hello_response,
    parse_authenticated_message,
    parse_hello,
    parse_json_message,
    serialize_message,
    state_message,
)


LOGGER = logging.getLogger(__name__)
LOCAL_HOST = "127.0.0.1"
PREFERRED_PORT = 17823
MAX_PROTOCOL_ERRORS = 3


@dataclass(slots=True)
class ClientConnection:
    authenticated: bool = False
    protocol_errors: int = 0
    client_name: str | None = None


class LocalWebSocketServer(QObject):
    """Authenticated, localhost-only transport for the playback protocol."""

    def __init__(
        self,
        state_store: PlaybackStateStore,
        controller: PlaybackController,
        token: str,
        connection_path: Path,
        parent: QObject | None = None,
        preferred_port: int = PREFERRED_PORT,
    ) -> None:
        super().__init__(parent)
        self._state_store = state_store
        self._controller = controller
        self._token = token
        self._connection_path = connection_path
        self._preferred_port = preferred_port
        self._connection_info: ConnectionInfo | None = None
        self._clients: dict[QWebSocket, ClientConnection] = {}
        self._sequence = SequenceCounter()

        self._server = QWebSocketServer(
            "YouTube Music Desktop Local API",
            QWebSocketServer.SslMode.NonSecureMode,
            self,
        )
        self._server.originAuthenticationRequired.connect(self._authenticate_origin)
        self._server.newConnection.connect(self._accept_pending_connections)

        self._position_timer = QTimer(self)
        self._position_timer.setInterval(POSITION_SYNC_INTERVAL_MS)
        self._position_timer.timeout.connect(self._send_position_sync)
        self._state_store.state_changed.connect(self.broadcast_state)

    @property
    def port(self) -> int | None:
        return self._server.serverPort() if self._server.isListening() else None

    def start(self) -> int:
        address = QHostAddress(LOCAL_HOST)
        if not self._server.listen(address, self._preferred_port):
            LOGGER.info("Preferred WebSocket port %d is unavailable; selecting a fallback", self._preferred_port)
            if not self._server.listen(address, 0):
                raise RuntimeError(f"Unable to start local WebSocket server: {self._server.errorString()}")

        port = self._server.serverPort()
        info = new_connection_info(LOCAL_HOST, port, self._token)
        try:
            write_connection_info(self._connection_path, info)
        except Exception:
            self._server.close()
            raise

        self._connection_info = info
        self._position_timer.start()
        LOGGER.info("WebSocket server started on %s:%d", LOCAL_HOST, port)
        return port

    def stop(self) -> None:
        self._position_timer.stop()
        for socket in list(self._clients):
            socket.close(
                QWebSocketProtocol.CloseCode.CloseCodeGoingAway,
                "Server shutting down",
            )
        self._clients.clear()
        if self._server.isListening():
            self._server.close()
            LOGGER.info("WebSocket server stopped")
        if self._connection_info is not None:
            remove_connection_info(self._connection_path, self._connection_info)
            self._connection_info = None

    def broadcast_state(self, state: PlaybackState, reason: str) -> None:
        recipients = [
            socket for socket, client in self._clients.items() if client.authenticated
        ]
        if not recipients:
            return
        payload = state_message(state, self._sequence.next(), reason)
        _log_state_summary(payload)
        message = serialize_message(payload)
        for socket in recipients:
            socket.sendTextMessage(message)

    def _authenticate_origin(self, authenticator: QWebSocketCorsAuthenticator) -> None:
        allowed = _origin_allowed(authenticator.origin())
        authenticator.setAllowed(allowed)
        if not allowed:
            LOGGER.warning("Rejected WebSocket connection with an untrusted browser origin")

    def _accept_pending_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setMaxAllowedIncomingFrameSize(MAX_MESSAGE_BYTES)
            socket.setMaxAllowedIncomingMessageSize(MAX_MESSAGE_BYTES)
            self._clients[socket] = ClientConnection()
            socket.textMessageReceived.connect(partial(self._receive_text, socket))
            socket.binaryMessageReceived.connect(partial(self._receive_binary, socket))
            socket.disconnected.connect(partial(self._client_disconnected, socket))
            LOGGER.info("WebSocket client connected")

    def _receive_text(self, socket: QWebSocket, text: str) -> None:
        client = self._clients.get(socket)
        if client is None:
            return
        try:
            message = parse_json_message(text)
            if not client.authenticated:
                hello = parse_hello(message, self._token)
                client.authenticated = True
                client.client_name = hello.client_name
                socket.sendTextMessage(serialize_message(hello_response()))
                self._send_state(socket, "initial")
                LOGGER.info("WebSocket client handshake succeeded")
                return

            request = parse_authenticated_message(message)
            if isinstance(request, GetStateRequest):
                self._send_state(socket, "state_refresh", request.request_id)
            else:
                self._dispatch_command(socket, request)
        except ProtocolViolation as violation:
            self._handle_protocol_violation(socket, client, violation)

    def _receive_binary(self, socket: QWebSocket, _message: bytes) -> None:
        client = self._clients.get(socket)
        if client is not None:
            self._handle_protocol_violation(
                socket,
                client,
                ProtocolViolation("invalid_request", "Binary messages are not supported."),
            )

    def _dispatch_command(self, socket: QWebSocket, request: CommandRequest) -> None:
        callback = partial(self._command_completed, socket, request)
        self._controller.dispatch(request.command, request.args, callback)

    def _command_completed(
        self,
        socket: QWebSocket,
        request: CommandRequest,
        ok: bool,
        error_code: str | None,
        error_message_text: str | None,
    ) -> None:
        if socket not in self._clients:
            return
        response = command_result(request, ok, error_code, error_message_text)
        socket.sendTextMessage(serialize_message(response))

    def _send_state(
        self,
        socket: QWebSocket,
        reason: str,
        request_id: str | None = None,
    ) -> None:
        message = state_message(
            self._state_store.current,
            self._sequence.next(),
            reason,
            request_id,
        )
        _log_state_summary(message)
        socket.sendTextMessage(serialize_message(message))

    def _send_position_sync(self) -> None:
        state = self._state_store.current
        if state.playback.status is PlaybackStatus.PLAYING:
            self.broadcast_state(state, "position_sync")

    def _handle_protocol_violation(
        self,
        socket: QWebSocket,
        client: ClientConnection,
        violation: ProtocolViolation,
    ) -> None:
        socket.sendTextMessage(
            serialize_message(error_response(violation.code, violation.message))
        )
        client.protocol_errors += 1
        LOGGER.warning("WebSocket protocol error: %s", violation.code)

        handshake_rejection = not client.authenticated and violation.code in {
            "authentication_required",
            "invalid_authentication",
            "unsupported_protocol_version",
            "invalid_request",
        }
        if handshake_rejection:
            LOGGER.warning("WebSocket client handshake rejected: %s", violation.code)
        if handshake_rejection or client.protocol_errors >= MAX_PROTOCOL_ERRORS:
            socket.close(
                QWebSocketProtocol.CloseCode.CloseCodePolicyViolated,
                violation.message,
            )

    def _client_disconnected(self, socket: QWebSocket) -> None:
        if self._clients.pop(socket, None) is not None:
            LOGGER.info("WebSocket client disconnected")
        try:
            socket.deleteLater()
        except RuntimeError:
            # Qt may delete a pending socket while the server itself is closing.
            pass


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return True
    url = QUrl(origin)
    return url.isValid() and url.host().lower() in {"127.0.0.1", "localhost"}


def _log_state_summary(message: dict[str, Any]) -> None:
    track = message.get("track") or {}
    artwork = track.get("artwork") or {}
    playback = message.get("playback") or {}
    # Keep normal playback quiet while retaining a sanitized diagnostic at
    # DEBUG level. Authentication and raw client payloads are never included.
    LOGGER.debug(
        "State payload sequence=%s reason=%s metadata_available=%s "
        "title=%s artist=%s album=%s media_id=%s artwork=%s status=%s "
        "duration_ms=%s position_ms=%s",
        message.get("sequence"),
        message.get("reason"),
        message.get("metadata_available"),
        track.get("title") or "EMPTY",
        track.get("artist") or "EMPTY",
        track.get("album") or "EMPTY",
        track.get("media_id") or "EMPTY",
        "present" if artwork.get("url") else "empty",
        playback.get("status"),
        playback.get("duration_ms"),
        playback.get("position_ms"),
    )
