"""World source backed by a directory tree (e.g. the NAS share, mounted by the user).

Read-only by construction: files are only ever opened with O_RDONLY (see `readonly.py`), and
this module has no code path that creates, modifies or deletes anything.
"""

import fnmatch
import os
from collections.abc import Generator, Iterator, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from mcatlas.adapters import readonly
from mcatlas.adapters.source_zip import ZipArchive, split_zip_relpath
from mcatlas.core.discovery import is_world_root
from mcatlas.core.model import SourceFile, WorldFiles, WorldListing

_IGNORED_NAMES: Final = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", ".localized"})
_MAX_NESTING: Final = 4
"""How deep to look for worlds inside a top-level folder that is not a world itself."""


def _ignored(name: str) -> bool:
    return name in _IGNORED_NAMES or name.startswith("._")


class FolderWorld:
    """Read-only view of one world directory."""

    def __init__(self, base: str, listing: WorldListing, pool: Executor | None = None) -> None:
        self._base = base
        self._listing = listing
        self._pool = pool

    @property
    def listing(self) -> WorldListing:
        return self._listing

    def read_bytes(self, relpath: str) -> bytes:
        return readonly.read_all(readonly.safe_join(self._base, relpath))

    def read_range(self, relpath: str, offset: int, length: int) -> bytes:
        return readonly.read_range(readonly.safe_join(self._base, relpath), offset, length)

    def read_ranges(self, requests: Sequence[tuple[str, int, int]]) -> list[bytes | OSError]:
        resolved = [(readonly.safe_join(self._base, rel), off, n) for rel, off, n in requests]
        return readonly.read_ranges(resolved, self._pool)


class FolderSource:
    def __init__(
        self,
        source_id: str,
        root: Path,
        *,
        archives: Sequence[str] = ("*.zip",),
        exclude: Sequence[str] = (),
        jobs: int = 8,
        io_threads: int = 32,
    ) -> None:
        self._id = source_id
        self._root = str(root.expanduser().absolute())
        self._archives = tuple(archives)
        self._exclude = tuple(exclude)
        self._jobs = max(1, jobs)
        # Shared by all worlds: many small concurrent requests hide network-share latency.
        # Tasks in this pool never submit to it, so nesting from the scan/analyze pools is safe.
        self._io = ThreadPoolExecutor(max(1, io_threads), thread_name_prefix="io")

    def close(self) -> None:
        self._io.shutdown(wait=True)

    @property
    def source_id(self) -> str:
        return self._id

    @property
    def root(self) -> Path:
        return Path(self._root)

    def _excluded(self, name: str) -> bool:
        return _ignored(name) or any(fnmatch.fnmatch(name, pat) for pat in self._exclude)

    def _entries(self, rel_dir: str) -> tuple[list[str], list[str]]:
        """(file names, directory names) of one directory; symlinks are skipped."""
        files: list[str] = []
        dirs: list[str] = []
        with os.scandir(os.path.join(self._root, rel_dir) if rel_dir else self._root) as it:
            for entry in it:
                if entry.is_symlink() or self._excluded(entry.name):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(entry.name)
                elif entry.is_file(follow_symlinks=False):
                    files.append(entry.name)
        return sorted(files), sorted(dirs)

    def _walk_files(self, rel_dir: str) -> list[SourceFile]:
        """Every regular file below `rel_dir`, with paths relative to it."""
        base = os.path.join(self._root, rel_dir)
        names = sorted(
            rel
            for rel, kind in readonly.list_tree(base, self._io)
            if kind == "file" and not any(_ignored(part) for part in rel.split("/"))
        )
        stats = readonly.stat_many([os.path.join(base, n) for n in names], self._io)
        return [
            SourceFile(n, st.st_size, st.st_mtime_ns) for n, st in zip(names, stats, strict=True)
        ]

    def _find_roots(self, rel_dir: str, depth: int) -> list[str]:
        files, dirs = self._entries(rel_dir)
        if is_world_root(files, dirs):
            return [rel_dir]
        if depth >= _MAX_NESTING:
            return []
        roots: list[str] = []
        for d in dirs:
            roots += self._find_roots(f"{rel_dir}/{d}", depth + 1)
        return roots

    def _scan_top(self, name: str) -> list[WorldListing]:
        roots = self._find_roots(name, 0) or [name]  # no world inside: still list the folder
        return [WorldListing(self._id, r, tuple(self._walk_files(r))) for r in roots]

    def scan(self) -> Iterator[WorldListing]:
        files, dirs = self._entries("")
        with ThreadPoolExecutor(self._jobs, thread_name_prefix="scan") as pool:
            for listings in pool.map(self._scan_top, dirs):
                yield from listings
        for name in files:
            if any(fnmatch.fnmatch(name, pat) for pat in self._archives):
                yield from ZipArchive(self._id, Path(self._root), name).scan()

    @contextmanager
    def open(self, listing: WorldListing) -> Generator[WorldFiles]:
        if listing.source_id != self._id:
            raise ValueError(f"listing belongs to source {listing.source_id!r}, not {self._id!r}")
        zip_part = split_zip_relpath(listing.relpath)
        if zip_part is not None:
            with ZipArchive(self._id, Path(self._root), zip_part[0]).open(listing) as files:
                yield files
            return
        yield FolderWorld(readonly.safe_join(self._root, listing.relpath), listing, self._io)
