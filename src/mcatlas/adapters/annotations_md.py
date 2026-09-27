"""Annotations as Markdown files with TOML front matter, one per world (see core.annotations).

The directory lives next to the archive so that the notes stay with the worlds; it is an output
path, so the guard refuses it if it were ever inside a world source. A README (in the configured
language, written once and then left alone) explains the format for whoever finds the folder
years from now.
"""

from pathlib import Path

from mcatlas.adapters.outputs import atomic_write, remove
from mcatlas.core.annotations import (
    Annotation,
    AnnotationError,
    format_annotation,
    parse_annotation,
)
from mcatlas.core.model import Language, WorldId
from mcatlas.core.words import WORDS


class AnnotationStoreError(RuntimeError):
    pass


class MarkdownAnnotations:
    def __init__(self, directory: Path | None, *, language: Language = "en") -> None:
        self._dir = directory
        self._readme = WORDS[language].notes_readme

    def _files(self) -> list[Path]:
        if self._dir is None or not self._dir.is_dir():
            return []
        return sorted(
            p
            for p in self._dir.glob("*.md")
            if p.name != "README.md" and not p.name.startswith(".")
        )

    def _read(self) -> tuple[dict[WorldId, tuple[Path, Annotation]], list[str]]:
        found: dict[WorldId, tuple[Path, Annotation]] = {}
        problems: list[str] = []
        for path in self._files():
            try:
                annotation = parse_annotation(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, AnnotationError) as e:
                problems.append(f"{path.name}: {e}")
                continue
            if annotation.world in found:
                other = found[annotation.world][0].name
                problems.append(f"{path.name}: world {annotation.world} also in {other}")
                continue
            found[annotation.world] = (path, annotation)
        return found, problems

    def load(self) -> tuple[dict[WorldId, Annotation], list[str]]:
        found, problems = self._read()
        return {w: a for w, (_, a) in found.items()}, problems

    def save(self, annotation: Annotation) -> str:
        if self._dir is None:
            raise AnnotationStoreError(
                "no annotations directory configured (paths.annotations_dir or paths.atlas_dir)"
            )
        found, _ = self._read()
        existing = found.get(annotation.world)
        path = existing[0] if existing else self._dir / f"{annotation.world}.md"
        if annotation.is_empty:
            remove(path)
            return f"{path} (removed: empty)"
        if not (self._dir / "README.md").exists():
            atomic_write(self._dir / "README.md", self._readme.encode())
        atomic_write(path, format_annotation(annotation).encode())
        return str(path)
