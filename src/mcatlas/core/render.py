"""What to render in 3D: per world and dimension, the areas around its build sites.

A renderer (BlueMap) never reads the archive itself. mcatlas copies the few files a map needs
into the renderer's workspace first, so a plan also names those files: the level file and the
region files that overlap the areas.

Coordinates are blocks; boxes are inclusive (min_x, min_z, max_x, max_z) like `BuildSite.bbox`.
"""

import re
from datetime import datetime
from typing import TYPE_CHECKING, Final

from pydantic import Field

from mcatlas.core.discovery import parse_region_name
from mcatlas.core.facts import Facts
from mcatlas.core.model import (
    NETHER,
    OVERWORLD,
    THE_END,
    DimensionLayout,
    Language,
    WorldFormat,
    WorldId,
    WorldLayout,
)
from mcatlas.core.words import WORDS, Words, num

if TYPE_CHECKING:
    from mcatlas.core.catalog import WorldEntry

RENDER_VERSION: Final = 1
"""Bump when plans change in a way that needs a re-render (texts for people do not)."""
REGION_BLOCKS: Final = 512
MIN_DATA_VERSION: Final = 1451
"""1.13: older chunk formats are not rendered."""
CAVES_PCT_BELOW: Final = 25.0
"""Render caves too when a map's sites have at least this share built underground."""
NETHER_ROOF_Y: Final = 120
"""Nether areas are cut below the bedrock roof, otherwise only the roof would be visible."""

DIMENSIONS: Final[dict[str, str]] = {OVERWORLD: "", NETHER: "nether", THE_END: "end"}
"""Dimensions that can be rendered, with the suffix of their map id."""
DIMENSION_NAMES: Final[dict[str, str]] = {OVERWORLD: "", NETHER: "Nether", THE_END: "End"}

_MAP_ID_STRIP: Final = re.compile(r"[^A-Za-z0-9_]")

type Box = tuple[int, int, int, int]


class RenderArea(Facts):
    label: str
    """"Site 1" for build site 1 (numbered as in the catalog), or "Spawn"."""
    site: int | None = None
    """Index into `WorldEntry.build.sites`; None for the spawn area."""
    box: Box
    x: int
    """Where to look: the centre of the build (built-weighted) or the spawn point."""
    y: int
    z: int
    max_y: int | None = None
    """Blocks above this height are left out (Nether roof)."""
    detail: str = ""
    """One line for people, shown with the marker in the 3D view."""


class MapPlan(Facts):
    map_id: str
    world_id: WorldId
    world_name: str
    dimension: str
    name: str
    sorting: int
    areas: list[RenderArea] = Field(default_factory=list[RenderArea])
    marker_set: str = ""
    """Name of the markers in the 3D view."""
    show_caves: bool = False
    """Keep dark underground blocks (costlier); on where much was built below the surface."""
    level_file: str
    region_files: list[str] = Field(default_factory=list[str])
    """Relative paths of the region files the areas overlap (only those that exist)."""


class RenderedMap(MapPlan):
    rendered_at: datetime | None = None
    images: dict[int, str] = Field(default_factory=dict[int, str])
    """Area index -> relative path of its flat top-down image."""
    heights: dict[int, int] = Field(default_factory=dict[int, int])
    """Area index -> height of the top block at the area's centre, as rendered."""
    stale_tiles: int = 0
    """Tiles the renderer could not replace (a network share held the old file), so they
    show an earlier render. Tiles whose new version was identical are not counted."""


def map_id(world_id: WorldId, dimension: str) -> str:
    """BlueMap map ids may only hold letters, digits and underscores (it rewrites the rest)."""
    suffix = DIMENSIONS.get(dimension)
    if suffix is None:
        raise ValueError(f"dimension cannot be rendered: {dimension}")
    base = _MAP_ID_STRIP.sub("_", world_id)
    return f"{base}__{suffix}" if suffix else base


def pad(box: Box, blocks: int) -> Box:
    return (box[0] - blocks, box[1] - blocks, box[2] + blocks, box[3] + blocks)


def clamp(box: Box, x: int, z: int, max_side: int) -> Box:
    """Shrink a box to at most `max_side` blocks per side, keeping (x, z) inside."""

    def side(lo: int, hi: int, centre: int) -> tuple[int, int]:
        if hi - lo + 1 <= max_side:
            return lo, hi
        start = min(max(centre - max_side // 2, lo), hi - max_side + 1)
        return start, start + max_side - 1

    x0, x1 = side(box[0], box[2], x)
    z0, z1 = side(box[1], box[3], z)
    return (x0, z0, x1, z1)


def regions(box: Box) -> set[tuple[int, int]]:
    """Region files (r.X.Z) that hold blocks of the box."""
    return {
        (rx, rz)
        for rx in range(box[0] // REGION_BLOCKS, box[2] // REGION_BLOCKS + 1)
        for rz in range(box[1] // REGION_BLOCKS, box[3] // REGION_BLOCKS + 1)
    }


def _site_detail(w: Words, built: int, pct_below: float | None) -> str:
    text = w.built_detail.format(n=num(w, built))
    return text if pct_below is None else f"{text}, {w.below_detail.format(pct=num(w, pct_below))}"


def without_texts(plan: MapPlan) -> MapPlan:
    """The plan without its texts for people: those change the markers, not the tiles."""
    return plan.model_copy(
        update={
            "marker_set": "",
            "areas": [a.model_copy(update={"label": "", "detail": ""}) for a in plan.areas],
        }
    )


def _underground(entry: WorldEntry, areas: list[RenderArea]) -> bool:
    if entry.build is None:
        return False
    sites = [entry.build.sites[a.site] for a in areas if a.site is not None]
    return any((s.pct_below or 0) >= CAVES_PCT_BELOW for s in sites)


def renderable(entry: WorldEntry) -> bool:
    return (
        entry.format is WorldFormat.ANVIL
        and entry.build is not None
        and (entry.data_version or 0) >= MIN_DATA_VERSION
    )


def plan_maps(
    entry: WorldEntry,
    layout: WorldLayout,
    *,
    pad_blocks: int,
    spawn_radius: int,
    max_side: int,
    sorting: int = 0,
    language: Language = "en",
) -> list[MapPlan]:
    """One map per dimension that has build sites; the spawn area when there is no site."""
    w = WORDS[language]
    if not renderable(entry) or entry.build is None or layout.level_dat is None:
        return []
    dims: dict[str, DimensionLayout] = {d.key: d for d in layout.dimensions if d.key in DIMENSIONS}
    areas: dict[str, list[RenderArea]] = {}
    for i, site in enumerate(entry.build.sites):
        if site.dimension not in dims:
            continue
        roof = NETHER_ROOF_Y if site.dimension == NETHER else None
        areas.setdefault(site.dimension, []).append(
            RenderArea(
                label=w.site_label.format(n=i + 1),
                site=i,
                box=clamp(pad(site.bbox, pad_blocks), site.x, site.z, max_side),
                x=site.x,
                y=min(site.max_y, roof) if roof is not None else site.max_y,
                z=site.z,
                max_y=roof,
                detail=_site_detail(w, site.built, site.pct_below),
            )
        )
    if not areas and entry.spawn is not None and OVERWORLD in dims:
        x, y, z = entry.spawn
        r = spawn_radius
        areas[OVERWORLD] = [
            RenderArea(
                label=w.spawn_label,
                box=(x - r, z - r, x + r, z + r),
                x=x,
                y=y,
                z=z,
                detail=w.spawn_detail,
            )
        ]

    plans: list[MapPlan] = []
    for dimension, dim_areas in areas.items():
        layout_dim = dims[dimension]
        wanted = set[tuple[int, int]]().union(*(regions(a.box) for a in dim_areas))
        files = sorted(
            f.relpath
            for f in layout_dim.region_files
            if (parsed := parse_region_name(f.relpath.rsplit("/", 1)[-1])) is not None
            and parsed[2] == "mca"
            and (parsed[0], parsed[1]) in wanted
        )
        if not files:
            continue
        label = DIMENSION_NAMES[dimension]
        plans.append(
            MapPlan(
                map_id=map_id(entry.world_id, dimension),
                world_id=entry.world_id,
                world_name=entry.name,
                dimension=dimension,
                name=f"{entry.name} ({label})" if label else entry.name,
                sorting=sorting * 10 + list(DIMENSIONS).index(dimension),
                areas=dim_areas,
                marker_set=w.marker_set,
                show_caves=dimension != OVERWORLD or _underground(entry, dim_areas),
                level_file=layout.level_dat,
                region_files=files,
            )
        )
    return plans
