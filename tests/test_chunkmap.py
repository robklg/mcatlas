"""Chunk maps: generated land, building per chunk, build sites outlined and numbered."""

import base64
import io
from pathlib import Path

import numpy as np
from builders import make_world
from PIL import Image

from mcatlas.adapters.source_folder import FolderSource
from mcatlas.core.analyze.regions import analyze_regions
from mcatlas.core.build import BuildSite, DimensionMap
from mcatlas.core.chunkmap import MARGIN, PALETTE, chunk_maps, footprint_chunks
from mcatlas.core.discovery import classify

OVERWORLD = "minecraft:overworld"


def _rgb(index: int) -> tuple[int, int, int]:
    r, g, b = PALETTE[index * 3 : index * 3 + 3]
    return (r, g, b)


PAPER, LAND, INK = _rgb(0), _rgb(1), _rgb(2)


def _png(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.load()
    return img


def _footprint(chunks: list[tuple[int, int]]) -> dict[str, str]:
    by_region: dict[str, np.ndarray] = {}
    for x, z in chunks:
        bits = by_region.setdefault(f"{x // 32},{z // 32}", np.zeros(1024, bool))
        bits[(x % 32) + 32 * (z % 32)] = True
    return {k: base64.b64encode(np.packbits(v).tobytes()).decode() for k, v in by_region.items()}


def _site(x0: int, z0: int, x1: int, z1: int) -> BuildSite:
    return BuildSite(
        dimension=OVERWORLD,
        x=(x0 + x1) // 2,
        z=(z0 + z1) // 2,
        bbox=(x0, z0, x1, z1),
        chunks=1,
        built=100,
        below=0,
        no_ground=0,
        min_y=60,
        max_y=70,
        pct_below=0.0,
        hours_nearby=1.0,
    )


def test_footprint_round_trips_through_region_bits():
    chunks = [(0, 0), (31, 31), (-1, 5), (40, -33)]
    found = {(int(x), int(z)) for x, z in footprint_chunks(_footprint(chunks))}
    assert found == set(chunks)
    assert footprint_chunks({}).shape == (0, 2)


def test_built_map_shows_land_building_and_numbered_sites():
    m = DimensionMap(
        key=OVERWORLD,
        x=[0, 1, 2, 5_000],
        z=[0, 0, 0, 5_000],
        built=[5, 500, 50_000, 900],  # the last one: a teleport far away
        below=[0, 400, 0, 0],
        minutes=[1, 1, 1, 1],
    )
    land = [(x, z) for x in range(-3, 6) for z in range(-3, 4)]
    maps = chunk_maps(m, _footprint(land), [(3, _site(0, 0, 47, 15))], underground=True)
    assert maps is not None
    assert maps.elsewhere == 1 and maps.blocks_per_pixel == 2  # 8 pixels per chunk
    assert maps.box == (-MARGIN * 16, -MARGIN * 16, (2 + MARGIN) * 16 + 15, MARGIN * 16 + 15)
    img = _png(maps.built)
    side = (2 * MARGIN + 3) * 8
    assert img.size == (side, (2 * MARGIN + 1) * 8)

    def at(chunk_x: int, chunk_z: int) -> object:
        return img.getpixel(((chunk_x + MARGIN) * 8 + 4, (chunk_z + MARGIN) * 8 + 4))

    assert at(0, 0) == _rgb(3) and at(1, 0) == _rgb(5) and at(2, 0) == _rgb(7)  # darker
    assert at(-2, 2) == LAND and at(-7, -7) == PAPER
    assert img.getpixel((MARGIN * 8 - 1, MARGIN * 8 + 4)) == INK  # the site's outline
    assert INK in {img.getpixel((x, y)) for x in range(MARGIN * 8 - 1, MARGIN * 8 + 8)
                   for y in range(MARGIN * 8 - 13, MARGIN * 8 - 2)}  # its number above  # fmt: skip

    under = _png(maps.underground or b"")
    assert under.getpixel(((1 + MARGIN) * 8 + 4, MARGIN * 8 + 4)) == _rgb(8 + 4)  # 80% below
    assert under.getpixel(((2 + MARGIN) * 8 + 4, MARGIN * 8 + 4)) == _rgb(8)  # all above
    assert under.getpixel((MARGIN * 8 + 4, MARGIN * 8 + 4)) == LAND  # too little building


def test_no_map_without_building_and_no_underground_unless_asked():
    empty = DimensionMap(key=OVERWORLD, x=[0], z=[0], built=[0], below=[0], minutes=[30])
    assert chunk_maps(empty, {}, [], underground=True) is None
    m = DimensionMap(key=OVERWORLD, x=[0], z=[0], built=[50], below=[0], minutes=[1])
    maps = chunk_maps(m, {}, [], underground=False)
    assert maps is not None and maps.underground is None


def test_large_areas_get_several_chunks_per_pixel():
    xs = list(range(0, 3000, 4))
    m = DimensionMap(
        key=OVERWORLD, x=xs, z=[0] * len(xs), built=[50] * len(xs), below=[0] * len(xs),
        minutes=[1] * len(xs),
    )  # fmt: skip
    maps = chunk_maps(m, {}, [], underground=False)
    assert maps is not None and maps.blocks_per_pixel == 64 and maps.elsewhere == 0
    assert _png(maps.built).width <= 1024


def test_region_analysis_keeps_the_footprint(tmp_path: Path):
    make_world(tmp_path / "w", level_name="w", chunks={"region": [(3, 4, 1_700_000_000)]})
    source = FolderSource("t", tmp_path)
    [listing] = list(source.scan())
    with source.open(listing) as files:
        facts = analyze_regions(files, classify(listing.files))
    source.close()
    [dim] = facts.dimensions
    assert {(int(x), int(z)) for x, z in footprint_chunks(dim.footprint)} == {(3, 4)}


def test_scattered_building_is_drawn_together_but_a_teleport_is_not():
    m = DimensionMap(
        key=OVERWORLD,
        x=[0, 1, 60, 150, 90_000],
        z=[0, 0, 40, -30, 0],
        built=[400, 400, 300, 200, 5_000],  # most building far away, alone
        below=[0] * 5,
        minutes=[1] * 5,
    )
    maps = chunk_maps(m, {}, [], underground=False)
    assert maps is not None
    assert maps.elsewhere == 4 and maps.box[0] > 80_000 * 16  # the biggest group wins...
    m = m.model_copy(update={"built": [4_000, 4_000, 300, 200, 5_000]})
    maps = chunk_maps(m, {}, [], underground=False)
    assert maps is not None and maps.elsewhere == 1  # ...and nearby groups join it
    assert maps.box == (
        (0 - MARGIN) * 16,
        (-30 - MARGIN) * 16,
        (150 + MARGIN) * 16 + 15,
        (40 + MARGIN) * 16 + 15,
    )
