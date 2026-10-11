from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    PROJECT_ROOT
    / "src"
    / "ytmusic_player"
    / "assets"
    / "icons"
    / "red_play_button_with_headphones.png"
)
DEFAULT_OUTPUT = DEFAULT_SOURCE.with_name("youtube_music_desktop.ico")
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _png_payload(source: QImage, size: int) -> bytes:
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Unable to allocate an image buffer.")
    if not scaled.save(buffer, "PNG"):
        raise RuntimeError(f"Unable to encode the {size}px icon image.")
    return bytes(encoded)


def build_ico(source_path: Path, output_path: Path) -> None:
    source = QImage(str(source_path))
    if source.isNull():
        raise RuntimeError(f"Unable to load source icon: {source_path}")

    payloads = [_png_payload(source, size) for size in ICON_SIZES]
    header_size = 6 + (16 * len(payloads))
    offset = header_size
    entries: list[bytes] = []
    for size, payload in zip(ICON_SIZES, payloads, strict=True):
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        offset += len(payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        struct.pack("<HHH", 0, 1, len(payloads))
        + b"".join(entries)
        + b"".join(payloads)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Windows multi-size icon.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build_ico(args.source.resolve(), args.output.resolve())
    print(f"Created {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
