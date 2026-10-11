from __future__ import annotations

import struct

from PySide6.QtGui import QImage

from ytmusic_player.resources import ICON_DIRECTORY, PRIMARY_ICON_PATH


def test_primary_icon_is_a_valid_square_image() -> None:
    image = QImage(str(PRIMARY_ICON_PATH))
    assert not image.isNull()
    assert image.width() == image.height()
    assert image.width() >= 256


def test_windows_icon_contains_expected_sizes() -> None:
    icon_path = ICON_DIRECTORY / "youtube_music_desktop.ico"
    icon_data = icon_path.read_bytes()
    reserved, image_type, image_count = struct.unpack_from("<HHH", icon_data)
    assert reserved == 0
    assert image_type == 1

    sizes: set[tuple[int, int]] = set()
    for index in range(image_count):
        width, height = struct.unpack_from("<BB", icon_data, 6 + index * 16)
        sizes.add((width or 256, height or 256))

    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes
