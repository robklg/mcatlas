"""Where did players build? Block classification per chunk, aggregated per region file.

Every block falls in one category (see `core.data.natural_blocks`). Non-natural blocks are
*built*; built blocks in chunks that a generated structure touches are counted apart, since
villages and mineshafts are not our players' work.

Above or below ground
---------------------
The natural surface of a column is its highest natural *ground* block (trees and plants do not
count). Digging a basement lowers that surface to the basement floor, so the raw surface would
call a basement "above ground". The surface of a whole region is therefore smoothed with a
morphological closing: depressions narrower than `SURFACE_WINDOW` blocks (pits, cellars, the
footprint of a house with a basement) are filled up to the surrounding ground level, while wide
valleys stay valleys. A built block is *below ground* when it lies under that smoothed surface.
Columns without any ground (void and sky worlds) have no surface; their blocks count as
`no_ground`.

`scan_region` is a pure function of the region file's bytes, so it can run in a worker process.
"""

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from mcatlas.core import nbt
from mcatlas.core.anvil.chunk import Chunk, ChunkError, chunk_bytes, parse_chunk
from mcatlas.core.anvil.region import parse_header
from mcatlas.core.data import natural_blocks as nb
from mcatlas.core.data.structure_blocks import is_structure_block
from mcatlas.core.npx import eq, item, ne, to_ints
from mcatlas.core.texts import FoundText, texts_of

AIR: Final = 0
FLUID: Final = 1
GROUND: Final = 2
VEGETATION: Final = 3
SEAM: Final = 4
BUILT: Final = 5
STRUCTURE: Final = 6
"""Non-natural, but placed by a generated structure or dungeon in this chunk."""
MODDED: Final = 7
"""A block from another namespace: a mod's terrain or building block, counted apart."""
SPAWNER: Final = "minecraft:spawner"
SPAWNER_BYTES: Final = SPAWNER.encode()
VISITED_TICKS: Final = 36_000
"""Below 30 minutes of player presence nearby, typical structure blocks (planks, cobblestone,
beds, ...) are taken as generated: structure references are missing in some upgraded worlds."""

SURFACE_WINDOW: Final = 17
"""Width in blocks of the closing that fills cellars and pits (odd)."""
INHABITED_MIN_TICKS: Final = 1200
"""Chunks where players spent at least a minute are kept even without building."""
REGION_BLOCKS: Final = 512
STRONGHOLD_REACH: Final = 7
"""Chunks from a stronghold's start chunk that its rooms can reach (Java keeps them within
about 112 blocks)."""
MAX_ERRORS: Final = 5

_categories: dict[str, int] = {}


def category(name: str) -> int:
    cat = _categories.get(name)
    if cat is None:
        if name in nb.AIR:
            cat = AIR
        elif name in nb.FLUID:
            cat = FLUID
        elif name in nb.GROUND:
            cat = GROUND
        elif name in nb.VEGETATION:
            cat = VEGETATION
        elif name in nb.SEAM:
            cat = SEAM
        elif not name.startswith("minecraft:"):
            cat = MODDED
        else:
            cat = BUILT
        _categories[name] = cat
    return cat


@lru_cache(maxsize=65536)
def _context_category(name: str, structures: tuple[str, ...]) -> int:
    cat = category(name)
    if cat == BUILT and structures and is_structure_block(name, structures):
        return STRUCTURE
    return cat


def _likely(chunk: Chunk, job: RegionJob) -> tuple[str, ...]:
    """Structures to assume in a chunk without references for them: one converted from the old
    format, or any chunk of a world converted from a console."""
    if not (chunk.legacy or job.converted):
        return ()
    near = any(
        max(abs(chunk.x - x), abs(chunk.z - z)) <= STRONGHOLD_REACH for x, z in job.strongholds
    )
    return (*job.likely, "likely_stronghold") if near else job.likely


def _generated(
    chunk: Chunk, *, near_spawner: bool, likely: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """What could have placed non-natural blocks here: the chunk's structures, plus the
    pseudo-structures "dungeon" (a spawner in this or a neighbouring chunk; dungeons straddle
    chunk borders) and "unvisited" (players spent little time nearby)."""
    context = (*chunk.structures, *likely)
    if near_spawner:
        context = (*context, "dungeon")
    if chunk.inhabited_ticks < VISITED_TICKS:
        context = (*context, "unvisited")
    return context


@dataclass(frozen=True, slots=True)
class RegionJob:
    relpath: str
    region_x: int
    region_z: int
    data: bytes
    likely: tuple[str, ...] = ()
    """Structures assumed in this dimension's chunks converted from the old format, which carry
    no structure references (see `structure_blocks.LIKELY`)."""
    strongholds: tuple[tuple[int, int], ...] = ()
    """Start chunks of the strongholds, as far as the world's data files tell."""
    converted: bool = False
    """The world was converted from a console: even once Java has finished its chunks, they
    carry no references for the structures the console generated."""


@dataclass(frozen=True, slots=True)
class ChunkRow:
    x: int
    z: int
    built: int
    below: int
    no_ground: int
    seam: int
    structure_built: int
    min_y: int
    max_y: int
    inhabited: int
    saved: int
    """Unix time of the chunk's last save (region header)."""


@dataclass(slots=True)
class RegionScan:
    relpath: str
    chunks_full: int = 0
    chunks_partial: int = 0
    chunks_external: int = 0
    chunks_failed: int = 0
    rows: list[ChunkRow] = field(default_factory=list[ChunkRow])
    blocks: Counter[str] = field(default_factory=Counter[str])
    """Built blocks outside structures, by block name."""
    structure_blocks: Counter[str] = field(default_factory=Counter[str])
    """Non-natural blocks attributed to structures and dungeons."""
    modded: Counter[str] = field(default_factory=Counter[str])
    texts: list[FoundText] = field(default_factory=list[FoundText])
    structures: Counter[str] = field(default_factory=Counter[str])
    """Structure name -> number of chunks it touches."""
    built_by_section: Counter[int] = field(default_factory=Counter[int])
    """Built blocks outside structures per section (block y // 16)."""
    errors: list[str] = field(default_factory=list[str])


@dataclass(frozen=True, slots=True)
class _Pending:
    """Pass-1 result for one chunk: built block positions wait for the smoothed surface."""

    chunk: Chunk
    saved: int
    surface: NDArray[np.int32]
    """Highest ground block y per column (z, x); INT32_MIN where the column has no ground."""
    columns: NDArray[np.int32]
    """Column index (z * 16 + x) of every built block."""
    ys: NDArray[np.int32]
    seam: int
    structure_built: int


_NO_GROUND: Final = np.iinfo(np.int32).min


def _classify(
    chunk: Chunk,
    saved: int,
    scan: RegionScan,
    *,
    near_spawner: bool,
    likely: tuple[str, ...] = (),
) -> _Pending:
    """Categorize all blocks; count built blocks by name and section."""
    if not chunk.sections:
        empty = np.empty(0, dtype=np.int32)
        return _Pending(chunk, saved, np.full((16, 16), _NO_GROUND, np.int32), empty, empty, 0, 0)
    lo = chunk.sections[0].y
    height = (chunk.sections[-1].y - lo + 1) * 16
    cats = np.zeros((height, 16, 16), dtype=np.uint8)
    context = _generated(chunk, near_spawner=near_spawner, likely=likely)
    seam = structure_built = 0
    for sec in chunk.sections:
        lut = np.fromiter(
            (_context_category(n, context) for n in sec.palette),
            dtype=np.uint8,
            count=len(sec.palette),
        )
        base = (sec.y - lo) * 16
        if sec.indices is None:
            cats[base : base + 16] = lut[0]
            counts = np.array([4096], dtype=np.int64)
        else:
            cats[base : base + 16] = lut[sec.indices].reshape(16, 16, 16)
            counts = np.bincount(sec.indices, minlength=len(sec.palette))
        built_here = 0
        for i in to_ints(np.flatnonzero(eq(lut, BUILT))):
            n = item(counts, i)
            if n:
                scan.blocks[sec.palette[i]] += n
                built_here += n
        for i in to_ints(np.flatnonzero(eq(lut, STRUCTURE))):
            n = item(counts, i)
            if n:
                scan.structure_blocks[sec.palette[i]] += n
                structure_built += n
        for i in to_ints(np.flatnonzero(eq(lut, MODDED))):
            n = item(counts, i)
            if n:
                scan.modded[sec.palette[i]] += n
        if built_here:
            scan.built_by_section[sec.y] += built_here
        seam += int(counts[eq(lut, SEAM)].sum())

    ground = eq(cats, GROUND)
    has_ground = np.any(ground, axis=0)
    top = height - 1 - np.argmax(ground[::-1], axis=0)
    surface = np.where(has_ground, top + lo * 16, _NO_GROUND).astype(np.int32)
    y_idx, z_idx, x_idx = np.nonzero(eq(cats, BUILT))
    return _Pending(
        chunk,
        saved,
        surface,
        (z_idx * 16 + x_idx).astype(np.int32),
        (y_idx + lo * 16).astype(np.int32),
        seam,
        structure_built,
    )


def _window(a: NDArray[np.float64], *, reduce_max: bool) -> NDArray[np.float64]:
    """Separable sliding max/min over a SURFACE_WINDOW square, edges padded neutrally."""
    pad = SURFACE_WINDOW // 2
    fill = -np.inf if reduce_max else np.inf
    out = a
    for axis in (0, 1):
        widths = [(0, 0), (0, 0)]
        widths[axis] = (pad, pad)
        padded = np.pad(out, widths, constant_values=fill)
        windows = sliding_window_view(padded, SURFACE_WINDOW, axis=axis)
        out = windows.max(axis=-1) if reduce_max else windows.min(axis=-1)
    return out


def smooth_surface(heights: NDArray[np.float64]) -> NDArray[np.float64]:
    """Morphological closing of a height field; -inf marks columns without ground.

    Never lowers a column and never gives a groundless column a surface. Columns next to
    unknown land only close over known neighbours.
    """
    known = np.isfinite(heights)
    dilated = _window(heights, reduce_max=True)
    closed = _window(np.where(np.isfinite(dilated), dilated, np.inf), reduce_max=False)
    return np.where(known & np.isfinite(closed), np.maximum(heights, closed), heights)


def _finish(pending: list[_Pending], region_x: int, region_z: int, scan: RegionScan) -> None:
    heights = np.full((REGION_BLOCKS, REGION_BLOCKS), -np.inf)
    for p in pending:
        lz, lx = (p.chunk.z - region_z * 32) * 16, (p.chunk.x - region_x * 32) * 16
        if 0 <= lx < REGION_BLOCKS and 0 <= lz < REGION_BLOCKS:
            known = ne(p.surface, _NO_GROUND)
            heights[lz : lz + 16, lx : lx + 16] = np.where(known, p.surface, -np.inf)
    smoothed = smooth_surface(heights)

    for p in pending:
        c = p.chunk
        lz, lx = (c.z - region_z * 32) * 16, (c.x - region_x * 32) * 16
        if 0 <= lx < REGION_BLOCKS and 0 <= lz < REGION_BLOCKS:
            local = smoothed[lz : lz + 16, lx : lx + 16].reshape(-1)
        else:  # chunk stored in the wrong region file: fall back to its own surface
            local = np.where(ne(p.surface, _NO_GROUND), p.surface, -np.inf).reshape(-1)
        built = int(p.ys.size)
        if not (built or p.seam or p.structure_built or c.inhabited_ticks >= INHABITED_MIN_TICKS):
            continue
        surface = local[p.columns]
        grounded = np.isfinite(surface)
        scan.rows.append(
            ChunkRow(
                x=c.x,
                z=c.z,
                built=built,
                below=int(np.count_nonzero(grounded & (p.ys < surface))),
                no_ground=int(np.count_nonzero(~grounded)),
                seam=p.seam,
                structure_built=p.structure_built,
                min_y=int(p.ys.min()) if built else 0,
                max_y=int(p.ys.max()) if built else 0,
                inhabited=c.inhabited_ticks,
                saved=p.saved,
            )
        )


def _near(coords: set[tuple[int, int]]) -> set[tuple[int, int]]:
    return {(x + dx, z + dz) for x, z in coords for dx in (-1, 0, 1) for dz in (-1, 0, 1)}


def scan_region(job: RegionJob) -> RegionScan:
    """Analyze every generated chunk of one region file."""
    scan = RegionScan(job.relpath)
    header = parse_header(job.data, job.region_x, job.region_z)
    if header is None:
        return scan
    raw_chunks: list[tuple[int, bytes]] = []
    for slot in to_ints(np.flatnonzero(header.present)):
        try:
            raw = chunk_bytes(job.data, header, slot)
        except ChunkError as e:
            scan.chunks_failed += 1
            if len(scan.errors) < MAX_ERRORS:
                scan.errors.append(f"{job.relpath} slot {slot}: {e}")
            continue
        if raw is None:
            scan.chunks_external += 1
        else:
            raw_chunks.append((slot, raw))
    # A cheap byte search finds dungeons before decoding, so neighbours can use the rule too.
    spawners = _near(
        {
            (job.region_x * 32 + slot % 32, job.region_z * 32 + slot // 32)
            for slot, raw in raw_chunks
            if SPAWNER_BYTES in raw
        }
    )

    pending: list[_Pending] = []
    for slot, raw in raw_chunks:
        try:
            chunk = parse_chunk(nbt.decode(raw))
        except (ChunkError, nbt.NbtError) as e:
            scan.chunks_failed += 1
            if len(scan.errors) < MAX_ERRORS:
                scan.errors.append(f"{job.relpath} slot {slot}: {e}")
            continue
        if not chunk.full:
            scan.chunks_partial += 1
            continue
        scan.chunks_full += 1
        for holder in (*chunk.block_entities, *chunk.entities):
            scan.texts.extend(texts_of(holder))
        scan.structures.update(chunk.structures)
        if SPAWNER_BYTES in raw:
            scan.structures["dungeon"] += 1
        saved = item(header.timestamps, slot)
        near = (chunk.x, chunk.z) in spawners
        pending.append(_classify(chunk, saved, scan, near_spawner=near, likely=_likely(chunk, job)))
    _finish(pending, job.region_x, job.region_z, scan)
    return scan


def scan_entities(job: RegionJob) -> RegionScan:
    """Texts (names, books in item frames and minecarts, ...) from an entities/ region file."""
    scan = RegionScan(job.relpath)
    header = parse_header(job.data, job.region_x, job.region_z)
    if header is None:
        return scan
    for slot in to_ints(np.flatnonzero(header.present)):
        try:
            raw = chunk_bytes(job.data, header, slot)
            if raw is None:
                scan.chunks_external += 1
                continue
            root = nbt.decode(raw)
        except (ChunkError, nbt.NbtError) as e:
            scan.chunks_failed += 1
            if len(scan.errors) < MAX_ERRORS:
                scan.errors.append(f"{job.relpath} slot {slot}: {e}")
            continue
        entities = root.get("Entities")
        if isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict):
                    scan.texts.extend(texts_of(entity))
    return scan
