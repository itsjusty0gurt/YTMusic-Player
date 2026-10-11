from __future__ import annotations

import argparse
from pathlib import Path

from ytmusic_player.metadata import APP_VERSION, DISPLAY_NAME, EXECUTABLE_NAME


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version.split(".")]
    if not 1 <= len(parts) <= 4:
        raise ValueError("Application version must contain between one and four integers.")
    return tuple((parts + [0] * 4)[:4])  # type: ignore[return-value]


def render_version_info() -> str:
    numeric_version = version_tuple(APP_VERSION)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric_version!r},
    prodvers={numeric_version!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('FileDescription', '{DISPLAY_NAME}'),
          StringStruct('FileVersion', '{APP_VERSION}'),
          StringStruct('InternalName', 'YouTubeMusicDesktop'),
          StringStruct('OriginalFilename', '{EXECUTABLE_NAME}'),
          StringStruct('ProductName', '{DISPLAY_NAME}'),
          StringStruct('ProductVersion', '{APP_VERSION}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PyInstaller Windows version metadata.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_version_info(), encoding="utf-8", newline="\n")
    print(f"Created {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
