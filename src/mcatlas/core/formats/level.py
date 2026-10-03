"""level.dat / special_level.dat across versions (Beta McRegion up to 1.21), and the 26.1+
files that took over part of it (`data/minecraft/world_gen_settings.dat`, Paper's
`data/paper/level_overrides.dat`)."""

import re
from collections.abc import Mapping
from datetime import UTC, datetime

from mcatlas.core.facts import LevelFacts
from mcatlas.core.formats.access import (
    bool_,
    compound,
    compound_path,
    compounds,
    int_,
    int_array,
    list_,
    str_,
    strings,
)
from mcatlas.core.formats.player import game_mode, parse_player_state
from mcatlas.core.model import Generator
from mcatlas.core.nbt import NbtCompound
from mcatlas.core.npx import to_ints

_FORMATTING = re.compile(r"§.")

_NOISE_PRESETS = {
    "minecraft:overworld": Generator.DEFAULT,
    "minecraft:amplified": Generator.AMPLIFIED,
    "minecraft:large_biomes": Generator.LARGE_BIOMES,
}

_LEGACY_GENERATORS = {
    "default": Generator.DEFAULT,
    "default_1_1": Generator.DEFAULT,
    "flat": Generator.FLAT,
    "largebiomes": Generator.LARGE_BIOMES,
    "amplified": Generator.AMPLIFIED,
    "customized": Generator.CUSTOM,
    "buffet": Generator.SINGLE_BIOME,
    "debug_all_block_states": Generator.DEBUG,
}


def strip_formatting(text: str) -> str:
    return _FORMATTING.sub("", text).strip()


def _flat(settings: NbtCompound | None) -> tuple[Generator, str | None]:
    layers = compounds(list_(settings, "layers")) if settings else []
    described = [(int_(layer, "height") or 1, str_(layer, "block") or "?") for layer in layers]
    if all(block == "minecraft:air" for _, block in described):
        return Generator.VOID, None
    detail = ", ".join(f"{h}×{b.removeprefix('minecraft:')}" for h, b in described)
    return Generator.FLAT, detail


def detect_generator(data: NbtCompound) -> tuple[Generator, str | None]:  # noqa: PLR0911
    """Classify the overworld generator from 1.16+ WorldGenSettings or the legacy fields."""
    generator = compound_path(data, "WorldGenSettings", "dimensions", "minecraft:overworld")
    generator = compound(generator, "generator") if generator else None
    if generator is not None:
        gen_type = str_(generator, "type")
        if gen_type == "minecraft:flat":
            return _flat(compound(generator, "settings"))
        if gen_type == "minecraft:debug":
            return Generator.DEBUG, None
        if gen_type == "minecraft:noise":
            biome_source = compound(generator, "biome_source")
            if biome_source and str_(biome_source, "type") == "minecraft:fixed":
                return Generator.SINGLE_BIOME, str_(biome_source, "biome")
            preset = str_(generator, "settings")
            if preset is None:
                return Generator.CUSTOM, "inline noise settings"
            return _NOISE_PRESETS.get(preset, Generator.CUSTOM), preset
        return Generator.CUSTOM, gen_type

    legacy = str_(data, "generatorName")
    if legacy is not None:
        kind = _LEGACY_GENERATORS.get(legacy.lower(), Generator.CUSTOM)
        return kind, str_(data, "generatorOptions") or None
    return Generator.UNKNOWN, None


def _spawn(data: NbtCompound) -> tuple[int, int, int] | None:
    x, y, z = int_(data, "SpawnX"), int_(data, "SpawnY"), int_(data, "SpawnZ")
    if x is not None and y is not None and z is not None:
        return (x, y, z)
    spawn = compound(data, "spawn")
    pos = int_array(spawn.get("pos")) if spawn else None
    if pos is not None and pos.size == 3:
        px, py, pz = to_ints(pos)
        return (px, py, pz)
    return None


def parse_level(root: NbtCompound, level_file: str) -> LevelFacts:
    data = compound(root, "Data") or root
    version = compound(data, "Version")
    last_played = int_(data, "LastPlayed")
    seed = int_(compound(data, "WorldGenSettings") or {}, "seed")
    generator, generator_detail = detect_generator(data)
    raw_name = str_(data, "LevelName")
    host = compound(data, "Player")
    datapacks = compound(data, "DataPacks")
    return LevelFacts(
        level_file=level_file,
        level_name=raw_name,
        display_name=strip_formatting(raw_name) if raw_name else None,
        version_name=str_(version, "Name") if version else None,
        data_version=int_(data, "DataVersion"),
        game_mode=game_mode(int_(data, "GameType")),
        hardcore=bool_(data, "hardcore"),
        cheats=bool_(data, "allowCommands"),
        generator=generator,
        generator_detail=generator_detail,
        seed=seed if seed is not None else int_(data, "RandomSeed"),
        time_ticks=int_(data, "Time"),
        last_played=datetime.fromtimestamp(last_played / 1000, UTC) if last_played else None,
        spawn=_spawn(data),
        was_modded=bool_(data, "WasModded"),
        server_brands=strings(list_(data, "ServerBrands")),
        datapacks=strings(list_(datapacks, "Enabled")) if datapacks else [],
        enabled_features=strings(list_(data, "enabled_features")),
        host_player=parse_player_state(host) if host else None,
    )


def _level_data_version(parts: Mapping[str, NbtCompound]) -> int | None:
    versions = [v for part in parts.values() if (v := int_(part, "DataVersion")) is not None]
    return max(versions, default=None)


def apply_level_data(
    base: LevelFacts | None, parts: Mapping[str, NbtCompound], level_file: str
) -> LevelFacts:
    """Complete (or, without a level.dat, build) the level facts from the 26.1+ files.

    `parts` maps each file's path to its decoded root. They hold the world's current state, so
    they win over a level.dat that is older: e.g. a single-player level.dat kept from before
    the world moved to a server. Name, last played and host player stay the level.dat's.
    """
    facts = base or LevelFacts(level_file=level_file)
    data_version = _level_data_version(parts)
    if base is not None and data_version is not None and (base.data_version or 0) > data_version:
        return base
    update: dict[str, object] = {}
    if data_version is not None and data_version != facts.data_version:
        # A level.dat's version name belongs to its own, older DataVersion.
        facts = facts.model_copy(update={"data_version": data_version, "version_name": None})
    for path, root in parts.items():
        data = compound(root, "data") or {}
        if path.endswith("world_gen_settings.dat"):
            generator, detail = detect_generator({"WorldGenSettings": data})
            if generator is not Generator.UNKNOWN:
                update |= {"generator": generator, "generator_detail": detail}
            update["seed"] = int_(data, "seed")
        elif path.endswith("level_overrides.dat"):
            difficulty = compound(data, "difficulty_settings") or {}
            update |= {
                "game_mode": game_mode(int_(data, "game_type")),
                "hardcore": bool_(difficulty, "hardcore"),
                "time_ticks": int_(data, "game_time"),
                "spawn": _spawn(data),
            }
    return facts.model_copy(update={k: v for k, v in update.items() if v is not None})
