"""In-game maps: the paper maps players fill by walking around, stored as data/map_<n>.dat.

Each map is 128 × 128 colour indexes into the game's fixed map palette (index = base colour × 4
+ brightness; 0-3 are transparent). The palette only ever grew, so the newest one draws maps of
every version. A map covers 128 × 2^scale blocks around its centre, north up.

Worlds downloaded from others can hold thousands of maps (map art, a whole city), so a world
shows a mosaic per dimension with every filled map in its place, plus a few loose maps.
"""

import hashlib
import re
from collections.abc import Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

from mcatlas.core.facts import InGameMap, MapMosaic
from mcatlas.core.formats.access import bool_, compound, int_
from mcatlas.core.model import NETHER, OVERWORLD, THE_END
from mcatlas.core.nbt import NbtCompound
from mcatlas.core.npx import shape2
from mcatlas.core.png import indexed_png

MAP_SIZE: Final = 128
MAX_SHOWN: Final = 24
"""Loose maps shown per world: the newest (highest numbers) first, without duplicates."""
MOSAIC_MAX_SIDE: Final = 2048
"""Mosaics are scaled down (by powers of two) until they fit."""
MAX_MOSAICS: Final = 3
"""Mosaics per dimension: the areas with the most maps."""
NEAR: Final = 512
"""Maps closer than this many blocks belong to one area (one mosaic)."""
MAP_FILE: Final = re.compile(r"^data/(?:map_|minecraft/maps/)(\d+)\.dat$")
"""`data/map_<n>.dat`; since 26.1 `data/minecraft/maps/<n>.dat`."""

# net.minecraft.world.level.material.MapColor, checked against the 26.3 client.
BASE_COLORS: Final = (
    0x000000, 0x7FB238, 0xF7E9A3, 0xC7C7C7, 0xFF0000, 0xA0A0FF, 0xA7A7A7, 0x007C00,
    0xFFFFFF, 0xA4A8B8, 0x976D4D, 0x707070, 0x4040FF, 0x8F7748, 0xFFFCF5, 0xD87F33,
    0xB24CD8, 0x6699D8, 0xE5E533, 0x7FCC19, 0xF27FA5, 0x4C4C4C, 0x999999, 0x4C7F99,
    0x7F3FB2, 0x334CB2, 0x664C33, 0x667F33, 0x993333, 0x191919, 0xFAEE4D, 0x5CDBD5,
    0x4A80FF, 0x00D93A, 0x815631, 0x700200, 0xD1B1A1, 0x9F5224, 0x95576C, 0x706C8A,
    0xBA8524, 0x677535, 0xA04D4E, 0x392923, 0x876B62, 0x575C5C, 0x7A4958, 0x4C3E5C,
    0x4C3223, 0x4C522A, 0x8E3C2E, 0x251610, 0xBD3031, 0x943F61, 0x5C191D, 0x167E86,
    0x3A8E8C, 0x562C3E, 0x14B485, 0x646464, 0xD8AF93, 0x7FA796,
)  # fmt: skip
BRIGHTNESS: Final = (180, 220, 255, 135)
"""MapColor.Brightness: LOW, NORMAL, HIGH, LOWEST."""
COLORS: Final = 4 * len(BASE_COLORS)


def _palette() -> bytes:
    out = bytearray()
    for rgb in BASE_COLORS:
        for b in BRIGHTNESS:
            out += bytes(((rgb >> shift) & 0xFF) * b // 255 for shift in (16, 8, 0))
    return bytes(out)


PALETTE: Final = _palette()
ALPHA: Final = bytes(4)
"""Palette entries 0-3 (no colour) are transparent."""

_LEGACY_DIMENSIONS: Final = {0: OVERWORLD, -1: NETHER, 1: THE_END}
_DIMENSION_ORDER: Final = (OVERWORLD, NETHER, THE_END)

type Pixels = NDArray[np.uint8]


class MapError(ValueError):
    pass


def parse_map(map_id: int, root: NbtCompound) -> tuple[InGameMap, Pixels]:
    data = compound(root, "data")
    if data is None:
        raise MapError("no data compound")
    colors = data.get("colors")
    if not isinstance(colors, np.ndarray) or colors.size != MAP_SIZE * MAP_SIZE:
        raise MapError("no 128 × 128 colours")
    pixels: Pixels = colors.astype(np.int16).astype(np.uint8)  # signed bytes as 0-255
    pixels[pixels >= COLORS] = 0
    raw_dim = data.get("dimension")
    if isinstance(raw_dim, str):
        dimension = raw_dim
    elif isinstance(raw_dim, int):
        dimension = _LEGACY_DIMENSIONS.get(raw_dim, f"legacy:{raw_dim}")
    else:
        dimension = OVERWORLD
    info = InGameMap(
        id=map_id,
        scale=min(max(int_(data, "scale") or 0, 0), 4),
        dimension=dimension,
        x=int_(data, "xCenter") or 0,
        z=int_(data, "zCenter") or 0,
        locked=bool_(data, "locked") or False,
        filled=int(np.count_nonzero(pixels >= 4)),
    )
    return info, pixels


def image(pixels: Pixels) -> bytes:
    """A map (or mosaic) as PNG; `pixels` is a 2-D array of palette indexes."""
    height, width = shape2(pixels)
    return indexed_png(width, height, pixels.tobytes(), PALETTE, ALPHA)


def area(m: InGameMap) -> tuple[int, int, int, int]:
    """Blocks the map covers: min_x, min_z, max_x, max_z (inclusive)."""
    size = MAP_SIZE << m.scale
    x0, z0 = m.x - size // 2, m.z - size // 2
    return (x0, z0, x0 + size - 1, z0 + size - 1)


def mosaic(
    maps: Sequence[tuple[InGameMap, Pixels]], max_side: int = MOSAIC_MAX_SIDE
) -> tuple[tuple[int, int, int, int], int, Pixels]:
    """Maps laid out in the world: (area in blocks, blocks per pixel, pixels).

    Coarser maps lie below finer ones, newer maps (higher numbers) on top of older ones."""
    boxes = [area(m) for m, _ in maps]
    x0, z0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, z1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    per_px = 1
    while max(x1 - x0 + 1, z1 - z0 + 1) > max_side * per_px:
        per_px *= 2
    canvas: Pixels = np.zeros(((z1 - z0) // per_px + 1, (x1 - x0) // per_px + 1), np.uint8)
    for m, pixels in sorted(maps, key=lambda t: (-t[0].scale, t[0].id)):
        grid = pixels.reshape(MAP_SIZE, MAP_SIZE)  # [z][x]
        block = 1 << m.scale
        if block >= per_px:
            grid = np.repeat(np.repeat(grid, block // per_px, 0), block // per_px, 1)
        else:
            grid = grid[:: per_px // block, :: per_px // block]
        mx, mz, _, _ = area(m)
        top, left = (mz - z0) // per_px, (mx - x0) // per_px
        target = canvas[top : top + grid.shape[0], left : left + grid.shape[1]]
        grid = grid[: target.shape[0], : target.shape[1]]
        mask = grid >= 4
        target[mask] = grid[mask]
    return (x0, z0, x1, z1), per_px, canvas


def _dimension_key(dimension: str) -> tuple[int, str]:
    order = _DIMENSION_ORDER.index(dimension) if dimension in _DIMENSION_ORDER else 3
    return (order, dimension)


def mosaic_name(dimension: str, n: int = 0) -> str:
    base = "mosaic-" + re.sub(r"[^a-z0-9]+", "-", dimension.rsplit(":", 1)[-1].lower())
    return f"{base}-{n + 1}.png" if n else f"{base}.png"


def areas(maps: Sequence[tuple[InGameMap, Pixels]]) -> list[list[tuple[InGameMap, Pixels]]]:
    """Maps grouped into areas of maps near each other, the area with the most maps first.

    A map far from the rest (map art in a corner of the world) would otherwise shrink a
    mosaic until nothing is recognizable."""
    parent = list(range(len(maps)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell_owner: dict[tuple[int, int], int] = {}
    for i, (m, _) in enumerate(maps):
        x0, z0, x1, z1 = area(m)
        for cx in range((x0 - NEAR // 2) // NEAR, (x1 + NEAR // 2) // NEAR + 1):
            for cz in range((z0 - NEAR // 2) // NEAR, (z1 + NEAR // 2) // NEAR + 1):
                other = cell_owner.setdefault((cx, cz), i)
                parent[root(i)] = root(other)
    groups: dict[int, list[tuple[InGameMap, Pixels]]] = {}
    for i, t in enumerate(maps):
        groups.setdefault(root(i), []).append(t)
    return sorted(groups.values(), key=lambda g: (-len(g), min(m.id for m, _ in g)))


def pictures(
    maps: Sequence[tuple[InGameMap, Pixels]],
) -> tuple[list[InGameMap], list[MapMosaic], dict[str, bytes]]:
    """The loose maps to show, the mosaics, and their images by name."""
    filled = sorted((t for t in maps if t[0].filled), key=lambda t: -t[0].id)
    images: dict[str, bytes] = {}
    shown: list[InGameMap] = []
    seen: set[bytes] = set()
    for m, pixels in filled:
        digest = hashlib.blake2b(pixels.tobytes(), digest_size=16).digest()
        if digest in seen:
            continue
        seen.add(digest)
        if len(shown) < MAX_SHOWN:
            name = f"map_{m.id}.png"
            images[name] = image(pixels.reshape(MAP_SIZE, MAP_SIZE))
            shown.append(m.model_copy(update={"image": name}))
    mosaics: list[MapMosaic] = []
    for dimension in sorted({m.dimension for m, _ in filled}, key=_dimension_key):
        in_dim = [t for t in filled if t[0].dimension == dimension]
        # One place only: the loose maps show it already.
        groups = [g for g in areas(in_dim) if len({area(m) for m, _ in g}) > 1]
        for n, group in enumerate(groups[:MAX_MOSAICS]):
            box, per_px, pixels = mosaic(group)
            name = mosaic_name(dimension, n)
            images[name] = image(pixels)
            mosaics.append(
                MapMosaic(
                    dimension=dimension,
                    image=name,
                    box=box,
                    blocks_per_pixel=per_px,
                    maps=len(group),
                )
            )
    return shown, mosaics, images
