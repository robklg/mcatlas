"""The top requirement: running everything leaves the world source bit-for-bit untouched."""

import io
import os
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from builders import Byte, PlayerSpec, TypedList, chunk_nbt, make_world, region

from mcatlas.adapters import guard, manifest
from mcatlas.adapters.site_static import StaticSiteWriter
from mcatlas.adapters.source_folder import FolderSource
from mcatlas.adapters.store_sqlite import SqliteFactStore
from mcatlas.adapters.workers import process_mapper
from mcatlas.app.analyze import AnalyzeOptions, analyze_sources
from mcatlas.app.catalog import publish_site
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
            "data/map_0.dat": b"x",
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
        names = {SAM: "SamCraft2024", ALEX: "AlexCraft2020"}
        catalog, index, _ = publish_site(store, StaticSiteWriter(out / "site"), names, UTC)
    finally:
        store.close()

    after = manifest.take("archive", archive, hashed=True)
    diff = manifest.compare(before, after)
    assert diff.clean, diff
    assert before.entries == after.entries

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
    }

    dream = by_folder["Alex en Sam's droom wereld"]
    assert dream.format is WorldFormat.ANVIL
    assert dream.chunks == 53 and len(dream.dimensions) == 2
    assert {p.name for p in dream.players} == {"SamCraft2024", "AlexCraft2020"}
    assert dream.play_hours == 12.0
    assert dream.has_icon and (out / "site" / "icons" / f"{dream.world_id}.png").is_file()
    assert dream.map_items == 1
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
