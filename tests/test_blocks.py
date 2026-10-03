import numpy as np
import pytest
from builders import Byte, chunk_nbt, nbt, pack, region
from hypothesis import given, settings
from hypothesis import strategies as st

from mcatlas.core.anvil.chunk import ChunkError, parse_chunk, unpack
from mcatlas.core.blocks import RegionJob, RegionScan, scan_region, smooth_surface
from mcatlas.core.nbt import decode

STONE = "minecraft:stone"
GRASS = "minecraft:grass_block"
GROUND = [(0, 59, STONE), (60, 60, GRASS)]  # natural surface at y = 60
VISITED = 36_000  # half an hour of player presence nearby


@settings(max_examples=60)
@given(bits=st.integers(1, 15), spanning=st.booleans(), seed=st.integers(0, 2**32 - 1))
def test_unpack_matches_naive_packer(bits, spanning, seed):
    values = np.random.default_rng(seed).integers(0, 2**bits, 4096)
    packed = pack(values.tolist(), bits, spanning=spanning)
    assert unpack(packed, bits, spanning=spanning).tolist() == values.tolist()


def test_unpack_rejects_short_data():
    with pytest.raises(ChunkError):
        unpack(np.zeros(3, dtype=np.int64), 5, spanning=False)


def test_palette_entries_saved_by_26_3():
    """26.3 writes palette entries as {id, properties} instead of {Name, Properties}."""
    raw = chunk_nbt(0, 0, {(1, 70, 2): "minecraft:glass"}, fill=GROUND)
    for section in raw["sections"].items:
        for entry in section["block_states"]["palette"].items:
            entry["id"] = entry.pop("Name")
    names = {n for sec in parse_chunk(decode(nbt(raw))).sections for n in sec.palette}
    assert {"minecraft:glass", STONE, GRASS} <= names


@pytest.mark.parametrize(
    ("status", "populated", "full"),
    [
        ("minecraft:features", None, False),  # the edge of explored land
        ("minecraft:features", 1, True),  # upgraded from before 1.13, not lit yet
        ("minecraft:empty", 1, True),  # upgraded, waiting to be extended below y=0
        ("minecraft:empty", 0, False),
    ],
)
def test_chunks_upgraded_from_the_old_format(status, populated, full):
    raw = chunk_nbt(0, 0, {}, fill=GROUND, status=status)
    if populated is not None:
        raw["TerrainPopulated"] = Byte(populated)
    assert parse_chunk(decode(nbt(raw))).full is full


@pytest.mark.parametrize("data_version", [3465, 2230, 2586])  # 1.20.1, 1.15.2 (spanning), 1.16.5
def test_parse_chunk_modern_and_legacy_layouts(data_version):
    chunk = parse_chunk(
        decode(
            nbt(
                chunk_nbt(
                    3,
                    -2,
                    {(1, 70, 2): "minecraft:glass", (4, 5, 6): "minecraft:diamond_block"},
                    fill=GROUND,
                    data_version=data_version,
                    structures=["mineshaft"],
                    inhabited=4800,
                )
            )
        )
    )
    assert (chunk.x, chunk.z, chunk.full, chunk.inhabited_ticks) == (3, -2, True, 4800)
    assert chunk.structures == ("mineshaft",)
    names = {n for sec in chunk.sections for n in sec.palette}
    assert {"minecraft:glass", "minecraft:diamond_block", STONE, GRASS} <= names
    sec4 = next(s for s in chunk.sections if s.y == 4)  # y 64..79 holds the glass
    assert sec4.indices is not None
    assert sec4.palette[int(sec4.indices[((70 - 64) * 16 + 2) * 16 + 1])] == "minecraft:glass"
    sec0 = next(s for s in chunk.sections if s.y == 0)
    assert sec0.indices is not None  # stone + one diamond block


def test_pre_flattening_chunks_are_rejected():
    with pytest.raises(ChunkError, match=r"pre-1\.13"):
        parse_chunk({"DataVersion": 1343, "Level": {}})


def _scan(chunks: list[dict]) -> RegionScan:
    data = region({(c["xPos"] & 31, c["zPos"] & 31): (c, 1_693_591_200) for c in chunks})
    return scan_region(RegionJob("region/r.0.0.mca", 0, 0, data))


def _row(scan: RegionScan, x: int, z: int):
    return next(r for r in scan.rows if (r.x, r.z) == (x, z))


def test_house_above_and_cellar_below_ground():
    house = {(5, y, 5): "minecraft:stone_bricks" for y in (61, 62, 63)}
    cellar = {(8, 50, 8): "minecraft:oak_planks"}
    scan = _scan([chunk_nbt(0, 0, house | cellar, fill=GROUND, inhabited=VISITED)])
    row = _row(scan, 0, 0)
    assert (row.built, row.below, row.no_ground) == (4, 1, 0)
    assert (row.min_y, row.max_y) == (50, 63)
    assert scan.blocks == {"minecraft:stone_bricks": 3, "minecraft:oak_planks": 1}
    assert scan.built_by_section == {3: 4}  # y 48..63


def test_open_pit_counts_as_underground_but_wide_valley_does_not():
    pit = {
        (x, y, z): "minecraft:air" for x in range(4, 8) for z in range(4, 8) for y in (58, 59, 60)
    }
    pit |= {(x, 57, z): "minecraft:glass" for x in range(4, 8) for z in range(4, 8)}
    valley_floor = [(0, 40, STONE)]
    mountain = [(0, 80, STONE)]
    house = {(8, 41, 8): "minecraft:oak_planks"}
    scan = _scan(
        [
            chunk_nbt(1, 0, pit, fill=GROUND, inhabited=VISITED),
            chunk_nbt(3, 0, {}, fill=mountain),
            chunk_nbt(4, 0, {}, fill=valley_floor),
            chunk_nbt(5, 0, house, fill=valley_floor, inhabited=VISITED),
            chunk_nbt(6, 0, {}, fill=valley_floor),
            chunk_nbt(7, 0, {}, fill=mountain),
        ]
    )
    pit_row = _row(scan, 1, 0)
    assert (pit_row.built, pit_row.below) == (16, 16)  # filled in by the closing
    valley_row = _row(scan, 5, 0)
    assert (valley_row.built, valley_row.below) == (1, 0)


def test_converted_chunks_assume_the_structures_of_their_dimension():
    """Old-format chunks (a Wii U world) have no structure references: a nether fortress's
    own blocks are assumed generated, other building blocks still count."""
    blocks = {(5, 61, 5): "minecraft:nether_bricks", (6, 61, 6): "minecraft:oak_planks"}

    def scan(*, legacy: bool, likely: tuple[str, ...] = (), strongholds=()) -> RegionScan:
        raw = chunk_nbt(0, 0, blocks, fill=GROUND, inhabited=VISITED)
        if legacy:
            raw["TerrainPopulated"] = Byte(1)
        data = region({(0, 0): (raw, 1_693_591_200)})
        return scan_region(RegionJob("r.0.0.mca", 0, 0, data, likely, strongholds))

    assert scan(legacy=True, likely=("likely_fortress",)).blocks == {"minecraft:oak_planks": 1}
    # Without the assumption, or in a chunk saved by Java itself, both count.
    assert len(scan(legacy=True).blocks) == 2
    assert len(scan(legacy=False, likely=("likely_fortress",)).blocks) == 2

    bricks = {(5, 40, 5): "minecraft:stone_bricks", (6, 40, 6): "minecraft:oak_planks"}
    for start, expected in (((7, -7), 1), ((8, 0), 2)):
        raw = chunk_nbt(0, 0, bricks, fill=GROUND, inhabited=VISITED)
        raw["TerrainPopulated"] = Byte(1)
        data = region({(0, 0): (raw, 1_693_591_200)})
        result = scan_region(RegionJob("r.0.0.mca", 0, 0, data, (), (start,)))
        assert len(result.blocks) == expected  # within 7 chunks of a stronghold's start


def test_void_structures_dungeons_and_proto_chunks():
    scan = _scan(
        [
            # sky island, no ground
            chunk_nbt(10, 0, {(0, 64, 0): "minecraft:white_wool"}, inhabited=VISITED),
            chunk_nbt(
                12,
                0,
                {(1, 30, 1): "minecraft:oak_planks", (2, 30, 2): "minecraft:quartz_block"},
                fill=GROUND,
                structures=["mineshaft"],
                inhabited=VISITED,
            ),
            chunk_nbt(
                14,
                0,
                {(3, 20, 3): "minecraft:spawner", (3, 20, 4): "minecraft:cobblestone"},
                fill=GROUND,
                inhabited=VISITED,
            ),
            # the same dungeon reaching into the next chunk (no spawner of its own)
            chunk_nbt(
                15, 0, {(0, 20, 4): "minecraft:mossy_stone_bricks"}, fill=GROUND, inhabited=VISITED
            ),
            chunk_nbt(16, 0, {(0, 64, 0): "minecraft:glass"}, status="minecraft:features"),
        ]
    )
    assert (scan.chunks_full, scan.chunks_partial) == (4, 1)
    void = _row(scan, 10, 0)
    assert (void.built, void.no_ground, void.below) == (1, 1, 0)
    shaft = _row(scan, 12, 0)
    assert (shaft.built, shaft.structure_built, shaft.below) == (1, 1, 1)
    dungeon = _row(scan, 14, 0)
    assert (dungeon.built, dungeon.structure_built) == (0, 2)
    assert scan.structures == {"mineshaft": 1, "dungeon": 1}
    assert scan.blocks == {
        "minecraft:white_wool": 1,
        "minecraft:quartz_block": 1,
        "minecraft:mossy_stone_bricks": 1,
    }
    assert _row(scan, 15, 0).built == 1  # next to a dungeon, but not a dungeon block
    assert scan.structure_blocks == {
        "minecraft:oak_planks": 1,
        "minecraft:spawner": 1,
        "minecraft:cobblestone": 1,
    }


def test_inhabited_chunks_are_kept_without_building():
    scan = _scan(
        [chunk_nbt(0, 0, {}, fill=GROUND, inhabited=24_000), chunk_nbt(1, 0, {}, fill=GROUND)]
    )
    assert [(r.x, r.inhabited) for r in scan.rows] == [(0, 24_000)]


def test_corrupt_chunk_is_counted_not_fatal():
    good = chunk_nbt(0, 0, {(0, 61, 0): "minecraft:glass"}, fill=GROUND)
    data = bytearray(region({(0, 0): (good, 1), (1, 0): (good | {"xPos": 1}, 1)}))
    second = int.from_bytes(data[4:7], "big") * 4096  # slot 1's sector offset
    data[second + 5 : second + 40] = b"\xff" * 35
    scan = scan_region(RegionJob("r.0.0.mca", 0, 0, bytes(data)))
    assert (scan.chunks_full, scan.chunks_failed) == (1, 1)
    assert scan.errors and "slot 1" in scan.errors[0]


def test_smooth_surface_fills_narrow_pits_only():
    h = np.full((64, 64), 60.0)
    h[10:14, 10:14] = 50.0  # pit, 4 wide
    h[:, 40:64] = 30.0  # wide valley along one side
    h[0:3, 0:3] = -np.inf  # no ground (void)
    out = smooth_surface(h)
    assert (out[10:14, 10:14] == 60).all()
    assert (out[:, 50:64] == 30).all()
    assert np.isneginf(out[0:3, 0:3]).all()  # no ground stays no ground


def test_unvisited_chunks_keep_unusual_blocks_but_not_village_blocks():
    village = {(1, 61, 1): "minecraft:oak_planks", (2, 61, 2): "minecraft:hay_block"}
    far_build = {(5, 70, 5): "minecraft:black_concrete"}
    scan = _scan([chunk_nbt(0, 0, village | far_build, fill=GROUND, inhabited=2_000)])
    row = _row(scan, 0, 0)
    assert (row.built, row.structure_built) == (1, 2)
    assert scan.blocks == {"minecraft:black_concrete": 1}


def test_dungeon_cobblestone_in_the_neighbouring_chunk_is_not_building():
    scan = _scan(
        [
            chunk_nbt(0, 0, {(15, 20, 3): "minecraft:spawner"}, fill=GROUND, inhabited=VISITED),
            chunk_nbt(1, 0, {(0, 20, 3): "minecraft:cobblestone"}, fill=GROUND, inhabited=VISITED),
            chunk_nbt(3, 0, {(0, 20, 3): "minecraft:cobblestone"}, fill=GROUND, inhabited=VISITED),
        ]
    )
    assert _row(scan, 1, 0).structure_built == 1
    assert _row(scan, 3, 0).built == 1  # two chunks away: somebody placed it
    assert scan.structures == {"dungeon": 1}


def test_modded_blocks_are_counted_apart():
    blocks = {(0, 61, 0): "witherstormmod:tainted_flesh_block", (1, 61, 0): "minecraft:glass"}
    scan = _scan([chunk_nbt(0, 0, blocks, fill=GROUND, inhabited=VISITED)])
    assert scan.blocks == {"minecraft:glass": 1}
    assert scan.modded == {"witherstormmod:tainted_flesh_block": 1}


def test_rows_carry_the_chunk_save_time():
    scan = _scan([chunk_nbt(0, 0, {(0, 61, 0): "minecraft:glass"}, fill=GROUND, inhabited=VISITED)])
    assert scan.rows[0].saved == 1_693_591_200
