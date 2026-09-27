"""In-game maps: palette, PNG images, mosaics and which maps are shown."""

import io
from pathlib import Path

import numpy as np
import pytest
from builders import map_dat
from PIL import Image

from mcatlas.adapters.store_sqlite import SqliteFactStore
from mcatlas.core.discovery import classify
from mcatlas.core.facts import InGameMap
from mcatlas.core.maps import (
    MAX_SHOWN,
    PALETTE,
    MapError,
    area,
    image,
    mosaic,
    parse_map,
    pictures,
)
from mcatlas.core.model import WorldListing
from mcatlas.core.nbt import decode_file
from mcatlas.core.png import indexed_png

GRASS = 1 * 4 + 1  # base colour 1, normal brightness
WATER = 12 * 4 + 2  # base colour 12, high brightness


def _map(map_id: int, data: bytes) -> tuple[InGameMap, np.ndarray]:
    return parse_map(map_id, decode_file(data))


def _png(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def test_palette_follows_the_game():
    assert len(PALETTE) == 62 * 4 * 3
    assert PALETTE[GRASS * 3 : GRASS * 3 + 3] == bytes(
        (0x7F * 220 // 255, 0xB2 * 220 // 255, 0x38 * 220 // 255)
    )
    assert PALETTE[WATER * 3 : WATER * 3 + 3] == bytes((0x40, 0x40, 0xFF))


def test_indexed_png_reads_back():
    data = indexed_png(
        3, 2, bytes([0, 1, 2, 2, 1, 0]), bytes([0, 0, 0, 255, 0, 0, 0, 255, 0]), b"\0"
    )
    img = _png(data).convert("RGBA")
    assert img.size == (3, 2)
    assert img.getpixel((0, 0)) == (0, 0, 0, 0)  # entry 0 transparent
    assert img.getpixel((1, 0)) == (255, 0, 0, 255) and img.getpixel((0, 1)) == (0, 255, 0, 255)
    with pytest.raises(ValueError, match="pixels"):
        indexed_png(3, 2, b"\0", bytes(3))


def test_parse_map_reads_centre_scale_and_colours():
    info, pixels = _map(7, map_dat(64, -64, color=250, scale=2, dimension=-1, locked=True))
    assert (info.id, info.x, info.z, info.scale) == (7, 64, -64, 2)
    assert info.dimension == "minecraft:the_nether" and info.locked
    assert info.filled == 0  # 250 is past the palette: treated as no colour
    info, pixels = _map(8, map_dat(color=WATER))
    assert info.filled == 128 * 128 and int(pixels[0]) == WATER
    assert area(info) == (-64, -64, 63, 63)
    with pytest.raises(MapError):
        parse_map(9, {"data": {"scale": 0}})


def test_mosaic_places_maps_and_keeps_detail_on_top():
    coarse = _map(1, map_dat(64, 64, color=GRASS, scale=1))  # 256 blocks, 2 per pixel
    fine = _map(2, map_dat(0, 0, color=WATER))
    box, per_px, pixels = mosaic([fine, coarse])
    assert box == (-64, -64, 191, 191) and per_px == 1 and pixels.shape == (256, 256)
    assert pixels[0, 0] == WATER and pixels[127, 127] == WATER  # fine map lies on top
    assert pixels[200, 200] == GRASS
    box, per_px, pixels = mosaic([fine, coarse], max_side=64)
    assert per_px == 4 and pixels.shape == (64, 64) and pixels[10, 10] == WATER


def test_pictures_show_new_filled_maps_once_and_a_mosaic_per_dimension():
    maps = [_map(i, map_dat(128 * i, 0, color=4 + i)) for i in range(30)]  # all different
    maps.append(_map(99, map_dat(0, 0)))  # never used: not shown
    maps.append(_map(98, map_dat(0, 0, color=GRASS, dimension="minecraft:the_end")))
    shown, mosaics, images = pictures(maps)
    ids = [m.id for m in shown]
    assert len(shown) == MAX_SHOWN and ids[0] == 98 and 99 not in ids
    assert ids == sorted(ids, reverse=True)
    assert [m.dimension for m in mosaics] == ["minecraft:overworld"]  # the End: one place only
    assert mosaics[0].maps == 30 and mosaics[0].image == "mosaic-overworld.png"
    assert set(images) == {m.image for m in shown} | {"mosaic-overworld.png"}
    assert _png(images["map_98.png"]).size == (128, 128)

    same = [_map(1, map_dat(color=GRASS)), _map(2, map_dat(color=GRASS))]  # a copied map
    shown, mosaics, _ = pictures(same)
    assert [m.id for m in shown] == [2] and not mosaics


def test_image_of_a_map_is_its_colours():
    _, pixels = _map(1, map_dat(color=WATER))
    img = _png(image(pixels.reshape(128, 128))).convert("RGBA")
    assert img.getpixel((5, 5)) == (0x40, 0x40, 0xFF, 255)


def test_store_replaces_an_analyzers_images(tmp_path: Path):
    store = SqliteFactStore(tmp_path / "state.sqlite")
    listing = WorldListing("archive", "lab", ())
    store.record_world(listing, classify(()))
    wid = listing.world_id
    store.save_asset(wid, "icon.png", "f", b"icon")
    store.replace_assets(wid, "maps/", "f", {"map_1.png": b"1", "map_2.png": b"2"})
    store.replace_assets(wid, "maps/", "g", {"map_2.png": b"two"})  # map 1 is gone
    assert store.asset_group("maps/") == {wid: {"map_2.png": b"two"}}
    assert store.assets("icon.png") == {wid: b"icon"}  # other assets stay
    store.close()


def test_a_far_away_map_does_not_shrink_the_mosaic():
    near = [_map(i, map_dat(128 * i, 0, color=4 + i)) for i in range(3)]
    far = _map(9, map_dat(0, 10_000_000, color=40))
    other = [_map(20 + i, map_dat(50_000 + 128 * i, 0, color=60 + i)) for i in range(2)]
    shown, mosaics, _ = pictures([*near, far, *other])
    assert [(m.maps, m.blocks_per_pixel) for m in mosaics] == [(3, 1), (2, 1)]
    assert [m.image for m in mosaics] == ["mosaic-overworld.png", "mosaic-overworld-2.png"]
    assert 9 in [m.id for m in shown]  # still shown on its own
    assert mosaics[1].box == (49_936, -64, 50_191, 63)
