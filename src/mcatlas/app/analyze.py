"""Scan sources, run analyzers incrementally and record the results."""

import fnmatch
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from mcatlas.core import analyze
from mcatlas.core.discovery import classify
from mcatlas.core.facts import Facts, ImageFacts
from mcatlas.core.model import Mapper, WorldLayout, WorldListing, serial_map
from mcatlas.ports import FactStore, WorldSource

ICON = "icon.png"
MAP_IMAGES = f"{analyze.MAPS.name}/"
"""Asset prefix of the in-game map images."""

type Progress = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class AnalyzeOptions:
    tier: int = 1
    world_glob: str | None = None
    """Only analyze worlds whose folder name or path matches (case-insensitive)."""
    force: bool = False
    jobs: int = 8


@dataclass(slots=True)
class AnalyzeReport:
    worlds: int = 0
    analyzed: int = 0
    up_to_date: int = 0
    forgotten: int = 0
    failures: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])
    """(folder, analyzer, error) for every analyzer run that raised."""


@dataclass(frozen=True, slots=True)
class _Outcome:
    listing: WorldListing
    results: list[tuple[analyze.Analyzer[Facts], str | None, str | None]]
    icon: bytes | None
    images: dict[str, dict[str, bytes]]
    """Images per analyzer that makes them (empty when it failed or did not apply)."""


def _quiet(_message: str) -> None:
    return


def _matches(listing: WorldListing, pattern: str) -> bool:
    pat = pattern.casefold()
    return any(
        fnmatch.fnmatch(candidate.casefold(), pat)
        for candidate in (listing.folder_name, listing.relpath, str(listing.world_id))
    )


def _run(
    source: WorldSource,
    listing: WorldListing,
    layout: WorldLayout,
    todo: Sequence[analyze.Analyzer[Facts]],
    *,
    want_icon: bool,
    mapper: Mapper,
) -> _Outcome:
    results: list[tuple[analyze.Analyzer[Facts], str | None, str | None]] = []
    icon: bytes | None = None
    images: dict[str, dict[str, bytes]] = {
        a.name: {} for a in todo if issubclass(a.model, ImageFacts)
    }
    with source.open(listing) as files:
        for analyzer in todo:
            if not analyzer.applies(layout):
                results.append((analyzer, None, None))  # not applicable, cached as such
                continue
            try:
                facts = analyzer.run(files, layout, mapper)
                results.append((analyzer, facts.model_dump_json(), None))
                if isinstance(facts, ImageFacts):
                    images[analyzer.name] = facts.images
            except Exception as e:  # noqa: BLE001 - one broken world must not stop the run
                results.append((analyzer, None, f"{type(e).__name__}: {e}"))
        if want_icon and layout.icon is not None:
            try:
                icon = files.read_bytes(layout.icon)
            except OSError:
                icon = None
    return _Outcome(listing, results, icon, images)


def analyze_sources(
    sources: Sequence[WorldSource],
    store: FactStore,
    options: AnalyzeOptions,
    progress: Progress | None = None,
    mapper: Mapper = serial_map,
) -> AnalyzeReport:
    """Analyze all worlds of `sources`; `mapper` may run heavy pure work in worker processes."""
    report = AnalyzeReport()
    analyzers = analyze.for_tier(options.tier)
    say: Progress = progress or _quiet

    for source in sources:
        say(f"scanning {source.source_id} …")
        listings = list(source.scan())
        if options.world_glob is None:
            report.forgotten += store.forget_missing(
                source.source_id, {listing.world_id for listing in listings}
            )
        else:
            listings = [x for x in listings if _matches(x, options.world_glob)]
        say(f"{source.source_id}: {len(listings)} worlds")

        jobs: list[tuple[WorldListing, WorldLayout, list[analyze.Analyzer[Facts]], bool]] = []
        for listing in listings:
            layout = classify(listing.files)
            store.record_world(listing, layout)
            fingerprint = listing.fingerprint()
            todo = [
                a
                for a in analyzers
                if options.force
                or not store.is_current(listing.world_id, a.name, a.version, fingerprint)
            ]
            want_icon = layout.icon is not None and (
                options.force or not store.has_asset(listing.world_id, ICON, fingerprint)
            )
            report.worlds += 1
            if todo or want_icon:
                jobs.append((listing, layout, todo, want_icon))
            else:
                report.up_to_date += 1

        with ThreadPoolExecutor(options.jobs, thread_name_prefix="analyze") as pool:
            futures = [
                pool.submit(_run, source, listing, layout, todo, want_icon=want_icon, mapper=mapper)
                for listing, layout, todo, want_icon in jobs
            ]
            for n, future in enumerate(as_completed(futures), start=1):
                outcome = future.result()
                listing = outcome.listing
                fingerprint = listing.fingerprint()
                for analyzer, payload, error in outcome.results:
                    store.save_facts(
                        listing.world_id,
                        analyzer.name,
                        analyzer.version,
                        fingerprint,
                        payload=payload,
                        error=error,
                    )
                    if error is not None:
                        report.failures.append((listing.folder_name, analyzer.name, error))
                if outcome.icon is not None:
                    store.save_asset(listing.world_id, ICON, fingerprint, outcome.icon)
                for name, images in outcome.images.items():
                    store.replace_assets(listing.world_id, f"{name}/", fingerprint, images)
                report.analyzed += 1
                say(f"[{n}/{len(jobs)}] {listing.folder_name}")
    return report
