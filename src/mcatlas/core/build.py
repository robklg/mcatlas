"""Summarize block facts into what a person looking for a world wants to know.

* How much did players build, and how much of it underground?
* Where: *build sites* (hotspots) are groups of built chunks at most `SITE_GAP` chunks apart,
  each with coordinates to teleport to, so nothing gets overlooked when revisiting a world.
* A per-chunk map (built and time spent) for drawing, kept apart from the catalog because it
  can be large.
"""

from collections import Counter
from typing import Final

from pydantic import Field

from mcatlas.core.facts import BlockFacts, ChunkTable, DimensionBlocks, Facts

SITE_CHUNK_MIN: Final = 8
"""A chunk takes part in a build site from this many built blocks."""
SITE_GAP: Final = 2
"""Chunks at most this far apart (Chebyshev, in chunks) belong to the same site."""
SITE_MIN: Final = 100
"""Smallest build site worth listing, in built blocks."""
MAX_SITES: Final = 15
PCT_MIN_BUILT: Final = 100
"""Below this many grounded built blocks the underground share is not meaningful."""
TICKS_PER_HOUR: Final = 72_000
TOP_BLOCKS: Final = 25
GENERATED_DIMENSION_PREFIX: Final = "legacy:"
"""Dimensions of 20w14infinite: their terrain is made of random blocks, not building."""


class BuildSite(Facts):
    dimension: str
    x: int
    """Built-weighted centre, block coordinates."""
    z: int
    bbox: tuple[int, int, int, int]
    """(min_x, min_z, max_x, max_z) in block coordinates."""
    chunks: int
    built: int
    below: int
    no_ground: int
    min_y: int
    max_y: int
    pct_below: float | None
    hours_nearby: float
    """Most time spent near any of its chunks (InhabitedTime; nearby chunks all count)."""
    last_saved: int | None = None
    """Unix time of the latest save of any of its chunks: roughly when someone was last there."""


class BuildSummary(Facts):
    built: int = 0
    below: int = 0
    no_ground: int = 0
    structure_built: int = 0
    """Non-natural blocks attributed to generated structures, dungeons and villages."""
    history_built: int = 0
    """Built blocks in chunks last saved before our players arrived (makers of a map)."""
    modded: int = 0
    modded_blocks: list[tuple[str, int]] = Field(default_factory=list[tuple[str, int]])
    seam: int = 0
    pct_below: float | None = None
    """Share of built blocks (with ground in their column) under the natural surface."""
    built_chunks: int = 0
    main_dimension: str | None = None
    by_section: dict[int, int] = Field(default_factory=dict[int, int])
    """Built blocks per 16-high layer of the main dimension (key = y // 16)."""
    top_blocks: list[tuple[str, int]] = Field(default_factory=list[tuple[str, int]])
    """Across the whole world, including any history (block counts are not kept per chunk)."""
    structures: dict[str, int] = Field(default_factory=dict[str, int])
    sites: list[BuildSite] = Field(default_factory=list[BuildSite])
    excluded_dimensions: list[str] = Field(default_factory=list[str])
    chunks_scanned: int = 0
    chunks_skipped: int = 0
    """Proto, external (.mcc) and unreadable chunks."""


class DimensionMap(Facts):
    key: str
    x: list[int] = Field(default_factory=list[int])
    z: list[int] = Field(default_factory=list[int])
    built: list[int] = Field(default_factory=list[int])
    below: list[int] = Field(default_factory=list[int])
    minutes: list[int] = Field(default_factory=list[int])
    """Minutes of player presence nearby (InhabitedTime)."""


class BuildMap(Facts):
    dimensions: list[DimensionMap] = Field(default_factory=list[DimensionMap])


class _Groups:
    """Union-find over chunk indices."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def build_sites(key: str, t: ChunkTable) -> list[BuildSite]:
    idx = [i for i, b in enumerate(t.built) if b >= SITE_CHUNK_MIN]
    at = {(t.x[i], t.z[i]): n for n, i in enumerate(idx)}
    groups = _Groups(len(idx))
    for n, i in enumerate(idx):
        for dx in range(-SITE_GAP, SITE_GAP + 1):
            for dz in range(-SITE_GAP, SITE_GAP + 1):
                other = at.get((t.x[i] + dx, t.z[i] + dz))
                if other is not None and other != n:
                    groups.union(n, other)
    members: dict[int, list[int]] = {}
    for n, i in enumerate(idx):
        members.setdefault(groups.find(n), []).append(i)

    sites: list[BuildSite] = []
    for rows in members.values():
        built = sum(t.built[i] for i in rows)
        if built < SITE_MIN:
            continue
        below = sum(t.below[i] for i in rows)
        no_ground = sum(t.no_ground[i] for i in rows)
        xs = [t.x[i] for i in rows]
        zs = [t.z[i] for i in rows]
        sites.append(
            BuildSite(
                dimension=key,
                x=round(sum((t.x[i] * 16 + 8) * t.built[i] for i in rows) / built),
                z=round(sum((t.z[i] * 16 + 8) * t.built[i] for i in rows) / built),
                bbox=(min(xs) * 16, min(zs) * 16, max(xs) * 16 + 15, max(zs) * 16 + 15),
                chunks=len(rows),
                built=built,
                below=below,
                no_ground=no_ground,
                pct_below=_pct(below, built - no_ground),
                min_y=min(t.min_y[i] for i in rows),
                max_y=max(t.max_y[i] for i in rows),
                hours_nearby=round(max(t.inhabited[i] for i in rows) / TICKS_PER_HOUR, 1),
                last_saved=max((t.saved[i] for i in rows), default=0) or None,
            )
        )
    return sites


def _map(dim: DimensionBlocks) -> DimensionMap:
    t = dim.table
    return DimensionMap(
        key=dim.key,
        x=t.x,
        z=t.z,
        built=t.built,
        below=t.below,
        minutes=[v // 1200 for v in t.inhabited],
    )


def _pct(below: int, grounded: int) -> float | None:
    return round(100 * below / grounded, 1) if grounded >= PCT_MIN_BUILT else None


def _ours(t: ChunkTable, cutoff: int | None) -> tuple[ChunkTable, int]:
    """Blank out chunks last saved before our players arrived; return them as history."""
    if cutoff is None:
        return t, 0
    old = {i for i, saved in enumerate(t.saved) if 0 < saved < cutoff and t.built[i]}
    if not old:
        return t, 0

    def keep(column: list[int]) -> list[int]:
        return [0 if i in old else v for i, v in enumerate(column)]

    history = sum(t.built[i] for i in old)
    update = {"built": keep(t.built), "below": keep(t.below), "no_ground": keep(t.no_ground)}
    return t.model_copy(update=update), history


def summarize(
    facts: BlockFacts, *, history_before: int | None = None
) -> tuple[BuildSummary, BuildMap]:
    """`history_before` (Unix time): chunks last saved earlier were built by others (makers)."""
    dims: list[DimensionBlocks] = []
    excluded: list[str] = []
    history = 0
    for d in facts.dimensions:
        if d.key.startswith(GENERATED_DIMENSION_PREFIX):
            excluded.append(d.key)
            continue
        table, old = _ours(d.table, history_before)
        history += old
        dims.append(d.model_copy(update={"table": table}))
    if not dims:
        return BuildSummary(excluded_dimensions=excluded), BuildMap()

    def built_of(d: DimensionBlocks) -> int:
        return sum(d.table.built)

    main = max(dims, key=lambda d: (built_of(d), d.key == "minecraft:overworld"))
    blocks: Counter[str] = Counter()
    modded: Counter[str] = Counter()
    structures: Counter[str] = Counter()
    sites: list[BuildSite] = []
    for d in dims:
        blocks.update(d.blocks)
        modded.update(d.modded_blocks)
        structures.update(d.structures)
        sites.extend(build_sites(d.key, d.table))
    built = sum(built_of(d) for d in dims)
    below = sum(sum(d.table.below) for d in dims)
    no_ground = sum(sum(d.table.no_ground) for d in dims)
    summary = BuildSummary(
        built=built,
        below=below,
        no_ground=no_ground,
        structure_built=sum(d.structure_built for d in dims),
        history_built=history,
        modded=sum(d.modded for d in dims),
        modded_blocks=modded.most_common(TOP_BLOCKS),
        seam=sum(d.seam for d in dims),
        pct_below=_pct(below, built - no_ground),
        built_chunks=sum(1 for d in dims for b in d.table.built if b >= SITE_CHUNK_MIN),
        main_dimension=main.key if built_of(main) else None,
        by_section=dict(main.built_by_section),
        top_blocks=blocks.most_common(TOP_BLOCKS),
        structures=dict(structures.most_common()),
        sites=sorted(sites, key=lambda s: -s.built)[:MAX_SITES],
        excluded_dimensions=excluded,
        chunks_scanned=sum(d.chunks_full for d in dims),
        chunks_skipped=sum(d.chunks_partial + d.chunks_external + d.chunks_failed for d in dims),
    )
    return summary, BuildMap(dimensions=[_map(d) for d in dims if d.table.x])
