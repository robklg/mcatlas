"""Decode-only reader for Minecraft's NBT format.

There is deliberately no encoder in this package: mcatlas must never be able to write world data.
(The test suite has its own writer for building fixtures.)

Decoded values map onto plain Python types. The distinction between byte/short/int/long and
float/double is dropped because nothing in mcatlas needs it; array tags become numpy arrays.
"""

import gzip
import struct
import zlib
from typing import Final, cast

import numpy as np
from numpy.typing import NDArray

type NbtArray = NDArray[np.int8] | NDArray[np.int32] | NDArray[np.int64]
type NbtList = list[NbtValue]
type NbtCompound = dict[str, NbtValue]
type NbtValue = int | float | str | NbtArray | NbtList | NbtCompound

TAG_END: Final = 0
TAG_BYTE: Final = 1
TAG_SHORT: Final = 2
TAG_INT: Final = 3
TAG_LONG: Final = 4
TAG_FLOAT: Final = 5
TAG_DOUBLE: Final = 6
TAG_BYTE_ARRAY: Final = 7
TAG_STRING: Final = 8
TAG_LIST: Final = 9
TAG_COMPOUND: Final = 10
TAG_INT_ARRAY: Final = 11
TAG_LONG_ARRAY: Final = 12

MAX_DEPTH: Final = 512

_BYTE = struct.Struct(">b")
_SHORT = struct.Struct(">h")
_USHORT = struct.Struct(">H")
_INT = struct.Struct(">i")
_LONG = struct.Struct(">q")
_FLOAT = struct.Struct(">f")
_DOUBLE = struct.Struct(">d")


class NbtError(ValueError):
    """Raised when bytes are not valid NBT."""


def _decode_mutf8(raw: bytes) -> str:
    """Decode Java's "modified UTF-8" (NUL as C0 80, supplementary chars as surrogate pairs)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.replace(b"\xc0\x80", b"\x00").decode("utf-8", "surrogatepass")
        return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


class _Decoder:
    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def _take(self, n: int) -> int:
        start = self._pos
        end = start + n
        if n < 0 or end > len(self._data):
            raise NbtError(f"unexpected end of data at offset {start} (need {n} bytes)")
        self._pos = end
        return start

    def _unpack_int(self, fmt: struct.Struct) -> int:
        return cast("int", fmt.unpack_from(self._data, self._take(fmt.size))[0])

    def _unpack_float(self, fmt: struct.Struct) -> float:
        return cast("float", fmt.unpack_from(self._data, self._take(fmt.size))[0])

    def tag_type(self) -> int:
        return self._data[self._take(1)]

    def string(self) -> str:
        length = self._unpack_int(_USHORT)
        start = self._take(length)
        return _decode_mutf8(self._data[start : start + length])

    def _array(self, dtype: str, item_size: int) -> NbtArray:
        count = self._unpack_int(_INT)
        start = self._take(count * item_size)
        return np.frombuffer(self._data, dtype=np.dtype(dtype), count=count, offset=start)

    def payload(self, tag: int, depth: int) -> NbtValue:  # noqa: PLR0911, PLR0912 - one arm per tag type
        if depth > MAX_DEPTH:
            raise NbtError("NBT nesting too deep")
        match tag:
            case 1:
                return self._unpack_int(_BYTE)
            case 2:
                return self._unpack_int(_SHORT)
            case 3:
                return self._unpack_int(_INT)
            case 4:
                return self._unpack_int(_LONG)
            case 5:
                return self._unpack_float(_FLOAT)
            case 6:
                return self._unpack_float(_DOUBLE)
            case 7:
                return self._array("i1", 1)
            case 8:
                return self.string()
            case 9:
                item_tag = self.tag_type()
                count = self._unpack_int(_INT)
                if count <= 0:
                    return []
                if item_tag == TAG_END:
                    raise NbtError("non-empty list with element type TAG_End")
                return [self.payload(item_tag, depth + 1) for _ in range(count)]
            case 10:
                compound: NbtCompound = {}
                while (child := self.tag_type()) != TAG_END:
                    name = self.string()
                    compound[name] = self.payload(child, depth + 1)
                return compound
            case 11:
                return self._array(">i4", 4)
            case 12:
                return self._array(">i8", 8)
            case _:
                raise NbtError(f"unknown tag type {tag} at offset {self._pos - 1}")

    def root(self) -> tuple[str, NbtCompound]:
        tag = self.tag_type()
        if tag != TAG_COMPOUND:
            raise NbtError(f"root tag must be a compound, got type {tag}")
        name = self.string()
        value = self.payload(TAG_COMPOUND, 0)
        if not isinstance(value, dict):  # pragma: no cover - payload(TAG_COMPOUND) is a dict
            raise NbtError("root payload is not a compound")
        return name, value


def decompress(data: bytes) -> bytes:
    """Undo the gzip or zlib wrapping Minecraft uses for .dat files; raw NBT passes through."""
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if data[:1] == b"\x78":
        return zlib.decompress(data)
    return data


def decode(data: bytes) -> NbtCompound:
    """Decode an uncompressed NBT document and return its root compound."""
    return _Decoder(data).root()[1]


def decode_named(data: bytes) -> tuple[str, NbtCompound]:
    """Like `decode`, but also return the (usually empty) root tag name."""
    return _Decoder(data).root()


def decode_file(data: bytes) -> NbtCompound:
    """Decode the contents of a .dat file, which may be gzip, zlib or uncompressed."""
    return decode(decompress(data))
