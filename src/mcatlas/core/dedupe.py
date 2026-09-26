"""Find worlds that share history (copies, backups, "New World (3)" style duplicates).

Each world is reduced to the set of (dimension, chunk x, chunk z, last-save timestamp) keys.
Copies share most keys; unrelated worlds share none, even with the same seed. A MinHash
signature estimates Jaccard similarity between these sets without storing them.
"""

import zlib
from collections.abc import Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

SIGNATURE_SIZE: Final = 64

_GOLDEN = np.uint64(0x9E3779B97F4A7C15)
_MUL1 = np.uint64(0xBF58476D1CE4E5B9)
_MUL2 = np.uint64(0x94D049BB133111EB)


def _mix(x: NDArray[np.uint64]) -> NDArray[np.uint64]:
    """splitmix64 finalizer, vectorized (uint64 arithmetic wraps as intended)."""
    x = x + _GOLDEN
    x = (x ^ (x >> np.uint64(30))) * _MUL1
    x = (x ^ (x >> np.uint64(27))) * _MUL2
    return x ^ (x >> np.uint64(31))


def dimension_code(key: str) -> int:
    return zlib.crc32(key.encode()) & 0x3FFFFF


def chunk_keys(
    dim_code: int, xs: NDArray[np.int64], zs: NDArray[np.int64], ts: NDArray[np.int64]
) -> NDArray[np.uint64]:
    packed = (
        (xs.astype(np.uint64) & np.uint64(0x1FFFFF))
        | ((zs.astype(np.uint64) & np.uint64(0x1FFFFF)) << np.uint64(21))
        | (np.uint64(dim_code) << np.uint64(42))
    )
    return _mix(packed ^ _mix(ts.astype(np.uint64)))


def minhash(keys: NDArray[np.uint64], size: int = SIGNATURE_SIZE) -> list[int]:
    if keys.size == 0:
        return []
    seeds = _mix(np.arange(1, size + 1, dtype=np.uint64))
    return [int(_mix(keys ^ seeds[i : i + 1]).min()) for i in range(size)]


def similarity(a: Sequence[int], b: Sequence[int]) -> float:
    """Estimated Jaccard similarity of the two underlying key sets (0.0 – 1.0)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)
