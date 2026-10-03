"""Render 3D maps: copy what each map needs through the read-only source, then render.

Only maps whose plan or copied files changed are rendered again (unless forced). A change in
the texts for people only (another language) updates the markers, not the tiles.
"""

import fnmatch
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from mcatlas.core.catalog import WorldEntry
from mcatlas.core.discovery import classify
from mcatlas.core.model import Generator, Language, WorldFormat
from mcatlas.core.render import MIN_DATA_VERSION, MapPlan, plan_maps, staged_path, without_texts
from mcatlas.ports import Renderer, WorldSource

type Progress = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class RenderOptions:
    world_glob: str | None = None
    force: bool = False
    pad: int = 32
    spawn_radius: int = 96
    max_side: int = 2048
    language: Language = "en"


@dataclass(slots=True)
class RenderReport:
    maps: int = 0
    rendered: int = 0
    up_to_date: int = 0
    copied_files: int = 0
    copied_bytes: int = 0
    removed_files: int = 0
    images: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """(world name, reason) for selected worlds that got no map."""


def _quiet(_message: str) -> None:
    return


def _selected(entry: WorldEntry, pattern: str | None) -> bool:
    if pattern is None:
        return True
    pat = pattern.casefold()
    return any(
        fnmatch.fnmatch(c.casefold(), pat)
        for c in (entry.folder_name, entry.relpath, entry.world_id)
    )


def _why_not(entry: WorldEntry) -> str:
    if entry.format is not WorldFormat.ANVIL:
        return f"no terrain BlueMap can read ({entry.format.value})"
    if (entry.data_version or 0) < MIN_DATA_VERSION:
        return "saved before Minecraft 1.13: older chunk format"
    if entry.generator is Generator.DEBUG:
        return "debug world: every block once, nothing built"
    if entry.build is None:
        return "not analyzed yet: run `mcatlas analyze --tier 2`"
    return "nothing to render (no build site and no spawn area in a region file)"


def render_worlds(
    sources: Sequence[WorldSource],
    entries: Sequence[WorldEntry],
    renderer: Renderer,
    options: RenderOptions,
    progress: Progress | None = None,
) -> RenderReport:
    """`entries` in catalog order (most important first): that is the order of the maps."""
    say: Progress = progress or _quiet
    report = RenderReport()
    rank = {e.world_id: i for i, e in enumerate(entries)}
    by_id = {e.world_id: e for e in entries}
    previous = {m.map_id: m for m in renderer.rendered()}
    plans: dict[str, MapPlan] = {}
    changed: set[str] = set()

    for source in sources:
        say(f"scanning {source.source_id} …")
        for listing in source.scan():
            entry = by_id.get(listing.world_id)
            if entry is None or not _selected(entry, options.world_glob):
                continue
            layout = classify(listing.files)
            world_plans = plan_maps(
                entry,
                layout,
                pad_blocks=options.pad,
                spawn_radius=options.spawn_radius,
                max_side=options.max_side,
                sorting=rank[entry.world_id],
                language=options.language,
            )
            if not world_plans:
                report.skipped.append((entry.name, _why_not(entry)))
                continue
            sources_needed = {world_plans[0].level_file} | {
                f for p in world_plans for f in p.region_files
            }
            needed = {staged_path(layout, rel): rel for rel in sources_needed}
            have = renderer.staged(entry.world_id)
            files = {f.relpath: f for f in listing.files}
            todo = [
                (staged, rel)
                for staged, rel in sorted(needed.items())
                if have.get(staged) != (files[rel].size, files[rel].mtime_ns)
            ]
            if todo:
                say(f"copying {len(todo)} file(s) of {entry.name}")
                with source.open(listing) as world:
                    for staged, rel in todo:
                        data = world.read_bytes(rel)
                        renderer.stage(entry.world_id, staged, data, files[rel].mtime_ns)
                        report.copied_files += 1
                        report.copied_bytes += len(data)
            report.removed_files += renderer.unstage(entry.world_id, needed.keys())
            for plan in world_plans:
                plans[plan.map_id] = plan
                before = previous.get(plan.map_id)
                same_plan = before is not None and without_texts(
                    MapPlan.model_validate(before.model_dump(include=set(MapPlan.model_fields)))
                ) == without_texts(plan)
                if options.force or todo or not same_plan:
                    changed.add(plan.map_id)

    # Maps of worlds outside the selection stay configured, so the viewer keeps listing them.
    for map_id, before in previous.items():
        if (
            map_id not in plans
            and before.world_id in by_id
            and not _selected(by_id[before.world_id], options.world_glob)
        ):
            plans[map_id] = MapPlan.model_validate(
                before.model_dump(include=set(MapPlan.model_fields))
            )

    ordered = sorted(plans.values(), key=lambda p: p.sorting)
    report.maps = len(ordered)
    report.up_to_date = len([p for p in ordered if p.map_id not in changed])
    done = renderer.render(ordered, changed, force=options.force, progress=say)
    report.rendered = len(done)
    report.images = sum(len(m.images) for m in done)
    return report
