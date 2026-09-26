"""Layout-agnostic world recognition, working purely on file listings.

Handles the vanilla layout (`region/`, `DIM-1/`, `DIM1/`), the 20w14∞ numbered dimensions
(`DIM<n>/`), the newer `dimensions/<namespace>/<name>/` layout, McRegion leftovers and
folders that contain no world at all.
"""

import re
from collections import defaultdict
from collections.abc import Iterable

from mcatlas.core.model import (
    NETHER,
    OVERWORLD,
    THE_END,
    DimensionKey,
    DimensionLayout,
    SourceFile,
    WorldFormat,
    WorldLayout,
)

LEVEL_FILES = ("level.dat", "special_level.dat", "level.dat_old", "special_level.dat_old")
"""Preferred order when choosing which level file to read."""

WORLD_MARKERS = frozenset((*LEVEL_FILES, "level.dat_mcr"))

_REGION_FILE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.(mca|mcr)$")
_LEGACY_DIM = re.compile(r"^DIM(-?\d+)$")


def is_world_root(file_names: Iterable[str], dir_names: Iterable[str]) -> bool:
    """Decide from one directory's entries whether it is the root of a world."""
    return bool(WORLD_MARKERS.intersection(file_names)) or "region" in set(dir_names)


def parse_region_name(name: str) -> tuple[int, int, str] | None:
    """`r.-1.2.mca` -> (-1, 2, "mca"); None for anything else."""
    m = _REGION_FILE.match(name)
    return (int(m[1]), int(m[2]), m[3]) if m else None


def dimension_for_region_dir(region_dir: str) -> DimensionKey:
    """Map the directory that holds region files to a dimension key."""
    parent = region_dir.removesuffix("region").rstrip("/")
    if parent == "":
        return OVERWORLD
    parts = parent.split("/")
    if len(parts) == 3 and parts[0] == "dimensions":
        return DimensionKey(f"{parts[1]}:{parts[2]}")
    if len(parts) == 1 and (m := _LEGACY_DIM.match(parts[0])):
        n = int(m[1])
        if n == -1:
            return NETHER
        if n == 1:
            return THE_END
        return DimensionKey(f"legacy:dim{n}")
    return DimensionKey(f"other:{parent}")


def _dimension_sort_key(dim: DimensionLayout) -> tuple[int, str]:
    order = {OVERWORLD: 0, NETHER: 1, THE_END: 2}
    return (order.get(dim.key, 3), dim.key)


def _in_player_dir(relpath: str, *names: str) -> bool:
    """True for `<name>/x` and `players/<name>/x` (the newer player-data layout)."""
    parts = relpath.split("/")
    if len(parts) == 2:
        return parts[0] in names
    return len(parts) == 3 and parts[0] == "players" and parts[1] in names


def classify(files: Iterable[SourceFile]) -> WorldLayout:
    by_path = {f.relpath: f for f in files}
    region_dirs: dict[str, list[SourceFile]] = defaultdict(list)
    entity_dirs: dict[str, list[SourceFile]] = defaultdict(list)
    player_data: list[SourceFile] = []
    stats: list[SourceFile] = []
    advancements: list[SourceFile] = []

    for f in by_path.values():
        head, _, name = f.relpath.rpartition("/")
        if (head == "region" or head.endswith("/region")) and parse_region_name(name):
            region_dirs[head].append(f)
        elif (head == "entities" or head.endswith("/entities")) and name.endswith(".mca"):
            if parse_region_name(name):
                entity_dirs[head.removesuffix("entities") + "region"].append(f)
        elif name.endswith(".dat") and _in_player_dir(f.relpath, "playerdata", "data", "players"):
            if head != "data":  # the world-level data/ dir holds maps and raids, not players
                player_data.append(f)
        elif name.endswith(".json") and _in_player_dir(f.relpath, "stats"):
            stats.append(f)
        elif name.endswith(".json") and _in_player_dir(f.relpath, "advancements"):
            advancements.append(f)

    dimensions = sorted(
        (
            DimensionLayout(
                key=dimension_for_region_dir(d),
                region_dir=d,
                region_files=tuple(sorted(fs, key=lambda f: f.relpath)),
                entity_files=tuple(sorted(entity_dirs.get(d, []), key=lambda f: f.relpath)),
            )
            for d, fs in region_dirs.items()
        ),
        key=_dimension_sort_key,
    )
    level_dat = next((name for name in LEVEL_FILES if name in by_path), None)
    has_anvil = any(f.relpath.endswith(".mca") for d in dimensions for f in d.region_files)
    has_mcr = any(f.relpath.endswith(".mcr") for d in dimensions for f in d.region_files)

    if has_anvil:
        fmt = WorldFormat.ANVIL if level_dat else WorldFormat.NO_LEVEL_DAT
    elif has_mcr:
        fmt = WorldFormat.MCREGION if level_dat else WorldFormat.NO_LEVEL_DAT
    elif level_dat:
        fmt = WorldFormat.NO_TERRAIN
    else:
        fmt = WorldFormat.EMPTY

    return WorldLayout(
        format=fmt,
        level_dat=level_dat,
        dimensions=tuple(dimensions),
        player_data=tuple(sorted(player_data, key=lambda f: f.relpath)),
        stats=tuple(sorted(stats, key=lambda f: f.relpath)),
        advancements=tuple(sorted(advancements, key=lambda f: f.relpath)),
        icon="icon.png" if "icon.png" in by_path else None,
        converted_from_mcregion="level.dat_mcr" in by_path and has_anvil,
    )
