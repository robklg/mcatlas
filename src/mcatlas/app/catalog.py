"""Build the catalog from stored facts and notes, and publish it as a static site."""

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, tzinfo

from mcatlas.app.analyze import ICON, MAP_IMAGES
from mcatlas.core.catalog import Catalog, build_catalog
from mcatlas.ports import AnnotationStore, FactStore, Renderer, SiteWriter


def load_catalog(
    store: FactStore,
    names: Mapping[str, str],
    tz: tzinfo,
    *,
    ignore_file_days: Iterable[date] = (),
    notes: AnnotationStore | None = None,
    renderer: Renderer | None = None,
) -> tuple[Catalog, list[str]]:
    """The catalog, plus problems found while reading notes."""
    annotations, problems = notes.load() if notes is not None else ({}, [])
    renders = renderer.rendered() if renderer is not None else []
    catalog = build_catalog(
        store.worlds(),
        names,
        tz,
        datetime.now(UTC),
        ignore_file_days=frozenset(ignore_file_days),
        annotations=annotations,
        renders=renders,
    )
    return catalog, problems


def publish_site(
    store: FactStore,
    writer: SiteWriter,
    names: Mapping[str, str],
    tz: tzinfo,
    *,
    ignore_file_days: Iterable[date] = (),
    notes: AnnotationStore | None = None,
    renderer: Renderer | None = None,
) -> tuple[Catalog, str, list[str]]:
    catalog, problems = load_catalog(
        store, names, tz, ignore_file_days=ignore_file_days, notes=notes, renderer=renderer
    )
    images = flat_images(catalog, renderer, problems)
    for world_id, maps in store.asset_group(MAP_IMAGES).items():
        for name, data in maps.items():
            images[f"{SITE_MAPS}/{world_id}/{name}"] = data
    return catalog, writer.write(catalog, store.assets(ICON), images), problems


SITE_MAPS = "ingame"
"""Site folder of the in-game map images: ingame/<world id>/<image>."""


def flat_images(
    catalog: Catalog, renderer: Renderer | None, problems: list[str]
) -> dict[str, bytes]:
    """The flat maps of all 3D renders by render path; unreadable ones go to `problems`."""
    images: dict[str, bytes] = {}
    if renderer is not None:
        for maps in catalog.renders.values():
            for path in (p for m in maps for p in m.images.values()):
                try:
                    images[path] = renderer.image(path)
                except OSError as e:
                    problems.append(f"flat map {path}: {e}")
    return images
