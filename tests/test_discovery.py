from mcatlas.core import analyze
from mcatlas.core.analyze.files import is_game_file
from mcatlas.core.discovery import (
    classify,
    dimension_for_region_dir,
    is_world_root,
    merge_all_sibling_roots,
    merge_sibling_roots,
)
from mcatlas.core.model import SourceFile, WorldFormat, make_world_id, slugify


def files(*paths: str, size: int = 9000) -> list[SourceFile]:
    return [SourceFile(p, size, 0) for p in paths]


def test_world_root_markers():
    assert is_world_root(["level.dat"], [])
    assert is_world_root(["special_level.dat"], [])
    assert is_world_root([], ["region"])
    assert not is_world_root(["session.lock"], ["data"])


def test_dimension_keys():
    assert dimension_for_region_dir("region") == "minecraft:overworld"
    assert dimension_for_region_dir("DIM-1/region") == "minecraft:the_nether"
    assert dimension_for_region_dir("DIM1/region") == "minecraft:the_end"
    assert dimension_for_region_dir("DIM597088138/region") == "legacy:dim597088138"
    assert dimension_for_region_dir("dimensions/minecraft/skylands/region") == "minecraft:skylands"
    assert dimension_for_region_dir("weird/place/region") == "other:weird/place"


def test_vanilla_layout():
    layout = classify(
        files(
            "level.dat",
            "icon.png",
            "region/r.0.0.mca",
            "region/r.-1.0.mca",
            "DIM-1/region/r.0.0.mca",
            "entities/r.0.0.mca",
            "poi/r.0.0.mca",
            "playerdata/abc.dat",
            "playerdata/abc.dat_old",
            "stats/abc.json",
            "advancements/abc.json",
            "data/map_0.dat",
            "data/raids.dat",
        )
    )
    assert layout.format is WorldFormat.ANVIL
    assert layout.level_dat == "level.dat"
    assert [d.key for d in layout.dimensions] == ["minecraft:overworld", "minecraft:the_nether"]
    assert len(layout.dimensions[0].region_files) == 2
    assert [f.relpath for f in layout.player_data] == ["playerdata/abc.dat"]
    assert [f.relpath for f in layout.stats] == ["stats/abc.json"]
    assert layout.icon == "icon.png"


def test_newer_players_layout_and_dimensions_dir():
    layout = classify(
        files(
            "level.dat",
            "dimensions/minecraft/overworld/region/r.0.0.mca",
            "players/data/u1.dat",
            "players/stats/u1.json",
            "players/advancements/u1.json",
        )
    )
    assert [d.key for d in layout.dimensions] == ["minecraft:overworld"]
    assert [f.relpath for f in layout.player_data] == ["players/data/u1.dat"]
    assert len(layout.stats) == 1 and len(layout.advancements) == 1


def test_edge_formats():
    assert classify(files("level.dat", "region/r.0.0.mcr")).format is WorldFormat.MCREGION
    assert classify(files("level.dat", "session.lock")).format is WorldFormat.NO_TERRAIN
    assert classify(files("region/r.0.0.mca")).format is WorldFormat.NO_LEVEL_DAT
    assert classify(files("session.lock")).format is WorldFormat.EMPTY
    special = classify(files("special_level.dat", "region/r.0.0.mca"))
    assert special.format is WorldFormat.ANVIL and special.level_dat == "special_level.dat"
    converted = classify(files("level.dat", "level.dat_mcr", "region/r.0.0.mca"))
    assert converted.converted_from_mcregion


def test_paper_world_with_sibling_dimension_folders():
    """A Paper 26.x Multiverse world: three folders, no level.dat, the state in data/."""
    layout = classify(
        files(
            "castle/region/r.0.0.mca",
            "castle/entities/r.0.0.mca",
            "castle/data/minecraft/world_gen_settings.dat",
            "castle/data/minecraft/weather.dat",
            "castle/data/paper/level_overrides.dat",
            "castle_nether/region/r.0.0.mca",
            "castle_nether/entities/r.0.0.mca",
            "castle_nether/data/paper/level_overrides.dat",
            "castle_the_end/region/r.0.0.mca",
            "castle_the_end/region/r.-1.0.mca",
        )
    )
    assert layout.format is WorldFormat.ANVIL and layout.level_dat is None
    assert layout.level_data == (
        "castle/data/minecraft/world_gen_settings.dat",
        "castle/data/paper/level_overrides.dat",
    )
    assert [
        (d.key, d.region_dir, len(d.region_files), len(d.entity_files)) for d in layout.dimensions
    ] == [
        ("minecraft:overworld", "castle/region", 1, 1),
        ("minecraft:the_nether", "castle_nether/region", 1, 1),
        ("minecraft:the_end", "castle_the_end/region", 2, 0),
    ]
    assert classify(files("castle/region/r.0.0.mca", "castle_nether/region/r.0.0.mca")).format is (
        WorldFormat.NO_LEVEL_DAT
    )


def test_bukkit_world_with_sibling_dimension_folders():
    """Older Bukkit: each folder has its own level.dat, the nether keeps DIM-1/ inside."""
    layout = classify(
        files(
            "world/level.dat",
            "world/region/r.0.0.mca",
            "world/playerdata/u1.dat",
            "world/stats/u1.json",
            "world_nether/level.dat",
            "world_nether/DIM-1/region/r.0.0.mca",
            "world_the_end/level.dat",
            "world_the_end/DIM1/region/r.0.0.mca",
        )
    )
    assert layout.level_dat == "world/level.dat"
    assert [d.key for d in layout.dimensions] == [
        "minecraft:overworld",
        "minecraft:the_nether",
        "minecraft:the_end",
    ]
    assert [f.relpath for f in layout.player_data] == ["world/playerdata/u1.dat"]
    assert len(layout.stats) == 1


def test_sibling_folders_inside_an_ordinary_world_are_left_alone():
    layout = classify(
        files(
            "level.dat", "region/r.0.0.mca", "old/region/r.0.0.mca", "old_nether/region/r.0.0.mca"
        )
    )
    assert [d.key for d in layout.dimensions] == [
        "minecraft:overworld",
        "other:old",
        "other:old_nether",
    ]


def test_merge_sibling_roots():
    group = ["export/castle", "export/castle_nether", "export/castle_the_end"]
    assert merge_sibling_roots("export", group) == ["export"]
    assert merge_sibling_roots("export", group[:2]) == ["export"]
    # Not when other worlds share the folder, or without the overworld's folder.
    assert merge_sibling_roots("export", [*group, "export/tower"]) == [*group, "export/tower"]
    assert merge_sibling_roots("export", [*group, "export/old/copy"]) == [*group, "export/old/copy"]
    assert merge_sibling_roots("export", group[1:]) == group[1:]
    assert merge_sibling_roots("export", ["export/castle"]) == ["export/castle"]
    # In a zip: the whole archive can be the world, next to worlds elsewhere.
    assert merge_all_sibling_roots(["castle", "castle_nether"]) == [""]
    assert merge_all_sibling_roots(["a/castle", "a/castle_the_end", "b/tower"]) == ["a", "b/tower"]
    assert merge_all_sibling_roots(["a/castle", "b/castle_nether"]) == [
        "a/castle",
        "b/castle_nether",
    ]


def test_ids_are_stable_and_safe():
    a = make_world_id("archive", "Alex en Sam's droom wereld")
    assert a == make_world_id("archive", "Alex en Sam's droom wereld")
    assert a.startswith("alex-en-sam-s-droom-wereld-")
    # NFD and NFC spellings of the same folder give the same id
    assert make_world_id("s", "café") == make_world_id("s", "café")
    assert slugify("§4§lMazescapist") == "mazescapist"
    assert make_world_id("s", "DOORS.zip!/").startswith("doors-zip-")


def test_server_world_state_is_no_activity():
    def game(path: str) -> bool:
        return is_game_file(SourceFile(path, 1, 0))

    assert game("castle/region/r.0.0.mca") and game("level.dat") and game("data/map_0.dat")
    assert not game("castle/data/minecraft/weather.dat")
    assert not game("castle/data/paper/level_overrides.dat")


def test_not_applicable_is_cached_apart():
    """A world skipped as "not applicable" is analyzed once an analyzer starts to apply."""
    level_less = classify(files("region/r.0.0.mca"))
    empty = classify(files("session.lock"))
    assert analyze.cache_key(analyze.BLOCKS, level_less, "f") == "f"
    assert analyze.cache_key(analyze.BLOCKS, empty, "f") == "f/n-a"
