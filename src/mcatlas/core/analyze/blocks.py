"""Tier-2 analysis: read every chunk and measure what players built, where and how deep.

Region files are read whole, in small batches (bounded memory), through the read-only
`WorldFiles` protocol; the CPU-heavy decoding runs through the injected `Mapper`, so the
composition root can spread it over worker processes. Workers only ever receive bytes.
"""

import re
from collections import Counter
from collections.abc import Callable
from itertools import batched

from mcatlas.core import nbt
from mcatlas.core.anvil.region import HEADER_SIZE
from mcatlas.core.blocks import RegionJob, RegionScan, scan_entities, scan_region
from mcatlas.core.discovery import parse_region_name
from mcatlas.core.facts import BlockFacts, ChunkTable, DimensionBlocks, TextEntry
from mcatlas.core.formats.access import compound
from mcatlas.core.model import (
    NETHER,
    OVERWORLD,
    THE_END,
    DimensionLayout,
    Mapper,
    SourceFile,
    WorldFiles,
    WorldLayout,
)
from mcatlas.core.texts import FoundText, texts_of

STRONGHOLD_FILE = "data/stronghold.dat"
_CHUNK_KEY = re.compile(r"^\[(-?\d+),(-?\d+)\]$")
LIKELY_BY_DIMENSION: dict[str, tuple[str, ...]] = {
    NETHER: ("likely_fortress",),
    THE_END: ("likely_end_city",),
}
"""Structures assumed in old-format chunks without references, per dimension."""

BATCH = 16
"""Region files read per round trip; at most ~16 x 11 MB in memory per world."""
TOP_STRUCTURE_BLOCKS = 40


def _merge(scans: list[RegionScan], key: str) -> DimensionBlocks:
    columns: dict[str, list[int]] = {name: [] for name in ChunkTable.model_fields}
    blocks: Counter[str] = Counter()
    structure_blocks: Counter[str] = Counter()
    modded: Counter[str] = Counter()
    structures: Counter[str] = Counter()
    by_section: Counter[int] = Counter()
    for scan in scans:
        blocks.update(scan.blocks)
        structure_blocks.update(scan.structure_blocks)
        modded.update(scan.modded)
        structures.update(scan.structures)
        by_section.update(scan.built_by_section)
        for row in scan.rows:
            columns["x"].append(row.x)
            columns["z"].append(row.z)
            columns["built"].append(row.built)
            columns["below"].append(row.below)
            columns["no_ground"].append(row.no_ground)
            columns["seam"].append(row.seam)
            columns["structure_built"].append(row.structure_built)
            columns["min_y"].append(row.min_y)
            columns["max_y"].append(row.max_y)
            columns["inhabited"].append(row.inhabited)
            columns["saved"].append(row.saved)
    return DimensionBlocks(
        key=key,
        chunks_full=sum(s.chunks_full for s in scans),
        chunks_partial=sum(s.chunks_partial for s in scans),
        chunks_external=sum(s.chunks_external for s in scans),
        chunks_failed=sum(s.chunks_failed for s in scans),
        built=sum(columns["built"]),
        below=sum(columns["below"]),
        no_ground=sum(columns["no_ground"]),
        seam=sum(columns["seam"]),
        structure_built=sum(columns["structure_built"]),
        built_by_section=dict(sorted(by_section.items())),
        blocks=dict(blocks.most_common()),
        structure_blocks=dict(structure_blocks.most_common(TOP_STRUCTURE_BLOCKS)),
        modded=modded.total(),
        modded_blocks=dict(modded.most_common(TOP_STRUCTURE_BLOCKS)),
        structures=dict(structures.most_common()),
        table=ChunkTable.model_validate(columns),
    )


def _entry(found: FoundText, dimension: str | None) -> TextEntry:
    return TextEntry(
        kind=found.kind.value,
        text=found.text,
        holder=found.holder,
        dimension=dimension,
        x=found.x,
        y=found.y,
        z=found.z,
    )


def _scan_files(
    files: WorldFiles,
    region_files: tuple[SourceFile, ...],
    scanner: Callable[[RegionJob], RegionScan],
    mapper: Mapper,
    errors: list[str],
    *,
    likely: tuple[str, ...] = (),
    strongholds: tuple[tuple[int, int], ...] = (),
    converted: bool = False,
) -> list[RegionScan]:
    regions: list[tuple[str, int, int, int]] = []
    for f in region_files:
        parsed = parse_region_name(f.relpath.rsplit("/", 1)[-1])
        if parsed is not None and f.size >= HEADER_SIZE:
            regions.append((f.relpath, parsed[0], parsed[1], f.size))
    scans: list[RegionScan] = []
    for batch in batched(regions, BATCH, strict=False):
        blobs = files.read_ranges([(rel, 0, size) for rel, _, _, size in batch])
        jobs: list[RegionJob] = []
        for (rel, rx, rz, _), blob in zip(batch, blobs, strict=True):
            if isinstance(blob, OSError):
                errors.append(f"{rel}: {blob}")
            else:
                jobs.append(RegionJob(rel, rx, rz, blob, likely, strongholds, converted))
        for scan in mapper(scanner, jobs):
            errors.extend(scan.errors)
            scans.append(scan)
    return scans


def _dimension(
    files: WorldFiles,
    dim: DimensionLayout,
    mapper: Mapper,
    errors: list[str],
    texts: list[TextEntry],
    *,
    strongholds: tuple[tuple[int, int], ...],
    converted: bool,
) -> DimensionBlocks:
    likely = LIKELY_BY_DIMENSION.get(dim.key, ())
    held = strongholds if dim.key == OVERWORLD else ()
    scans = _scan_files(
        files,
        dim.region_files,
        scan_region,
        mapper,
        errors,
        likely=likely,
        strongholds=held,
        converted=converted,
    )
    entity_scans = _scan_files(files, dim.entity_files, scan_entities, mapper, errors)
    for scan in (*scans, *entity_scans):
        texts.extend(_entry(t, dim.key) for t in scan.texts)
    return _merge(scans, dim.key)


def _strongholds(files: WorldFiles, errors: list[str]) -> tuple[tuple[int, int], ...]:
    """Start chunks from the old-format structure file (`[x,z]` keys), when there is one.

    Java 1.12 wrote `data/Stronghold.dat`, the Wii U `data/StrongHold.dat`; the Wii U's
    per-structure data is its own binary format, so only the keys are used.
    """
    starts: list[tuple[int, int]] = []
    for f in files.listing.files:
        if f.relpath.lower() != STRONGHOLD_FILE:
            continue
        try:
            root = nbt.decode_file(files.read_bytes(f.relpath))
        except (OSError, nbt.NbtError, EOFError) as e:
            errors.append(f"{f.relpath}: {e}")
            continue
        features = compound(compound(root, "data") or {}, "Features") or {}
        starts.extend((int(m[1]), int(m[2])) for key in features if (m := _CHUNK_KEY.match(key)))
    return tuple(starts)


def _player_texts(files: WorldFiles, layout: WorldLayout, errors: list[str]) -> list[TextEntry]:
    """Books and named items that players carry (inventory, ender chest)."""
    holders: list[tuple[str, nbt.NbtCompound]] = []
    for f in layout.player_data:
        try:
            holders.append((f.relpath, nbt.decode_file(files.read_bytes(f.relpath))))
        except (OSError, nbt.NbtError, EOFError) as e:
            errors.append(f"{f.relpath}: {e}")
    if layout.level_dat is not None:
        try:
            level = nbt.decode_file(files.read_bytes(layout.level_dat))
            player = compound(compound(level, "Data") or {}, "Player")
            if player is not None:
                holders.append((layout.level_dat, player))
        except (OSError, nbt.NbtError, EOFError) as e:
            errors.append(f"{layout.level_dat}: {e}")
    found: list[TextEntry] = []
    for _path, player in holders:
        dimension = player.get("Dimension")
        dim = dimension if isinstance(dimension, str) else None
        found.extend(_entry(t, dim) for t in texts_of(player, holder_name="player"))
    return found


def analyze_blocks(files: WorldFiles, layout: WorldLayout, mapper: Mapper) -> BlockFacts:
    errors: list[str] = []
    texts: list[TextEntry] = []
    strongholds = _strongholds(files, errors)
    dims = [
        _dimension(
            files,
            d,
            mapper,
            errors,
            texts,
            strongholds=strongholds,
            converted=layout.console_metadata is not None,
        )
        for d in layout.dimensions
    ]
    texts.extend(_player_texts(files, layout, errors))
    return BlockFacts(dimensions=dims, texts=texts, errors=errors)
