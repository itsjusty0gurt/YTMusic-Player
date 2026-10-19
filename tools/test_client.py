from __future__ import annotations

import argparse
import json
import sys

from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtWebSockets import QWebSocket

from ytmusic_player.connection_info import connection_file_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Connect to the local YouTube Music API.")
    parser.add_argument(
        "--command",
        choices=["play", "pause", "play_pause", "next", "previous", "set_volume", "set_muted"],
    )
    parser.add_argument("--volume", type=int)
    parser.add_argument("--muted", choices=["true", "false"])
    parser.add_argument(
        "--watch-seconds",
        type=int,
        default=0,
        help="Keep printing state messages for this many seconds after connecting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    QCoreApplication.setOrganizationName("YouTubeMusicDesktop")
    QCoreApplication.setApplicationName("YouTubeMusicDesktop")
    info = json.loads(connection_file_path().read_text(encoding="utf-8"))
    app = QCoreApplication(sys.argv)
    socket = QWebSocket()
    command_sent = False

    def connected() -> None:
        socket.sendTextMessage(
            json.dumps(
                {
                    "type": "hello",
                    "protocol_versions": [1],
                    "client": {"name": "Development Test Client", "version": "1.0.0"},
                    "auth": {"token": info["token"]},
                }
            )
        )

    def received(text: str) -> None:
        nonlocal command_sent
        message = json.loads(text)
        print(json.dumps(message, indent=2, ensure_ascii=False))
        if message.get("type") == "state" and args.command and not command_sent:
            command_sent = True
            command = {
                "type": "command",
                "protocol_version": 1,
                "request_id": "development-test",
                "command": args.command,
            }
            if args.command == "set_volume":
                command["args"] = {"volume": args.volume}
            elif args.command == "set_muted":
                command["args"] = {"muted": args.muted == "true"}
            socket.sendTextMessage(json.dumps(command))
        elif args.watch_seconds <= 0 and (
            message.get("type") == "command_result" or (
                message.get("type") == "state" and not args.command
            )
        ):
            socket.close()
            app.quit()

    socket.connected.connect(connected)
    socket.textMessageReceived.connect(received)
    socket.errorOccurred.connect(lambda _error: app.exit(1))
    socket.open(QUrl(f"ws://{info['host']}:{info['port']}"))
    timeout_ms = args.watch_seconds * 1000 if args.watch_seconds > 0 else 5000
    QTimer.singleShot(timeout_ms, lambda: (socket.close(), app.quit()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
