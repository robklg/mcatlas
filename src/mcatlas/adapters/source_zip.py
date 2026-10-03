"""Worlds inside zip archives, read in place: nothing is extracted to disk."""

import os
import time
import zipfile
from collections import defaultdict
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path

from mcatlas.adapters import readonly
from mcatlas.core.discovery import is_world_root, merge_all_sibling_roots
from mcatlas.core.model import SourceFile, WorldFiles, WorldListing

ZIP_SEPARATOR = "!/"


def split_zip_relpath(relpath: str) -> tuple[str, str] | None:
    """`a.zip!/World` -> ("a.zip", "World"); None for a plain folder path."""
    if ZIP_SEPARATOR not in relpath:
        return None
    archive, _, inner = relpath.partition(ZIP_SEPARATOR)
    return archive, inner


def _mtime_ns(info: zipfile.ZipInfo) -> int:
    # Zip timestamps are naive local time.
    return int(time.mktime((*info.date_time, 0, 0, -1)) * 1_000_000_000)


class ZipWorld:
    def __init__(self, archive: zipfile.ZipFile, prefix: str, listing: WorldListing) -> None:
        self._zip = archive
        self._prefix = prefix
        self._listing = listing

    @property
    def listing(self) -> WorldListing:
        return self._listing

    def read_bytes(self, relpath: str) -> bytes:
        readonly.safe_join("", relpath)  # same path validation as for folders
        return self._zip.read(self._prefix + relpath)

    def read_range(self, relpath: str, offset: int, length: int) -> bytes:
        return self.read_bytes(relpath)[offset : offset + length]

    def read_ranges(self, requests: Sequence[tuple[str, int, int]]) -> list[bytes | OSError]:
        results: list[bytes | OSError] = []
        for relpath, offset, length in requests:
            try:
                results.append(self.read_range(relpath, offset, length))
            except (OSError, KeyError) as e:
                results.append(e if isinstance(e, OSError) else FileNotFoundError(str(e)))
        return results


class ZipArchive:
    def __init__(self, source_id: str, root: Path, relpath: str) -> None:
        self._source_id = source_id
        self._path = readonly.safe_join(str(root), relpath)
        self._relpath = relpath

    @contextmanager
    def _zip(self) -> Generator[zipfile.ZipFile]:
        fd = os.open(self._path, readonly.READ_FLAGS)
        with os.fdopen(fd, "rb") as handle, zipfile.ZipFile(handle, "r") as archive:
            yield archive

    def scan(self) -> list[WorldListing]:
        with self._zip() as archive:
            infos = [i for i in archive.infolist() if not i.is_dir()]
        files_in: dict[str, list[str]] = defaultdict(list)
        dirs_in: dict[str, set[str]] = defaultdict(set)
        for info in infos:
            parts = info.filename.rstrip("/").split("/")
            for depth in range(len(parts) - 1):
                dirs_in["/".join(parts[:depth])].add(parts[depth])
            files_in["/".join(parts[:-1])].append(parts[-1])

        candidates = sorted(set(files_in) | set(dirs_in), key=lambda d: (d.count("/"), d))
        roots: list[str] = []
        for d in candidates:
            nested = any(d == r or d.startswith(f"{r}/") or r == "" for r in roots)
            if not nested and is_world_root(files_in.get(d, []), dirs_in.get(d, set())):
                roots.append(d)

        roots = merge_all_sibling_roots(roots) or [""]
        listings: list[WorldListing] = []
        for root in roots:
            prefix = f"{root}/" if root else ""
            files = tuple(
                SourceFile(i.filename.removeprefix(prefix), i.file_size, _mtime_ns(i))
                for i in sorted(infos, key=lambda i: i.filename)
                if i.filename.startswith(prefix)
            )
            listings.append(
                WorldListing(self._source_id, self._relpath + ZIP_SEPARATOR + root, files)
            )
        return listings

    @contextmanager
    def open(self, listing: WorldListing) -> Generator[WorldFiles]:
        parts = split_zip_relpath(listing.relpath)
        if parts is None or parts[0] != self._relpath:
            raise ValueError(f"{listing.relpath!r} is not inside {self._relpath!r}")
        inner = parts[1]
        with self._zip() as archive:
            yield ZipWorld(archive, f"{inner}/" if inner else "", listing)
