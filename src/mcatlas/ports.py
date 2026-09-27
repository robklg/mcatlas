"""Ports: the interfaces between the application and the outside world.

Driven adapters in `mcatlas.adapters` implement these; `mcatlas.app` depends only on them.
The world-source port is deliberately read-only: it has no method that could change a world.
"""

from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from mcatlas.core.annotations import Annotation
from mcatlas.core.catalog import Catalog, StoredWorld
from mcatlas.core.model import WorldFiles, WorldId, WorldLayout, WorldListing
from mcatlas.core.render import MapPlan, RenderedMap


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
    def write(
        self,
        catalog: Catalog,
        icons: Mapping[WorldId, bytes],
        images: Mapping[str, bytes] | None = None,
    ) -> str:
        """Write the static catalog site and return where it was written.

        `images` are extra files by relative path (flat maps of 3D renders)."""
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


class Renderer(Protocol):
    """Renders 3D maps from copies of worlds in its own workspace, never from the sources.

    The application copies ("stages") the files a map needs through the read-only world source;
    the renderer only ever sees those copies.
    """

    def staged(self, world_id: WorldId) -> Mapping[str, tuple[int, int]]:
        """Copies present for a world: relpath -> (size, mtime_ns of the original)."""
        ...

    def stage(self, world_id: WorldId, relpath: str, data: bytes, mtime_ns: int) -> None: ...

    def unstage(self, world_id: WorldId, keep: Collection[str]) -> int:
        """Remove a world's copies that are not in `keep`; return how many were removed."""
        ...

    def rendered(self) -> list[RenderedMap]:
        """Maps rendered earlier (with the plan they were rendered from)."""
        ...

    def render(
        self,
        plans: Sequence[MapPlan],
        todo: Collection[str],
        *,
        force: bool,
        progress: Callable[[str], None],
    ) -> list[RenderedMap]:
        """Configure all `plans` (so the viewer lists them) and render the maps in `todo`."""
        ...

    def image(self, path: str) -> bytes:
        """A flat map image by the relative path given in `RenderedMap.images`."""
        ...
