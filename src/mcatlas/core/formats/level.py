"""level.dat / special_level.dat across versions (Beta McRegion up to 1.21)."""

import re
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
