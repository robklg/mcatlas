"""Source manifests: proof that the archive did not change.

`snapshot` records (path, size, mtime) of every entry below a source root, optionally with an
xxh3-128 content hash. `verify` re-reads the tree and reports anything added, removed or changed.
Unlike the world scanner, the manifest includes *everything*: hidden files, Finder litter,
symlinks. A new `.DS_Store` appearing is exactly the kind of change it must reveal.
"""

import gzip
import json
import os
from collections.abc import Callable, Iterator
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import xxhash
from pydantic import BaseModel

from mcatlas.adapters import readonly
from mcatlas.adapters.guard import check_output_path

_HASH_BLOCK: Final = 4 << 20


class ManifestHeader(BaseModel):
    source_id: str
    root: str
    created_at: datetime
    hashed: bool


class ManifestEntry(BaseModel):
    path: str
    kind: str  # "file" | "dir" | "symlink" | "other"
    size: int
    mtime_ns: int
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class Manifest:
    header: ManifestHeader
    entries: dict[str, ManifestEntry]


@dataclass(slots=True)
class ManifestDiff:
    added: list[str] = field(default_factory=list[str])
    removed: list[str] = field(default_factory=list[str])
    changed: list[str] = field(default_factory=list[str])

    @property
    def clean(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _walk(root: str, pool: Executor) -> Iterator[ManifestEntry]:
    found = readonly.list_tree(root, pool)
    stats = readonly.stat_many([os.path.join(root, rel) for rel, _ in found], pool)
    for (rel, kind), st in zip(found, stats, strict=True):
        # Directory sizes and mtimes on SMB are not meaningful content; record 0.
        size = st.st_size if kind == "file" else 0
        mtime = st.st_mtime_ns if kind != "dir" else 0
        yield ManifestEntry(path=rel, kind=kind, size=size, mtime_ns=mtime)


def _digest(path: str) -> str:
    h = xxhash.xxh3_128()
    fd = os.open(path, readonly.READ_FLAGS)
    try:
        while block := os.read(fd, _HASH_BLOCK):
            h.update(block)
    finally:
        os.close(fd)
    return h.hexdigest()


def take(
    source_id: str,
    root: Path,
    *,
    hashed: bool,
    jobs: int = 8,
    io_threads: int = 32,
    progress: Callable[[int, int], None] | None = None,
) -> Manifest:
    base = str(root.expanduser().absolute())
    with ThreadPoolExecutor(max(1, io_threads), thread_name_prefix="stat") as stat_pool:
        entries = {e.path: e for e in _walk(base, stat_pool)}
    if hashed:
        files = [e for e in entries.values() if e.kind == "file"]

        def work(e: ManifestEntry) -> ManifestEntry:
            return e.model_copy(update={"digest": _digest(readonly.safe_join(base, e.path))})

        with ThreadPoolExecutor(max(1, jobs), thread_name_prefix="hash") as pool:
            for n, done in enumerate(pool.map(work, files), start=1):
                entries[done.path] = done
                if progress:
                    progress(n, len(files))
    header = ManifestHeader(
        source_id=source_id, root=base, created_at=datetime.now(UTC), hashed=hashed
    )
    return Manifest(header, dict(sorted(entries.items())))


def compare(old: Manifest, new: Manifest) -> ManifestDiff:
    diff = ManifestDiff()
    diff.added = sorted(set(new.entries) - set(old.entries))
    diff.removed = sorted(set(old.entries) - set(new.entries))
    for path in sorted(set(old.entries) & set(new.entries)):
        a, b = old.entries[path], new.entries[path]
        same_meta = (a.kind, a.size, a.mtime_ns) == (b.kind, b.size, b.mtime_ns)
        same_digest = a.digest is None or b.digest is None or a.digest == b.digest
        if not (same_meta and same_digest):
            diff.changed.append(path)
    return diff


def save(manifest: Manifest, directory: Path) -> Path:
    target_dir = check_output_path(directory) / manifest.header.source_id
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = manifest.header.created_at.strftime("%Y%m%dT%H%M%SZ")
    path = target_dir / f"{stamp}.jsonl.gz"
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as out:
        out.write(manifest.header.model_dump_json() + "\n")
        for entry in manifest.entries.values():
            out.write(entry.model_dump_json(exclude_none=True) + "\n")
    tmp.replace(path)
    return path


def load(path: Path) -> Manifest:
    with gzip.open(path, "rt", encoding="utf-8") as src:
        header = ManifestHeader.model_validate_json(src.readline())
        entries = {
            e.path: e
            for e in (ManifestEntry.model_validate_json(line) for line in src if line.strip())
        }
    return Manifest(header, entries)


def latest(directory: Path, source_id: str) -> Path | None:
    candidates = sorted((directory / source_id).glob("*.jsonl.gz"))
    return candidates[-1] if candidates else None


def summary(manifest: Manifest) -> dict[str, int]:
    files = [e for e in manifest.entries.values() if e.kind == "file"]
    return {
        "entries": len(manifest.entries),
        "files": len(files),
        "bytes": sum(e.size for e in files),
        "hashed": sum(1 for e in files if e.digest),
    }


def to_json(diff: ManifestDiff) -> str:
    return json.dumps({"added": diff.added, "removed": diff.removed, "changed": diff.changed})
