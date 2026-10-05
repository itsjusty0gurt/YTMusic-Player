from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

from .protocol import SUPPORTED_VERSIONS


TOKEN_FILENAME = "api_token"
CONNECTION_FILENAME = "connection.json"


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    protocol_versions: list[int]
    host: str
    port: int
    token: str
    pid: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def application_data_directory() -> Path:
    path = Path(
        QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def connection_file_path() -> Path:
    return application_data_directory() / CONNECTION_FILENAME


def token_file_path() -> Path:
    return application_data_directory() / TOKEN_FILENAME


def get_or_create_token(path: Path) -> str:
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if len(existing) >= 32:
        return existing

    token = secrets.token_urlsafe(32)
    _write_atomic_text(path, token + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def new_connection_info(host: str, port: int, token: str) -> ConnectionInfo:
    return ConnectionInfo(
        protocol_versions=list(SUPPORTED_VERSIONS),
        host=host,
        port=port,
        token=token,
        pid=os.getpid(),
    )


def write_connection_info(path: Path, info: ConnectionInfo) -> None:
    data = json.dumps(info.to_dict(), indent=2, ensure_ascii=False) + "\n"
    _write_atomic_text(path, data)


def _write_atomic_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def remove_connection_info(path: Path, expected: ConnectionInfo) -> None:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return

    if (
        current.get("pid") == expected.pid
        and current.get("port") == expected.port
        and current.get("token") == expected.token
    ):
        path.unlink(missing_ok=True)
