"""Static catalog site: plain HTML/CSS/JS plus the catalog as a script file.

The catalog is embedded as `data/catalog.js` (not fetched as JSON), so the site also works when
opened straight from disk via file://. Per-world chunk maps go to `data/maps/<id>.js`, which the
page loads on demand with a script tag (that works from file:// as well). All texts (signs,
books, names) go to `data/texts.js`, loaded after the page so that search can use them.
"""

import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Final

from mcatlas.adapters.outputs import atomic_write, write_if_changed
from mcatlas.core.annotations import Annotation
from mcatlas.core.catalog import Catalog
from mcatlas.core.model import Language, WorldId

_ASSETS: Final = ("index.html", "style.css", "i18n.js", "app.js")


def _write(path: Path, data: bytes) -> None:
    atomic_write(path, data)


def _safe_relpath(relpath: str) -> Path:
    path = Path(relpath)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"not a relative path inside the site: {relpath!r}")
    return path


def _script(assignment: str, payload: str) -> bytes:
    # "</" must not appear inside a <script>-loaded file that could be inlined later.
    body = payload.replace("</", "<\\/")
    return (
        f"window.MCATLAS_MAPS = window.MCATLAS_MAPS || {{}};\nwindow.{assignment}{body};\n".encode()
    )


class StaticSiteWriter:
    def __init__(self, site_dir: Path, *, language: Language = "en") -> None:
        self._dir = site_dir
        self._language: Language = language

    def write(
        self,
        catalog: Catalog,
        icons: Mapping[WorldId, bytes],
        images: Mapping[str, bytes] | None = None,
    ) -> str:
        assets = resources.files("mcatlas.adapters.site_assets")
        for name in _ASSETS:
            _write(self._dir / name, assets.joinpath(name).read_bytes())
        # Notes live in their own file so that saving one note only rewrites that file.
        payload = catalog.model_dump_json(
            exclude={
                "maps": True,
                "footprints": True,
                "texts": True,
                "annotations": True,
                "worlds": {"__all__": {"annotation"}},
            }
        )
        # The default language; visitors can switch on the site (their choice is remembered).
        default = f"window.MCATLAS_LANG = {json.dumps(self._language)};\n".encode()
        _write(self._dir / "data" / "catalog.js", default + _script("MCATLAS_CATALOG = ", payload))
        for world_id, build_map in catalog.maps.items():
            key = json.dumps(world_id)
            _write(
                self._dir / "data" / "maps" / f"{world_id}.js",
                _script(f"MCATLAS_MAPS[{key}] = ", build_map.model_dump_json()),
            )
        for world in catalog.worlds:
            icon = icons.get(world.world_id)
            if icon is not None:
                _write(self._dir / "icons" / f"{world.world_id}.png", icon)
        texts = {
            world_id: [
                [t.kind, t.text, t.holder, t.dimension, t.x, t.y, t.z, int(t.history)]
                for t in entries
            ]
            for world_id, entries in catalog.texts.items()
        }
        _write(
            self._dir / "data" / "texts.js",
            _script("MCATLAS_TEXTS = ", json.dumps(texts, ensure_ascii=False)),
        )
        for relpath, data in (images or {}).items():
            # Flat maps are large and rarely change; skip rewriting them over a network share.
            write_if_changed(self._dir / _safe_relpath(relpath), data)
        self.write_annotations(catalog.annotations)
        return str(self._dir / "index.html")

    def write_annotations(self, annotations: Mapping[WorldId, Annotation]) -> None:
        payload = json.dumps(
            {w: a.model_dump(mode="json") for w, a in annotations.items()}, ensure_ascii=False
        )
        _write(self._dir / "data" / "annotations.js", _script("MCATLAS_ANNOTATIONS = ", payload))
