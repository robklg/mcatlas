"""The top requirement: running everything leaves the world source bit-for-bit untouched."""

import io
import json
import os
import stat
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from builders import (
    FAKE_BLUEMAP,
    Byte,
    Long,
    PlayerSpec,
    TypedList,
    chunk_nbt,
    fake_java,
    make_world,
    map_dat,
    nbt_gz,
    region,
)

from mcatlas.adapters import guard, manifest
from mcatlas.adapters.atlas_fs import AtlasFolderWriter
from mcatlas.adapters.bluemap import BlueMapRenderer
from mcatlas.adapters.site_static import StaticSiteWriter
from mcatlas.adapters.source_folder import FolderSource
from mcatlas.adapters.store_sqlite import SqliteFactStore
from mcatlas.adapters.workers import process_mapper
from mcatlas.app.analyze import AnalyzeOptions, analyze_sources
from mcatlas.app.catalog import publish_site
from mcatlas.app.export import export_atlas
from mcatlas.app.render import RenderOptions, render_worlds
from mcatlas.core.formats.console import lce_player_uuid
from mcatlas.core.model import WorldFormat

T0 = 1_676_199_600  # 2023-02-12 11:00 UTC
DAY = 86_400
SAM = "5a305a30-0000-4000-8000-000000000002"
ALEX = "a1e0a1e0-0000-4000-8000-000000000001"


def _chunks(n: int, ts: int, x0: int = 0) -> list[tuple[int, int, int]]:
    return [(x0 + i, 0, ts) for i in range(n)]


def _house_chunk() -> dict:
    """Chunk (5, 0): ground to y 60, a 10-block-high glass tower and a 120-block cellar."""
    tower = {(3, y, 3): "minecraft:glass" for y in range(61, 71)}
    cellar = {(x, 40, z): "minecraft:oak_planks" for x in range(12) for z in range(10)}
    sign = {
        "id": "minecraft:sign",
        "x": 83,
        "y": 61,
        "z": 3,
        "front_text": {"messages": ['"Sams"', '"geheime basis"', '""', '""']},
    }
    return chunk_nbt(
        5,
        0,
        tower | cellar,
        fill=[(0, 60, "minecraft:stone")],
        inhabited=144_000,
        block_entities=[sign],
    )


def _entities_region() -> bytes:
    wolf = {"id": "minecraft:wolf", "CustomName": '{"text":"Bello"}', "Pos": [85.5, 61.0, 4.5]}
    root = {
        "DataVersion": 3465,
        "Position": np.array([5, 0], dtype=np.int32),
        "Entities": TypedList(10, [wolf]),
    }
    return region({(5, 0): (root, 1_693_591_200)})


def _level_data(folder: str, seed: int) -> dict[str, bytes]:
    """The 26.1+ files a Paper server keeps instead of a level.dat for a Multiverse world."""
    gen = {"generator": {"type": "minecraft:noise", "settings": "minecraft:overworld"}}
    return {
        f"{folder}/data/minecraft/world_gen_settings.dat": nbt_gz(
            {
                "DataVersion": 4903,
                "data": {
                    "seed": Long(seed),
                    "dimensions": {"minecraft:overworld": {"generator": gen}},
                },
            }
        ),
        f"{folder}/data/paper/level_overrides.dat": nbt_gz(
            {
                "DataVersion": 4903,
                "data": {
                    "game_type": 0,
                    "game_time": Long(9_000_000),
                    "spawn": {"pos": np.array([0, 58, 0], dtype=np.int32)},
                },
            }
        ),
        f"{folder}/data/minecraft/weather.dat": nbt_gz({"DataVersion": 4903, "data": {}}),
        f"{folder}/paper-world.yml": b"_version: 31\n",
    }


def _build_server_worlds(root: Path) -> None:
    # Downloaded from a Paper server, with the old single-player level.dat put next to it.
    make_world(
        root / "server export",
        level_name="Kasteel",
        data_version=4189,
        version_name="1.21.4",
        chunks={
            "castle/region": _chunks(2, T0 + 120 * DAY),
            "castle_the_end/region": _chunks(1, T0 + 121 * DAY),
        },
        chunk_data={"castle_nether/region": [_house_chunk()]},
        extra_files={
            **_level_data("castle", seed=-77),
            "castle_nether/data/paper/level_overrides.dat": nbt_gz({"DataVersion": 4903}),
        },
    )
    # The same, without any level.dat: only the folders say it is one world.
    tower = make_world(
        root / "tower_export",
        chunks={
            "tower/region": _chunks(3, T0 + 130 * DAY),
            "tower_nether/region": _chunks(1, T0 + 130 * DAY),
        },
        extra_files=_level_data("tower", seed=12),
    )
    (tower / "level.dat").unlink()


CONVERTED = T0 + 200 * DAY
"""When lce2java converted the Wii U world: every chunk and file of it carries this date."""


def _build_wiiu_world(root: Path) -> None:
    """A Wii U save converted by lce2java: the real history is only in wiiu_metadata.json."""
    metadata = {
        "source": {
            "console": "Nintendo Wii U",
            "date_in_save_name": "2017-01-14T12:00:00",
            "wfs_file_times_utc": {"save_file": {"mtime": "2017-03-02T15:00:00Z"}},
        },
        "world": {
            "name": "Noors kasteel",
            "last_played_utc": "2010-01-01T00:00:00Z",  # the converter's wrong epoch
            "time_played_ticks": 5 * 72_000,
            "times_loaded": 4,
            "players": [{"name": "NoorBouwt", "host": True}, {"name": "SamWii"}],
        },
        "conversion": {
            "tool": "lce2java 0.1.0",
            "converted_at_utc": datetime.fromtimestamp(CONVERTED, UTC).isoformat(),
            "notes": ["11 of 2,916 chunks could not be recovered."],
            "errors": ["a sign could not be converted"],
        },
    }
    player = {"Pos": TypedList(6, [1.0, 64.0, 1.0]), "Dimension": "minecraft:overworld"}
    # Converted from the old format: no structure references, only the stronghold's start.
    old = chunk_nbt(
        1,
        0,
        {(5, 40, 5): "minecraft:stone_bricks", (6, 61, 6): "minecraft:oak_planks"},
        fill=[(0, 59, "minecraft:stone"), (60, 60, "minecraft:grass_block")],
        inhabited=36_000,
        status="minecraft:empty",
    )
    old["TerrainPopulated"] = Byte(1)
    make_world(
        root / "Noors kasteel [wiiu 80000001-170014120000]",
        level_name="world",
        last_played=datetime.fromtimestamp(CONVERTED, UTC),
        chunks={"dimensions/minecraft/overworld/region": _chunks(3, CONVERTED)},
        chunk_data={"dimensions/minecraft/overworld/region": [old]},
        extra_files={
            "data/StrongHold.dat": nbt_gz(
                {"data": {"Features": {"[4,-2]": np.zeros(8, dtype=np.int8)}}}
            ),
            "wiiu_metadata.json": json.dumps(metadata).encode(),
            f"players/data/{lce_player_uuid('NoorBouwt')}.dat": nbt_gz(player),
            f"players/data/{lce_player_uuid('SamWii')}.dat": nbt_gz(player),
            "data/minecraft/maps/0.dat": map_dat(0, 0, color=5),
        },
    )


def _build_archive(root: Path) -> None:
    dream = make_world(
        root / "Alex en Sam's droom wereld",
        level_name="Alex en Sam's droom wereld",
        chunks={
            "region": _chunks(40, T0) + _chunks(10, T0 + 30 * DAY, x0=100),
            "DIM-1/region": _chunks(3, T0 + 60 * DAY),
        },
        players=[
            PlayerSpec(
                SAM,
                play_ticks=10 * 72_000,
                sessions=12,
                advancement_times=["2023-01-05 17:00:00 +0100"],
                inventory=[
                    {
                        "id": "minecraft:written_book",
                        "Count": Byte(1),
                        "tag": {"title": "Dagboek", "author": "Sam", "pages": ['"de kist"']},
                    }
                ],
            ),
            PlayerSpec(ALEX, play_ticks=2 * 72_000),
        ],
        chunk_data={"region": [_house_chunk()]},
        extra_files={
            "entities/r.0.0.mca": _entities_region(),
            "icon.png": b"\x89PNG fake",
            "data/map_0.dat": map_dat(0, 0, color=5),
            "data/map_1.dat": map_dat(128, 0, color=50),
            "data/map_2.dat": map_dat(0, 0),  # never used
            "data/map_3.dat": b"x",  # damaged
            ".DS_Store": b"finder",
        },
    )
    # An exact copy (same history) and a quick throwaway world.
    make_world(
        root / "New World (3)",
        level_name="Alex en Sam's droom wereld",
        chunks={"region": _chunks(40, T0) + _chunks(10, T0 + 30 * DAY, x0=100)},
    )
    make_world(
        root / "boring",
        level_name="boring",
        chunks={"region": _chunks(4, T0 + 5 * DAY)},
        generator={
            "type": "minecraft:flat",
            "settings": {"layers": [{"block": "minecraft:air", "height": 1}]},
        },
    )
    # Edge cases: nested world, empty folder, level.dat without terrain, special_level.dat.
    make_world(
        root / "backups" / "old copy", level_name="nested", chunks={"region": _chunks(2, T0)}
    )
    (root / "Demo_World").mkdir()
    (root / "Demo_World" / "session.lock").write_bytes(b"\xe2\x98\x83")
    make_world(root / "console", chunks={})
    make_world(
        root / "infinite dimensions",
        level_file="special_level.dat",
        chunks={"DIM597088138/region": _chunks(2, T0)},
    )
    # A world inside a zip archive.
    zip_src = root.parent / "zipsrc"
    make_world(zip_src / "DOORS", level_name="DOORS", chunks={"region": _chunks(5, T0 + 90 * DAY)})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(zip_src.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(zip_src).as_posix())
    (root / "DOORS.zip").write_bytes(buf.getvalue())
    _build_server_worlds(root)
    _build_wiiu_world(root)
    assert dream.exists()


def _make_readonly(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(Path(dirpath) / name, stat.S_IRUSR | stat.S_IRGRP)
        for name in dirnames:
            os.chmod(Path(dirpath) / name, stat.S_IRUSR | stat.S_IXUSR)
    os.chmod(root, stat.S_IRUSR | stat.S_IXUSR)


def _restore(root: Path) -> None:
    os.chmod(root, 0o755)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            os.chmod(Path(dirpath) / name, 0o755)
        for name in filenames:
            os.chmod(Path(dirpath) / name, 0o644)


@pytest.fixture
def archive(tmp_path: Path):
    root = tmp_path / "Minecraft_worlds"
    _build_archive(root)
    _make_readonly(root)
    try:
        with guard.protected([root]):
            yield root
    finally:
        _restore(root)


def test_full_pipeline_leaves_source_untouched(archive: Path, tmp_path: Path):
    before = manifest.take("archive", archive, hashed=True)
    out = tmp_path / "out"
    source = FolderSource("archive", archive, jobs=4)
    store = SqliteFactStore(out / "state" / "mcatlas.sqlite")
    try:
        first = analyze_sources([source], store, AnalyzeOptions(tier=2, jobs=4))
        second = analyze_sources([source], store, AnalyzeOptions(tier=2, jobs=4))
        names = {SAM: "SamCraft2024", ALEX: "AlexCraft2020", lce_player_uuid("NoorBouwt"): "Noor"}
        catalog, _, _ = publish_site(store, StaticSiteWriter(out / "site"), names, UTC)
        # 3D maps: BlueMap (here a stand-in) only ever reads copies in its workspace.
        renderer = BlueMapRenderer(out / "render", java=fake_java(tmp_path), jar=FAKE_BLUEMAP)
        rendered = render_worlds([source], catalog.worlds, renderer, RenderOptions())
        again = render_worlds([source], catalog.worlds, renderer, RenderOptions())
        dutch = render_worlds([source], catalog.worlds, renderer, RenderOptions(language="nl"))
        catalog, index, _ = publish_site(
            store, StaticSiteWriter(out / "site"), names, UTC, renderer=renderer
        )
        atlas = AtlasFolderWriter(out / "atlas", notes_dir=out / "atlas" / "annotations")
        exported = export_atlas(
            store,
            atlas,
            names,
            UTC,
            today=datetime(2026, 9, 27).date(),
            tool="mcatlas test",
            renderer=renderer,
        )
    finally:
        store.close()

    after = manifest.take("archive", archive, hashed=True)
    diff = manifest.compare(before, after)
    assert diff.clean, diff
    assert before.entries == after.entries

    # Rendering copied only what the maps need, and BlueMap saw only those copies.
    # Seven worlds get a map; the empty folder, console, 20w14∞ and level.dat-less worlds cannot.
    assert rendered.rendered == rendered.maps == 7 and len(rendered.skipped) == 4
    assert again.rendered == 0 and again.copied_files == 0 and again.up_to_date == again.maps
    assert dutch.rendered == 0 and dutch.up_to_date == dutch.maps  # markers only
    seen = (out / "render" / "fake-bluemap.log").read_text().splitlines()
    assert seen and all(str(out / "render" / "worlds") in line for line in seen)
    assert not any(str(archive) in line for line in seen)

    # Incremental: the second run found everything up to date.
    assert first.analyzed == first.worlds and not first.failures
    assert second.analyzed == 0 and second.up_to_date == second.worlds

    # Output landed only where it was asked to.
    assert Path(index).is_file() and (out / "site" / "data" / "catalog.js").is_file()
    by_folder = {w.folder_name: w for w in catalog.worlds}
    assert set(by_folder) == {
        "Alex en Sam's droom wereld",
        "New World (3)",
        "boring",
        "old copy",
        "Demo_World",
        "console",
        "infinite dimensions",
        "DOORS",
        "server export",
        "tower_export",
        "Noors kasteel [wiiu 80000001-170014120000]",
    }

    dream = by_folder["Alex en Sam's droom wereld"]
    assert dream.format is WorldFormat.ANVIL
    assert dream.chunks == 53 and len(dream.dimensions) == 2
    assert {p.name for p in dream.players} == {"SamCraft2024", "AlexCraft2020"}
    assert dream.play_hours == 12.0
    assert dream.has_icon and (out / "site" / "icons" / f"{dream.world_id}.png").is_file()
    assert dream.map_items == 4
    maps = dream.in_game_maps
    assert maps is not None and (maps.total, maps.filled) == (4, 2)
    assert [m.id for m in maps.shown] == [1, 0] and [m.maps for m in maps.mosaics] == [2]
    assert any("map_3.dat" in e for e in dream.errors)
    assert (out / "site" / "ingame" / dream.world_id / "mosaic-overworld.png").is_file()
    days = dream.activity.days
    assert datetime(2023, 1, 5).date() in days  # only known from advancements
    assert dream.activity.first_day == datetime(2023, 1, 5).date()
    assert dream.activity.distinct_days >= 4
    assert dream.sessions == 15 and dream.days_upper == 15  # 12 + 3: an upper bound on days
    assert dream.hours_per_session == 0.83 and not dream.afk_suspect
    assert dream.importance.score > by_folder["boring"].importance.score
    assert catalog.worlds[0].folder_name in {"Alex en Sam's droom wereld", "New World (3)"}

    build = dream.build
    assert build is not None
    assert (build.built, build.below, build.pct_below) == (130, 120, 92.3)
    assert build.top_blocks[0] == ("minecraft:oak_planks", 120)
    [site] = build.sites
    assert (site.x // 16, site.z // 16, site.min_y, site.max_y) == (5, 0, 40, 70)
    assert site.hours_nearby == 2.0
    assert (out / "site" / "data" / "maps" / f"{dream.world_id}.js").is_file()
    assert by_folder["boring"].build is not None and by_folder["boring"].build.built == 0
    assert by_folder["Demo_World"].build is None  # no region files: not applicable
    texts = {(t.kind, t.text, t.holder, t.x) for t in catalog.texts[dream.world_id]}
    assert texts == {
        ("sign", "Sams / geheime basis", "sign", 83),
        ("name", "Bello", "wolf", 85),
        ("book", "Dagboek — door Sam\nde kist", "player", 1),
    }
    assert dream.text_counts == {"sign": 1, "name": 1, "book": 1}
    assert "geheime basis" in (out / "site" / "data" / "texts.js").read_text()

    [dream_map] = catalog.renders[dream.world_id]
    assert dream_map.region_files == ["region/r.0.0.mca"]  # not r.3.0: no site there
    staged = out / "render" / "worlds" / dream.world_id
    assert sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()) == [
        "level.dat",
        "region/r.0.0.mca",
    ]
    assert dream_map.areas[0].label == "Plek 1" and dream_map.heights == {0: 70}
    assert (out / "site" / dream_map.images[0]).is_file()
    doors = by_folder["DOORS"]
    assert catalog.renders[doors.world_id][0].areas[0].label == "Spawn"  # copied from the zip
    assert by_folder["Demo_World"].world_id not in catalog.renders

    # Server worlds: sibling folders are one world, its state read from the 26.1+ files.
    castle = by_folder["server export"]
    assert castle.format is WorldFormat.ANVIL and castle.name == "Kasteel"
    assert [d.key for d in castle.dimensions] == [
        "minecraft:overworld",
        "minecraft:the_nether",
        "minecraft:the_end",
    ]
    assert (castle.seed, castle.spawn, castle.data_version) == (-77, (0, 58, 0), 4903)
    assert castle.version_name is None  # the level.dat's "1.21.4" is older than the world
    assert castle.build is not None and castle.build.sites[0].dimension == "minecraft:the_nether"
    [castle_map] = catalog.renders[castle.world_id]
    assert castle_map.region_files == ["castle_nether/region/r.0.0.mca"]
    staged = out / "render" / "worlds" / castle.world_id
    assert sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()) == [
        "DIM-1/region/r.0.0.mca",  # where BlueMap looks for the nether
        "level.dat",
    ]
    tower = by_folder["tower_export"]
    assert tower.relpath == "tower_export" and tower.format is WorldFormat.ANVIL
    assert (tower.seed, tower.chunks, len(tower.dimensions)) == (12, 4, 2)
    assert tower.build is not None  # tier 2 ran, although there is no level.dat
    assert tower.world_id not in catalog.renders

    # A world converted from a Wii U: its history comes from the console, not the conversion.
    wiiu = by_folder["Noors kasteel [wiiu 80000001-170014120000]"]
    assert sorted(wiiu.activity.days) == [datetime(2017, 1, 14).date(), datetime(2017, 3, 2).date()]
    assert wiiu.last_played == datetime(2017, 3, 2, 15, tzinfo=UTC)
    assert (wiiu.play_hours, wiiu.sessions, wiiu.hours_per_session) == (5.0, 4, 1.25)
    assert sorted((p.name, p.known) for p in wiiu.players) == [("Noor", True), ("SamWii", False)]
    assert wiiu.origin is not None and wiiu.origin.console == "Nintendo Wii U"
    assert wiiu.origin.created == datetime(2017, 1, 14).date()
    assert wiiu.origin.notes == ["11 of 2,916 chunks could not be recovered."]
    assert "console: a sign could not be converted" in wiiu.errors
    assert wiiu.in_game_maps is not None and wiiu.in_game_maps.total == 1
    assert wiiu.build is not None and wiiu.build.top_blocks == [("minecraft:oak_planks", 1)]

    # The durable atlas: plain files per world, the flat map and icon included.
    assert exported.worlds == 11 and not exported.problems
    world_dir = out / "atlas" / "worlds" / dream.world_id
    facts = tomllib.loads((world_dir / "facts.toml").read_text())
    assert facts["schema_version"] == 1 and facts["build"]["built"] == 130
    assert facts["build"]["sites"][0]["image"] == "site-1.png"
    assert (world_dir / "site-1.png").read_bytes() == (
        out / "site" / dream_map.images[0]
    ).read_bytes()
    assert (world_dir / "icon.png").is_file()
    assert "geheime basis" in (world_dir / "texts.md").read_text()
    assert sorted(p.name for p in (world_dir / "maps").iterdir()) == [
        "map_0.png",
        "map_1.png",
        "mosaic-overworld.png",
    ]
    assert facts["in_game_maps"]["mosaics"][0]["image"] == "maps/mosaic-overworld.png"
    assert facts["build"]["map_image"] == "chunks.png"
    assert facts["build"]["underground_image"] == "underground.png"  # 92% underground
    assert (world_dir / "chunks.png").read_bytes().startswith(b"\x89PNG")
    assert "![Wat er gebouwd is" not in (world_dir / "README.md").read_text()  # English
    assert "![What was built, from above](chunks.png)" in (world_dir / "README.md").read_text()
    assert "![Map 1](maps/map_1.png)" in (world_dir / "README.md").read_text()
    assert "Alex en Sam" in (out / "atlas" / "index.html").read_text()
    assert not (out / "atlas" / "annotations").exists()

    wiiu_dir = out / "atlas" / "worlds" / wiiu.world_id
    readme = (wiiu_dir / "README.md").read_text()
    assert "Nintendo Wii U, converted to Java with lce2java 0.1.0" in readme
    assert (
        tomllib.loads((wiiu_dir / "facts.toml").read_text())["origin"]["tool"] == "lce2java 0.1.0"
    )

    copy = by_folder["New World (3)"]
    assert any(r.world_id == dream.world_id and r.similarity > 0.9 for r in copy.related)
    assert not any(r.world_id == by_folder["boring"].world_id for r in dream.related)

    assert by_folder["boring"].generator.value == "void"
    assert by_folder["Demo_World"].format is WorldFormat.EMPTY
    assert by_folder["console"].format is WorldFormat.NO_TERRAIN
    assert by_folder["infinite dimensions"].dimensions[0].key == "legacy:dim597088138"
    assert by_folder["DOORS"].relpath == "DOORS.zip!/DOORS"
    assert by_folder["DOORS"].chunks == 5
    assert by_folder["old copy"].relpath == "backups/old copy"


def test_store_inside_source_is_refused(archive: Path):
    with pytest.raises(guard.SafetyError):
        SqliteFactStore(archive / "state.sqlite")
    with pytest.raises(guard.SafetyError):
        StaticSiteWriter(archive / "site").write(
            __import__("mcatlas.core.catalog", fromlist=["Catalog"]).Catalog(
                generated_at=datetime.now(UTC), timezone="UTC"
            ),
            {},
        )
    with pytest.raises(guard.SafetyError):
        AtlasFolderWriter(archive / "atlas", notes_dir=None).write({"index.md": b"x"})


def test_scan_skips_symlinks_and_rejects_escapes(tmp_path: Path):
    root = tmp_path / "src"
    make_world(root / "w")
    (root / "w" / "link.dat").symlink_to(tmp_path / "elsewhere")
    source = FolderSource("s", root)
    (listing,) = list(source.scan())
    assert "link.dat" not in {f.relpath for f in listing.files}
    with source.open(listing) as files:
        with pytest.raises(ValueError, match="unsafe"):
            files.read_bytes("../secret")
        with pytest.raises(ValueError, match="unsafe"):
            files.read_bytes("/etc/passwd")


def test_downloaded_map_history_and_foreign_players(tmp_path: Path):
    maker = "7efa11a0-0000-4000-8000-000000000001"
    root = tmp_path / "src"
    make_world(
        root / "Mazescapist",
        chunks={"region": _chunks(30, T0 - 900 * DAY) + _chunks(5, T0, x0=50)},
        players=[
            PlayerSpec(
                maker, play_ticks=300 * 72_000, advancement_times=["2020-03-01 12:00:00 +0100"]
            ),
            PlayerSpec(ALEX, play_ticks=12_000, advancement_times=["2023-02-12 11:00:00 +0100"]),
        ],
    )
    source = FolderSource("s", root)
    store = SqliteFactStore(tmp_path / "state.sqlite")
    try:
        analyze_sources([source], store, AnalyzeOptions(jobs=1))
        catalog, _, _ = publish_site(
            store, StaticSiteWriter(tmp_path / "site"), {ALEX: "Alex"}, UTC
        )
    finally:
        store.close()
        source.close()
    (world,) = catalog.worlds
    assert world.foreign_players == 1
    assert world.play_hours < 1 < world.play_hours_all  # our time, not the makers'
    assert world.activity.first_day == datetime(2023, 2, 12).date()
    assert world.activity.history and min(world.activity.history).year == 2020


def test_worker_processes_give_the_same_answer(archive: Path, tmp_path: Path):
    before = manifest.take("archive", archive, hashed=True)
    source = FolderSource("archive", archive, jobs=2)
    results = []
    for name, use_workers in (("serial", False), ("workers", True)):
        store = SqliteFactStore(tmp_path / name / "mcatlas.sqlite")
        try:
            options = AnalyzeOptions(tier=2, world_glob="Alex*", jobs=2)
            if use_workers:
                with process_mapper(2) as mapper:
                    analyze_sources([source], store, options, mapper=mapper)
            else:
                analyze_sources([source], store, options)
            results.append({w.folder_name: w.facts.get("blocks") for w in store.worlds()})
        finally:
            store.close()
    assert results[0] == results[1]
    assert results[0]["Alex en Sam's droom wereld"]
    assert manifest.compare(before, manifest.take("archive", archive, hashed=True)).clean
