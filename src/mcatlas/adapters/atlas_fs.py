"""The durable atlas as a folder next to the archive (see core.atlas).

Only files that changed are written, so re-running an export over a network share is cheap and
leaves unchanged files (and their dates) alone. A small list of what the export wrote,
`.mcatlas-export.json`, lets the next export remove exactly its own files that are no longer
needed (a world that left the archive), and nothing else: the notes folder and anything people
put in the folder themselves are never touched.
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Final, cast

from mcatlas.adapters.guard import check_output_path
from mcatlas.adapters.outputs import atomic_write, remove, write_if_changed
from mcatlas.core.atlas import AtlasChanges

WRITTEN_LIST: Final = ".mcatlas-export.json"


class AtlasPathError(ValueError):
    """A file the export must not write."""


def _inside(path: Path, folder: Path) -> bool:
    real, base = os.path.realpath(path), os.path.realpath(folder)
    return real == base or real.startswith(base + os.sep)


class AtlasFolderWriter:
    def __init__(self, atlas_dir: Path, *, notes_dir: Path | None) -> None:
        self._dir = atlas_dir
        self._notes = notes_dir

    def _target(self, relpath: str) -> Path:
        rel = PurePosixPath(relpath)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.name == WRITTEN_LIST:
            raise AtlasPathError(f"not a file inside the atlas: {relpath!r}")
        path = self._dir.joinpath(*rel.parts)
        if self._notes is not None and _inside(path, self._notes):
            raise AtlasPathError(f"the export never writes into the notes folder: {relpath!r}")
        return path

    def _previous(self) -> set[str]:
        try:
            raw = cast("object", json.loads((self._dir / WRITTEN_LIST).read_text("utf-8")))
        except OSError, ValueError:
            return set()
        if not isinstance(raw, dict):
            return set()
        files = cast("dict[str, object]", raw).get("files")
        if not isinstance(files, list):
            return set()
        return {f for f in cast("list[object]", files) if isinstance(f, str)}

    def _prune(self, path: Path) -> None:
        """Remove folders the export emptied, up to (not including) the atlas folder."""
        base = os.path.realpath(self._dir)
        folder = path.parent
        while os.path.realpath(folder).startswith(base + os.sep):
            try:
                check_output_path(folder).rmdir()
            except OSError:
                return  # not empty (or gone): stop
            folder = folder.parent

    def write(self, files: Mapping[str, bytes]) -> AtlasChanges:
        check_output_path(self._dir)
        targets = {rel: self._target(rel) for rel in files}
        written = unchanged = 0
        for rel in sorted(files):
            if write_if_changed(targets[rel], files[rel]):
                written += 1
            else:
                unchanged += 1
        removed = 0
        for rel in sorted(self._previous() - set(files)):
            try:
                path = self._target(rel)
            except AtlasPathError:
                continue  # a tampered list: never delete outside our own files
            if path.is_file():
                remove(path)
                removed += 1
                self._prune(path)
        listing = {"about": "Files written by mcatlas export-atlas.", "files": sorted(files)}
        atomic_write(
            self._dir / WRITTEN_LIST,
            (json.dumps(listing, indent=1, ensure_ascii=False) + "\n").encode(),
        )
        return AtlasChanges(str(self._dir), written, unchanged, removed)
