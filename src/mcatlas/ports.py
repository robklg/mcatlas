"""Ports: the interfaces between the application and the outside world.

Driven adapters in `mcatlas.adapters` implement these; `mcatlas.app` depends only on them.
The world-source port is deliberately read-only: it has no method that could change a world.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from mcatlas.core.annotations import Annotation
from mcatlas.core.catalog import Catalog, StoredWorld
from mcatlas.core.model import WorldFiles, WorldId, WorldLayout, WorldListing


class WorldSource(Protocol):
    """A read-only collection of worlds (a folder, possibly containing zip archives)."""

    @property
    def source_id(self) -> str: ...

    def scan(self) -> Iterator[WorldListing]:
        """Yield every world (and every unrecognized top-level folder) with its file listing."""
        ...

    def open(self, listing: WorldListing) -> AbstractContextManager[WorldFiles]:
        """Give read-only access to the bytes of one listed world."""
        ...


class FactStore(Protocol):
    """Persists analysis results between runs (the cache that makes re-runs incremental)."""

    def record_world(self, listing: WorldListing, layout: WorldLayout) -> None: ...

    def forget_missing(self, source_id: str, present: set[WorldId]) -> int:
        """Drop worlds of a source that were not seen in its latest scan; return the count."""
        ...

    def is_current(
        self, world_id: WorldId, analyzer: str, version: int, fingerprint: str
    ) -> bool: ...

    def save_facts(
        self,
        world_id: WorldId,
        analyzer: str,
        version: int,
        fingerprint: str,
        *,
        payload: str | None,
        error: str | None,
    ) -> None: ...

    def has_asset(self, world_id: WorldId, name: str, fingerprint: str) -> bool: ...

    def save_asset(self, world_id: WorldId, name: str, fingerprint: str, data: bytes) -> None: ...

    def assets(self, name: str) -> Mapping[WorldId, bytes]: ...

    def worlds(self) -> Sequence[StoredWorld]: ...


class SiteWriter(Protocol):
    def write(self, catalog: Catalog, icons: Mapping[WorldId, bytes]) -> str:
        """Write the static catalog site and return where it was written."""
        ...

    def write_annotations(self, annotations: Mapping[WorldId, Annotation]) -> None:
        """Refresh only the notes in an already written site (cheap, after an edit)."""
        ...


class AnnotationStore(Protocol):
    """Durable notes about worlds; written only on explicit user action."""

    def load(self) -> tuple[dict[WorldId, Annotation], list[str]]:
        """All annotations by world, plus a message for every file that could not be read."""
        ...

    def save(self, annotation: Annotation) -> str:
        """Create or replace the annotation of one world; return where it was stored."""
        ...
