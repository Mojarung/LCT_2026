"""PNG без сторонних библиотек: карта покрытий для веба - это растр с четырьмя цветами.

Pillow ради одного файла в образ не тащим: PNG с RGBA и одним блоком IDAT - это сигнатура,
три чанка и zlib (ISO/IEC 15948, PNG Specification, разд. 5 и 11).
"""

from __future__ import annotations

import struct
import zlib
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RGBA = 6
_DEPTH = 8


def encode_rgba(pixels: NDArray[np.uint8]) -> bytes:
    """Картинка height x width x 4 (uint8) в байты PNG; строка 0 - верх картинки."""
    height, width, channels = pixels.shape
    if channels != 4:  # noqa: PLR2004 - RGBA
        raise ValueError("ожидается RGBA: четыре канала на пиксель")
    # Перед каждой строкой - байт фильтра 0 (без фильтра): так проще и достаточно сжимается.
    rows = np.concatenate(
        [np.zeros((height, 1), dtype=np.uint8), pixels.reshape(height, width * 4)], axis=1
    )
    header = struct.pack(">IIBBBBB", width, height, _DEPTH, _RGBA, 0, 0, 0)
    return (
        _SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 6))
        + _chunk(b"IEND", b"")
    )


def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


__all__ = ["encode_rgba"]
