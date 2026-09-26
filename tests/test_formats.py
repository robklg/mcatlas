import json
from datetime import UTC, datetime

import numpy as np
from builders import Long, TypedList, uuid_ints

from mcatlas.core.formats.advancements import parse_advancements
from mcatlas.core.formats.level import detect_generator, parse_level, strip_formatting
from mcatlas.core.formats.player import parse_player_state
from mcatlas.core.formats.stats import parse_stats
from mcatlas.core.model import GameMode, Generator


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
