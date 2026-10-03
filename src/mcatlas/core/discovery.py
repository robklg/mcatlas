"""Layout-agnostic world recognition, working purely on file listings.

Handles the vanilla layout (`region/`, `DIM-1/`, `DIM1/`), the 20w14∞ numbered dimensions
(`DIM<n>/`), the newer `dimensions/<namespace>/<name>/` layout, McRegion leftovers, folders
that contain no world at all, and the server layout in which a world's nether and end are
sibling folders (`<name>`, `<name>_nether`, `<name>_the_end`: Bukkit, Paper, Multiverse).
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence

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

LEVEL_DATA_FILES = ("data/minecraft/world_gen_settings.dat", "data/paper/level_overrides.dat")
"""Since 26.1 the seed and much of the world state moved out of level.dat into these files; a
Paper server writes no level.dat at all for its extra (Multiverse) worlds."""

NETHER_SUFFIX = "_nether"
END_SUFFIX = "_the_end"

_REGION_FILE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.(mca|mcr)$")
_LEGACY_DIM = re.compile(r"^DIM(-?\d+)$")


def is_world_root(file_names: Iterable[str], dir_names: Iterable[str]) -> bool:
    """Decide from one directory's entries whether it is the root of a world."""
    return bool(WORLD_MARKERS.intersection(file_names)) or "region" in set(dir_names)


def parse_region_name(name: str) -> tuple[int, int, str] | None:
    """`r.-1.2.mca` -> (-1, 2, "mca"); None for anything else."""
    m = _REGION_FILE.match(name)
    return (int(m[1]), int(m[2]), m[3]) if m else None


def sibling_group(names: Iterable[str]) -> str | None:
    """The `<name>` of a server world whose nether or end sit next to it as sibling folders.

    Among folder names, finds `<name>` together with `<name>_nether` and/or `<name>_the_end`;
    None when there is no such group or more than one.
    """
    present = set(names)
    bases = {
        n for n in present if f"{n}{NETHER_SUFFIX}" in present or f"{n}{END_SUFFIX}" in present
    }
    return next(iter(bases)) if len(bases) == 1 else None


def merge_sibling_roots(parent: str, roots: Sequence[str]) -> list[str]:
    """Replace world roots `<parent>/<name>`, `<name>_nether`, `<name>_the_end` by `<parent>`.

    Only when those are the only worlds in `parent`: then the parent is the world, the way a
    server's world folder holds all three. `parent` is "" for the root of a zip archive.
    """
    prefix = f"{parent}/" if parent else ""
    children = [r.removeprefix(prefix) for r in roots]
    if any(not r.startswith(prefix) or "/" in c for r, c in zip(roots, children, strict=True)):
        return list(roots)
    base = sibling_group(children)
    group = {base, f"{base}{NETHER_SUFFIX}", f"{base}{END_SUFFIX}"}
    if base is None or not set(children) <= group:
        return list(roots)
    return [parent]


def merge_all_sibling_roots(roots: Sequence[str]) -> list[str]:
    """`merge_sibling_roots` for a flat list of roots, such as all worlds in one zip archive."""
    merged = list(roots)
    for parent in sorted({r.rpartition("/")[0] for r in roots}):
        prefix = f"{parent}/" if parent else ""
        inside = [r for r in merged if r.startswith(prefix) and r != parent]
        if merge_sibling_roots(parent, inside) == [parent]:
            merged = [r for r in merged if r not in inside] + [parent]
    return sorted(merged)


def _sibling_dimension(region_dir: str, base: str | None) -> DimensionKey | None:
    """Paper: `<name>_nether/region`; older Bukkit: `<name>_nether/DIM-1/region`."""
    if base is None:
        return None
    match region_dir.split("/")[:-1]:
        case [folder] if folder == base:
            return OVERWORLD
        case [folder] | [folder, "DIM-1"] if folder == f"{base}{NETHER_SUFFIX}":
            return NETHER
        case [folder] | [folder, "DIM1"] if folder == f"{base}{END_SUFFIX}":
            return THE_END
        case _:
            return None


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


def _player_files(
    files: Iterable[SourceFile], overworld: str
) -> tuple[list[SourceFile], list[SourceFile], list[SourceFile]]:
    """(player data, stats, advancements); `overworld` is the folder prefix they sit under."""
    player_data: list[SourceFile] = []
    stats: list[SourceFile] = []
    advancements: list[SourceFile] = []
    for f in files:
        rel = f.relpath.removeprefix(overworld)
        head, _, name = rel.rpartition("/")
        if name.endswith(".dat") and _in_player_dir(rel, "playerdata", "data", "players"):
            if head != "data":  # the world-level data/ dir holds maps and raids, not players
                player_data.append(f)
        elif name.endswith(".json") and _in_player_dir(rel, "stats"):
            stats.append(f)
        elif name.endswith(".json") and _in_player_dir(rel, "advancements"):
            advancements.append(f)
    return player_data, stats, advancements


def classify(files: Iterable[SourceFile]) -> WorldLayout:
    by_path = {f.relpath: f for f in files}
    region_dirs: dict[str, list[SourceFile]] = defaultdict(list)
    entity_dirs: dict[str, list[SourceFile]] = defaultdict(list)
    rest: list[SourceFile] = []
    for f in by_path.values():
        head, _, name = f.relpath.rpartition("/")
        if (head == "region" or head.endswith("/region")) and parse_region_name(name):
            region_dirs[head].append(f)
        elif (head == "entities" or head.endswith("/entities")) and name.endswith(".mca"):
            if parse_region_name(name):
                entity_dirs[head.removesuffix("entities") + "region"].append(f)
        else:
            rest.append(f)

    sibling_base = (
        None if "region" in region_dirs else sibling_group(d.split("/", 1)[0] for d in region_dirs)
    )
    # A server keeps players and the overworld's own data/ in the overworld's folder.
    overworld = f"{sibling_base}/" if sibling_base is not None else ""
    player_data, stats, advancements = _player_files(rest, overworld)

    dimensions = sorted(
        (
            DimensionLayout(
                key=_sibling_dimension(d, sibling_base) or dimension_for_region_dir(d),
                region_dir=d,
                region_files=tuple(sorted(fs, key=lambda f: f.relpath)),
                entity_files=tuple(sorted(entity_dirs.get(d, []), key=lambda f: f.relpath)),
            )
            for d, fs in region_dirs.items()
        ),
        key=_dimension_sort_key,
    )
    level_dat = next(
        (
            path
            for prefix in ("", overworld)
            for name in LEVEL_FILES
            if (path := prefix + name) in by_path
        ),
        None,
    )
    candidates = dict.fromkeys(f"{p}{name}" for p in ("", overworld) for name in LEVEL_DATA_FILES)
    level_data = tuple(path for path in candidates if path in by_path)
    has_level = level_dat is not None or bool(level_data)
    has_anvil = any(f.relpath.endswith(".mca") for d in dimensions for f in d.region_files)
    has_mcr = any(f.relpath.endswith(".mcr") for d in dimensions for f in d.region_files)

    if has_anvil:
        fmt = WorldFormat.ANVIL if has_level else WorldFormat.NO_LEVEL_DAT
    elif has_mcr:
        fmt = WorldFormat.MCREGION if has_level else WorldFormat.NO_LEVEL_DAT
    elif level_dat:
        fmt = WorldFormat.NO_TERRAIN
    else:
        fmt = WorldFormat.EMPTY

    return WorldLayout(
        format=fmt,
        level_dat=level_dat,
        level_data=level_data,
        dimensions=tuple(dimensions),
        player_data=tuple(sorted(player_data, key=lambda f: f.relpath)),
        stats=tuple(sorted(stats, key=lambda f: f.relpath)),
        advancements=tuple(sorted(advancements, key=lambda f: f.relpath)),
        icon="icon.png" if "icon.png" in by_path else None,
        converted_from_mcregion="level.dat_mcr" in by_path and has_anvil,
    )
