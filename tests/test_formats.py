import json
from datetime import UTC, datetime

import numpy as np
from builders import Long, TypedList, uuid_ints

from mcatlas.core.formats.advancements import parse_advancements
from mcatlas.core.formats.level import (
    apply_level_data,
    detect_generator,
    parse_level,
    strip_formatting,
)
from mcatlas.core.formats.player import parse_player_state
from mcatlas.core.formats.stats import parse_stats
from mcatlas.core.model import GameMode, Generator
from mcatlas.core.nbt import NbtCompound


def _gen(generator: dict) -> dict:
    return {"WorldGenSettings": {"dimensions": {"minecraft:overworld": {"generator": generator}}}}


def test_generators():
    assert (
        detect_generator(_gen({"type": "minecraft:noise", "settings": "minecraft:overworld"}))[0]
        is Generator.DEFAULT
    )
    assert (
        detect_generator(_gen({"type": "minecraft:noise", "settings": "minecraft:amplified"}))[0]
        is Generator.AMPLIFIED
    )
    assert (
        detect_generator(_gen({"type": "minecraft:noise", "settings": "minecraft:large_biomes"}))[0]
        is Generator.LARGE_BIOMES
    )
    single = _gen(
        {
            "type": "minecraft:noise",
            "settings": "minecraft:overworld",
            "biome_source": {"type": "minecraft:fixed", "biome": "minecraft:desert"},
        }
    )
    assert detect_generator(single) == (Generator.SINGLE_BIOME, "minecraft:desert")
    flat = _gen(
        {
            "type": "minecraft:flat",
            "settings": {
                "layers": [
                    {"block": "minecraft:bedrock", "height": 1},
                    {"block": "minecraft:grass_block", "height": 1},
                ]
            },
        }
    )
    assert detect_generator(flat) == (Generator.FLAT, "1×bedrock, 1×grass_block")
    void = _gen(
        {
            "type": "minecraft:flat",
            "settings": {"layers": [{"block": "minecraft:air", "height": 1}]},
        }
    )
    assert detect_generator(void)[0] is Generator.VOID
    assert detect_generator({"generatorName": "largeBiomes"})[0] is Generator.LARGE_BIOMES
    assert detect_generator({})[0] is Generator.UNKNOWN


def test_parse_level_fields():
    root = {
        "Data": {
            "LevelName": "§4§lMazescapist",
            "DataVersion": 3578,
            "Version": {"Name": "1.20.2"},
            "GameType": 2,
            "hardcore": 0,
            "allowCommands": 1,
            "LastPlayed": Long(1_696_700_000_000),
            "Time": Long(9999),
            "spawn": {
                "pos": np.array([10, 70, -5], dtype=np.int32),
                "dimension": "minecraft:overworld",
            },
            "RandomSeed": Long(-77),
            "DataPacks": {"Enabled": TypedList(8, ["vanilla", "file/mypack"])},
            "Player": {
                "UUID": uuid_ints("a1e0a1e0-0000-4000-8000-000000000001"),
                "Pos": TypedList(6, [1.0, 2.0, 3.0]),
                "Dimension": 0,
                "playerGameType": 1,
            },
        }
    }
    from builders import nbt

    from mcatlas.core.nbt import decode

    level = parse_level(decode(nbt(root)), "level.dat")
    assert level.display_name == "Mazescapist"
    assert level.level_name == "§4§lMazescapist"
    assert level.version_name == "1.20.2" and level.data_version == 3578
    assert (
        level.game_mode is GameMode.ADVENTURE and level.hardcore is False and level.cheats is True
    )
    assert level.last_played == datetime.fromtimestamp(1_696_700_000, UTC)
    assert level.spawn == (10, 70, -5)
    assert level.seed == -77
    assert level.datapacks == ["vanilla", "file/mypack"]
    assert level.host_player is not None
    assert level.host_player.uuid == "a1e0a1e0-0000-4000-8000-000000000001"
    assert level.host_player.dimension == "minecraft:overworld"


_WORLD_GEN: NbtCompound = {
    "DataVersion": 4903,
    "data": {
        "seed": -77,
        "dimensions": {
            "minecraft:overworld": {
                "generator": {"type": "minecraft:noise", "settings": "minecraft:amplified"}
            }
        },
    },
}
_OVERRIDES: NbtCompound = {
    "DataVersion": 4903,
    "data": {
        "game_type": 1,
        "game_time": 5_000,
        "difficulty_settings": {"hardcore": 0, "difficulty": "normal"},
        "spawn": {"pos": np.array([10, 70, -20], dtype=">i4")},
    },
}
_PARTS: dict[str, NbtCompound] = {
    "castle/data/minecraft/world_gen_settings.dat": _WORLD_GEN,
    "castle/data/paper/level_overrides.dat": _OVERRIDES,
}


def test_level_data_without_level_dat():
    facts = apply_level_data(None, _PARTS, "castle/data/minecraft/world_gen_settings.dat")
    assert facts.level_file == "castle/data/minecraft/world_gen_settings.dat"
    assert (facts.seed, facts.generator, facts.spawn) == (-77, Generator.AMPLIFIED, (10, 70, -20))
    assert (facts.game_mode, facts.hardcore, facts.time_ticks) == (GameMode.CREATIVE, False, 5_000)
    assert (facts.data_version, facts.version_name, facts.level_name) == (4903, None, None)


def test_level_data_over_an_older_level_dat():
    """A single-player level.dat kept from before the world moved to a server."""
    old = parse_level(
        {
            "Data": {
                "LevelName": "Kasteel",
                "DataVersion": 4189,
                "Version": {"Name": "1.21.4"},
                "LastPlayed": 1_700_000_000_000,
                "GameType": 0,
                "SpawnX": 1,
                "SpawnY": 64,
                "SpawnZ": 2,
                "WorldGenSettings": {"seed": -77},
            }
        },
        "level.dat",
    )
    facts = apply_level_data(old, _PARTS, "castle/data/minecraft/world_gen_settings.dat")
    assert (facts.level_file, facts.level_name, facts.last_played) == (
        "level.dat",
        "Kasteel",
        old.last_played,
    )
    assert (facts.data_version, facts.version_name) == (4903, None)
    assert (facts.spawn, facts.game_mode, facts.generator) == (
        (10, 70, -20),
        GameMode.CREATIVE,
        Generator.AMPLIFIED,
    )
    # A level.dat newer than the data files keeps its own word.
    newer = old.model_copy(update={"data_version": 5000})
    assert apply_level_data(newer, _PARTS, "x") == newer


def test_strip_formatting():
    assert strip_formatting("§lParkour Paradise§r") == "Parkour Paradise"


def test_player_uuid_most_least():
    state = parse_player_state({"UUIDMost": -1, "UUIDLeast": 1, "Dimension": -1})
    assert state.uuid == "ffffffff-ffff-ffff-0000-000000000001"
    assert state.dimension == "minecraft:the_nether"


def test_stats_nested_and_flat():
    nested = parse_stats(
        json.dumps(
            {
                "stats": {
                    "minecraft:custom": {
                        "minecraft:play_time": 144000,
                        "minecraft:leave_game": 7,
                        "minecraft:walk_one_cm": 500,
                        "minecraft:fly_one_cm": 20,
                    },
                    "minecraft:used": {"minecraft:stone": 30, "minecraft:oak_planks": 70},
                    "minecraft:mined": {"minecraft:dirt": 5},
                },
                "DataVersion": 3465,
            }
        ).encode()
    )
    assert nested.play_ticks == 144000 and nested.sessions == 7
    assert nested.used_total == 100 and nested.mined_total == 5
    assert nested.distance_cm == 520
    assert nested.top_used[0] == ("oak_planks", 70)
    old = parse_stats(
        json.dumps(
            {"stat.playOneMinute": 500, "stat.leaveGame": 2, "achievement.x": {"value": 1}}
        ).encode()
    )
    assert old.play_ticks == 500 and old.sessions == 2


def test_advancements():
    done, times = parse_advancements(
        json.dumps(
            {
                "minecraft:story/root": {
                    "criteria": {
                        "a": "2023-09-01 20:50:47 +0200",
                        "b": "2023-09-01 20:50:47 +0200",
                    },
                    "done": True,
                },
                "minecraft:recipes/x": {
                    "criteria": {"c": "2023-02-12 10:00:00 +0100", "bad": "nope"},
                    "done": False,
                },
                "DataVersion": 3465,
            }
        ).encode()
    )
    assert done == 1
    assert len(times) == 2
    assert times[0].isoformat() == "2023-02-12T10:00:00+01:00"
