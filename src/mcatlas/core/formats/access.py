"""Small, type-narrowing accessors for decoded NBT compounds.

Each accessor returns `None` when the key is missing or holds a value of an unexpected type, so
format adapters can probe several historical layouts without try/except noise.
"""

import uuid

import numpy as np
from numpy.typing import NDArray

from mcatlas.core.nbt import NbtCompound, NbtList, NbtValue
from mcatlas.core.npx import to_ints


def compound(c: NbtCompound, key: str) -> NbtCompound | None:
    value = c.get(key)
    return value if isinstance(value, dict) else None


def compound_path(c: NbtCompound, *keys: str) -> NbtCompound | None:
    current: NbtCompound | None = c
    for key in keys:
        if current is None:
            return None
        current = compound(current, key)
    return current


def list_(c: NbtCompound, key: str) -> NbtList | None:
    value = c.get(key)
    return value if isinstance(value, list) else None


def int_(c: NbtCompound, key: str) -> int | None:
    value = c.get(key)
    return value if isinstance(value, int) else None


def float_(c: NbtCompound, key: str) -> float | None:
    value = c.get(key)
    if isinstance(value, float):
        return value
    return float(value) if isinstance(value, int) else None


def str_(c: NbtCompound, key: str) -> str | None:
    value = c.get(key)
    return value if isinstance(value, str) else None


def bool_(c: NbtCompound, key: str) -> bool | None:
    value = int_(c, key)
    return None if value is None else value != 0


def strings(values: NbtList | None) -> list[str]:
    return [v for v in values or [] if isinstance(v, str)]


def compounds(values: NbtList | None) -> list[NbtCompound]:
    return [v for v in values or [] if isinstance(v, dict)]


def floats(values: NbtList | None) -> list[float]:
    return [float(v) for v in values or [] if isinstance(v, int | float)]


def int_array(value: NbtValue | None) -> NDArray[np.int64] | None:
    """Interpret an int/long array tag (or a list of ints) as a native int64 array."""
    if isinstance(value, np.ndarray):
        return value.astype(np.int64)
    if isinstance(value, list) and all(isinstance(v, int) for v in value):
        return np.array(value, dtype=np.int64)
    return None


def uuid_from(c: NbtCompound) -> str | None:
    """Read an entity UUID in any of its historical encodings."""
    arr = int_array(c.get("UUID"))
    if arr is not None and arr.size == 4:
        raw = b"".join((x & 0xFFFFFFFF).to_bytes(4, "big") for x in to_ints(arr))
        return str(uuid.UUID(bytes=raw))
    most, least = int_(c, "UUIDMost"), int_(c, "UUIDLeast")
    if most is not None and least is not None:
        raw = (most & (2**64 - 1)).to_bytes(8, "big") + (least & (2**64 - 1)).to_bytes(8, "big")
        return str(uuid.UUID(bytes=raw))
    return None
