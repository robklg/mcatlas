"""Chunk maps for the atlas: what was built where, seen from above, one square per chunk.

Two maps per world, both of its main dimension:
- *built*: generated land light grey, chunks with building in orange (darker = more blocks);
- *underground*: chunks with building from green (above ground) to brown (below it); only
  drawn for worlds built mostly underground.
Build sites are outlined and numbered as in the atlas. The images hold no words, so they are
the same in every language; the page's caption explains them.

Only the area with the most building is drawn: a teleport far away would otherwise shrink the
map until nothing is recognizable.
"""

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from mcatlas.core.build import BuildSite, DimensionMap
from mcatlas.core.npx import shape2
from mcatlas.core.png import indexed_png

MAX_SIDE: Final = 1024
"""Pixels; larger areas get several chunks per pixel."""
TARGET_SIDE: Final = 640
"""Small areas are enlarged (up to 8 pixels per chunk) towards this size."""
MARGIN: Final = 8
"""Chunks of land drawn around the building."""
NEAR: Final = 8
"""Chunks with building closer than this belong to one group."""
SPREAD: Final = 256
"""Groups of building are drawn together while they fit in this many chunks (4096 blocks);
farther ones (a teleport to the edge of the world) are left out."""
MIN_BUILT: Final = 20
"""Chunks with fewer built blocks count as land only in the underground map."""
BUILT_STEPS: Final = (1, 10, 100, 1_000, 10_000)
"""Built blocks per chunk where the next, darker orange starts."""
BELOW_STEPS: Final = (0.2, 0.4, 0.6, 0.8)
"""Share built underground where the next colour (green → grey → brown) starts."""

_PAPER, _LAND, _INK = 0, 1, 2
_ORANGE: Final = 3  # 5 steps
_SPLIT: Final = 8  # 5 steps: green, light green, grey, light brown, brown
PALETTE: Final = bytes(
    [
        246, 244, 238,  # paper
        219, 214, 203,  # generated land
        40, 40, 40,  # ink: outlines and numbers
        253, 190, 133, 253, 141, 60, 230, 85, 13, 166, 54, 3, 100, 30, 0,
        26, 120, 60, 120, 190, 120, 168, 168, 160, 200, 150, 100, 120, 70, 30,
    ]
)  # fmt: skip

# Digits of 3 by 5 pixels, one string per row, "#" = ink.
_DIGITS: Final = (
    ("###", "# #", "# #", "# #", "###"),
    (" # ", "## ", " # ", " # ", "###"),
    ("###", "  #", "###", "#  ", "###"),
    ("###", "  #", "###", "  #", "###"),
    ("# #", "# #", "###", "  #", "  #"),
    ("###", "#  ", "###", "  #", "###"),
    ("###", "#  ", "###", "# #", "###"),
    ("###", "  #", "  #", "  #", "  #"),
    ("###", "# #", "###", "# #", "###"),
    ("###", "# #", "###", "  #", "###"),
)

type Grid = NDArray[np.uint8]
type Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class ChunkMaps:
    built: bytes
    underground: bytes | None
    box: Box
    """Blocks shown: min_x, min_z, max_x, max_z."""
    blocks_per_pixel: float
    elsewhere: int
    """Chunks with building outside the area shown."""


def footprint_chunks(footprint: Mapping[str, str]) -> NDArray[np.int64]:
    """All generated chunks as an (n, 2) array of chunk x, z."""
    parts: list[NDArray[np.int64]] = []
    for key, bits in footprint.items():
        rx, _, rz = key.partition(",")
        present = np.unpackbits(np.frombuffer(base64.b64decode(bits), np.uint8))[:1024]
        idx = np.flatnonzero(present).astype(np.int64)
        parts.append(np.stack((int(rx) * 32 + idx % 32, int(rz) * 32 + idx // 32), axis=1))
    return np.concatenate(parts) if parts else np.zeros((0, 2), np.int64)


def _main_area(m: DimensionMap) -> tuple[list[int], int]:
    """Indexes of the built chunks drawn, and how many were left out.

    The group with the most building comes first; other groups join while all fit."""
    built = [i for i, b in enumerate(m.built) if b > 0]
    parent = {i: i for i in built}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[tuple[int, int], int] = {}
    for i in built:
        cx, cz = m.x[i] // NEAR, m.z[i] // NEAR
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                other = owner.get((cx + dx, cz + dz))
                if other is not None:
                    parent[root(i)] = root(other)
        owner.setdefault((cx, cz), i)
    groups: dict[int, list[int]] = {}
    for i in built:
        groups.setdefault(root(i), []).append(i)
    if not groups:
        return [], 0
    ordered = sorted(groups.values(), key=lambda g: (-sum(m.built[i] for i in g), min(g)))
    area = list(ordered[0])
    box = _bounds(m, area)
    for group in ordered[1:]:
        g = _bounds(m, group)
        joined = (min(box[0], g[0]), min(box[1], g[1]), max(box[2], g[2]), max(box[3], g[3]))
        if max(joined[2] - joined[0], joined[3] - joined[1]) < SPREAD:
            area += group
            box = joined
    return area, len(built) - len(area)


def _bounds(m: DimensionMap, idx: Sequence[int]) -> Box:
    xs, zs = [m.x[i] for i in idx], [m.z[i] for i in idx]
    return (min(xs), min(zs), max(xs), max(zs))


def _digit_rows(number: int) -> list[str]:
    glyphs = [_DIGITS[int(c)] for c in str(number)]
    return [" ".join(g[row] for g in glyphs) for row in range(5)]


def _label(img: Grid, number: int, left: int, bottom: int) -> None:
    """The number in ink on a paper patch, its lower left corner at (left, bottom)."""
    rows = _digit_rows(number)
    scale = 2
    height, width = 5 * scale + 2, len(rows[0]) * scale + 2
    top = max(bottom - height, 0)
    left = min(max(left, 0), shape2(img)[1] - width)
    img[top : top + height, left : left + width] = _PAPER
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch == "#":
                y, x = top + 1 + r * scale, left + 1 + c * scale
                img[y : y + scale, x : x + scale] = _INK


def _outline(img: Grid, top: int, left: int, bottom: int, right: int) -> None:
    h, w = shape2(img)
    top, left = max(top, 0), max(left, 0)
    bottom, right = min(bottom, h - 1), min(right, w - 1)
    img[top, left : right + 1] = _INK
    img[bottom, left : right + 1] = _INK
    img[top : bottom + 1, left] = _INK
    img[top : bottom + 1, right] = _INK


@dataclass(frozen=True, slots=True)
class _Frame:
    """The chunks drawn (inclusive) and how: chunks per cell, pixels per cell."""

    x0: int
    z0: int
    x1: int
    z1: int
    per_cell: int
    px: int

    @property
    def cells(self) -> tuple[int, int]:
        return ((self.z1 - self.z0) // self.per_cell + 1, (self.x1 - self.x0) // self.per_cell + 1)

    @property
    def blocks_per_pixel(self) -> float:
        return 16 * self.per_cell / self.px

    def contains(self, x: int, z: int) -> bool:
        return self.x0 <= x <= self.x1 and self.z0 <= z <= self.z1


def _frame(m: DimensionMap, area: Sequence[int]) -> _Frame:
    bx0, bz0, bx1, bz1 = _bounds(m, area)
    x0, z0, x1, z1 = bx0 - MARGIN, bz0 - MARGIN, bx1 + MARGIN, bz1 + MARGIN
    side = max(x1 - x0 + 1, z1 - z0 + 1)
    per_cell = 1
    while side > MAX_SIDE * per_cell:
        per_cell *= 2
    cells = (side - 1) // per_cell + 1
    px = 1
    while px < 8 and cells * px * 2 <= TARGET_SIDE:
        px *= 2
    return _Frame(x0, z0, x1, z1, per_cell, px)


def _rasters(
    m: DimensionMap, footprint: Mapping[str, str], f: _Frame
) -> tuple[NDArray[np.bool_], NDArray[np.int64], NDArray[np.int64]]:
    """Per cell: land, built blocks, of which below ground."""
    land = np.zeros(f.cells, bool)
    chunks = footprint_chunks(footprint)
    xs, zs = chunks[:, 0], chunks[:, 1]
    inside = (xs >= f.x0) & (xs <= f.x1) & (zs >= f.z0) & (zs <= f.z1)
    land[(zs[inside] - f.z0) // f.per_cell, (xs[inside] - f.x0) // f.per_cell] = True
    built = np.zeros(f.cells, np.int64)
    below = np.zeros(f.cells, np.int64)
    for i in range(len(m.x)):
        if f.contains(m.x[i], m.z[i]):
            cz, cx = (m.z[i] - f.z0) // f.per_cell, (m.x[i] - f.x0) // f.per_cell
            built[cz, cx] += m.built[i]
            below[cz, cx] += m.below[i]
            land[cz, cx] = True  # presence counts as land even without a footprint
    return land, built, below


def _picture(grid: Grid, f: _Frame, sites: Sequence[tuple[int, BuildSite]]) -> bytes:
    img: Grid = np.repeat(np.repeat(grid, f.px, 0), f.px, 1)
    height, width = shape2(img)
    per_px = f.blocks_per_pixel
    for n, s in sites:
        left = round((s.bbox[0] - f.x0 * 16) / per_px) - 1
        top = round((s.bbox[1] - f.z0 * 16) / per_px) - 1
        right = round((s.bbox[2] + 1 - f.x0 * 16) / per_px)
        bottom = round((s.bbox[3] + 1 - f.z0 * 16) / per_px)
        if right < 0 or bottom < 0 or left >= width or top >= height:
            continue
        _outline(img, top, left, bottom, right)
        _label(img, n, left, top)
    return indexed_png(width, height, img.tobytes(), PALETTE)


def chunk_maps(
    m: DimensionMap,
    footprint: Mapping[str, str],
    sites: Sequence[tuple[int, BuildSite]],
    *,
    underground: bool,
) -> ChunkMaps | None:
    """The maps of one dimension; None when nothing was built there. `sites` are the build
    sites in this dimension with their number."""
    area, elsewhere = _main_area(m)
    if not area:
        return None
    f = _frame(m, area)
    land, built, below = _rasters(m, footprint, f)
    per_chunk = built / (f.per_cell * f.per_cell)
    base: Grid = np.where(land, _LAND, _PAPER).astype(np.uint8)
    orange = base.copy()
    for step, threshold in enumerate(BUILT_STEPS):
        orange[per_chunk >= threshold] = _ORANGE + step
    split: Grid | None = None
    if underground:
        split = base.copy()
        share = np.divide(below, built, out=np.zeros(built.shape), where=built > 0)
        many = per_chunk >= MIN_BUILT
        bounds = (-1.0, *BELOW_STEPS, 2.0)
        for step in range(5):
            split[many & (share >= bounds[step]) & (share < bounds[step + 1])] = _SPLIT + step
    return ChunkMaps(
        built=_picture(orange, f, sites),
        underground=_picture(split, f, sites) if split is not None else None,
        box=(f.x0 * 16, f.z0 * 16, f.x1 * 16 + 15, f.z1 * 16 + 15),
        blocks_per_pixel=f.blocks_per_pixel,
        elsewhere=elsewhere,
    )
