"""Export the durable atlas: the catalog as plain files next to the archive (see core.atlas)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, tzinfo

from mcatlas.app.analyze import ICON
from mcatlas.app.catalog import flat_images, load_catalog
from mcatlas.core.atlas import AtlasChanges, atlas_files
from mcatlas.core.model import Language
from mcatlas.ports import AnnotationStore, AtlasWriter, FactStore, Renderer


@dataclass(frozen=True, slots=True)
class ExportReport:
    worlds: int
    files: int
    images: int
    written: AtlasChanges
    problems: list[str]


def export_atlas(
    store: FactStore,
    writer: AtlasWriter,
    names: Mapping[str, str],
    tz: tzinfo,
    *,
    today: date,
    tool: str,
    ignore_file_days: Iterable[date] = (),
    notes: AnnotationStore | None = None,
    renderer: Renderer | None = None,
    language: Language = "en",
) -> ExportReport:
    catalog, problems = load_catalog(
        store, names, tz, ignore_file_days=ignore_file_days, notes=notes, renderer=renderer
    )
    images = flat_images(catalog, renderer, problems)
    files = atlas_files(
        catalog,
        icons=store.assets(ICON),
        images=images,
        generated=today,
        tool=tool,
        language=language,
    )
    return ExportReport(
        worlds=len(catalog.worlds),
        files=len(files),
        images=sum(1 for path in files if path.endswith(".png")),
        written=writer.write(files),
        problems=problems,
    )
