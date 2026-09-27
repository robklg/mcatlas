from mcatlas.core.discovery import classify, dimension_for_region_dir, is_world_root
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


def test_ids_are_stable_and_safe():
    a = make_world_id("archive", "Alex en Sam's droom wereld")
    assert a == make_world_id("archive", "Alex en Sam's droom wereld")
    assert a.startswith("alex-en-sam-s-droom-wereld-")
    # NFD and NFC spellings of the same folder give the same id
    assert make_world_id("s", "café") == make_world_id("s", "café")
    assert slugify("§4§lMazescapist") == "mazescapist"
    assert make_world_id("s", "DOORS.zip!/").startswith("doors-zip-")
