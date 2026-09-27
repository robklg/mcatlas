"""The single place where numpy's loosely typed results are narrowed to precise Python types."""

from typing import cast

import numpy as np
from numpy.typing import NDArray


def to_ints(a: NDArray[np.integer]) -> list[int]:
    return cast("list[int]", a.tolist())


def value_counts(a: NDArray[np.integer]) -> dict[int, int]:
    """Histogram of an integer array as a sorted {value: count} dict."""
    values, counts = np.unique(a, return_counts=True)
    return dict(zip(to_ints(values), to_ints(counts), strict=True))


def item(a: NDArray[np.integer], index: int) -> int:
    return a.item(index)


def eq(a: NDArray[np.generic], value: int) -> NDArray[np.bool_]:
    return cast("NDArray[np.bool_]", np.equal(a, value))


def ne(a: NDArray[np.generic], value: int) -> NDArray[np.bool_]:
    return cast("NDArray[np.bool_]", np.not_equal(a, value))


def shape2(a: NDArray[np.generic]) -> tuple[int, int]:
    """(rows, columns) of a 2-D array."""
    return cast("tuple[int, int]", a.shape)
