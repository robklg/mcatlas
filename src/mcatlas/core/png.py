"""PNG images from pure data: 8-bit indexed colour with one palette, nothing else.

Enough for in-game maps, whose pixels already are palette indexes. The same pixels always give
the same bytes, so an export only rewrites an image when the picture changed.
"""

import struct
import zlib
from typing import Final

_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data)
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def indexed_png(
    width: int, height: int, pixels: bytes, palette: bytes, alpha: bytes = b""
) -> bytes:
    """`pixels` row by row, one palette index each; `palette` RGB triples; `alpha` the opacity
    of the first palette entries (the rest are opaque)."""
    if width <= 0 or height <= 0 or len(pixels) != width * height:
        raise ValueError(f"{len(pixels)} pixels do not make a {width}×{height} image")
    if not 0 < len(palette) <= 3 * 256 or len(palette) % 3:
        raise ValueError("palette must hold 1 to 256 RGB triples")
    rows = b"".join(b"\0" + pixels[y * width : (y + 1) * width] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    return b"".join(
        (
            _SIGNATURE,
            _chunk(b"IHDR", header),
            _chunk(b"PLTE", palette),
            _chunk(b"tRNS", alpha) if alpha else b"",
            _chunk(b"IDAT", zlib.compress(rows, 9)),
            _chunk(b"IEND", b""),
        )
    )
