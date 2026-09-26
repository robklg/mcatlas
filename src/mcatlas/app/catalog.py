"""Build the catalog from stored facts and notes, and publish it as a static site."""

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, tzinfo

from mcatlas.app.analyze import ICON
from mcatlas.core.catalog import Catalog, build_catalog
from mcatlas.ports import AnnotationStore, FactStore, SiteWriter


def load_catalog(
    store: FactStore,
    names: Mapping[str, str],
    tz: tzinfo,
    *,
    ignore_file_days: Iterable[date] = (),
    notes: AnnotationStore | None = None,
) -> tuple[Catalog, list[str]]:
    """The catalog, plus problems found while reading notes."""
    annotations, problems = notes.load() if notes is not None else ({}, [])
    catalog = build_catalog(
        store.worlds(),
        names,
        tz,
        datetime.now(UTC),
        ignore_file_days=frozenset(ignore_file_days),
        annotations=annotations,
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
) -> tuple[Catalog, str, list[str]]:
    catalog, problems = load_catalog(
        store, names, tz, ignore_file_days=ignore_file_days, notes=notes
    )
    return catalog, writer.write(catalog, store.assets(ICON)), problems
