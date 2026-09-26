"""Low-level read-only file access: the only way mcatlas opens files inside a world source."""

import os
from collections.abc import Sequence
from concurrent.futures import Executor
from typing import Final

READ_FLAGS: Final = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
_CHUNK: Final = 1 << 20


def safe_join(base: str, relpath: str) -> str:
    """Join a listing-relative POSIX path onto `base`, refusing anything that could escape it."""
    parts = relpath.split("/")
    if relpath.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"unsafe relative path: {relpath!r}")
    return os.path.join(base, *parts)


def read_all(path: str) -> bytes:
    fd = os.open(path, READ_FLAGS)
    try:
        chunks: list[bytes] = []
        while block := os.read(fd, _CHUNK):
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _kind(entry: os.DirEntry[str]) -> str:
    if entry.is_symlink():
        return "symlink"
    if entry.is_dir(follow_symlinks=False):
        return "dir"
    if entry.is_file(follow_symlinks=False):
        return "file"
    return "other"


def list_tree(base: str, pool: Executor | None) -> list[tuple[str, str]]:
    """(relpath, kind) of every entry below `base`, never following symlinks.

    Walks breadth-first and lists all directories of one level concurrently: over a network
    share each directory listing is a round trip, so this hides latency.
    """

    def one(sub: str) -> list[tuple[str, str]]:
        with os.scandir(os.path.join(base, sub) if sub else base) as it:
            return [(f"{sub}/{e.name}" if sub else e.name, _kind(e)) for e in it]

    found: list[tuple[str, str]] = []
    level = [""]
    while level:
        listed = list(pool.map(one, level)) if pool else [one(d) for d in level]
        level: list[str] = []
        for entries in listed:
            found += entries
            level += [rel for rel, kind in entries if kind == "dir"]
    return found


def stat_many(paths: Sequence[str], pool: Executor | None) -> list[os.stat_result]:
    """lstat many paths; concurrently when a pool is given (SMB latency hides behind it)."""

    def one(path: str) -> os.stat_result:
        return os.stat(path, follow_symlinks=False)

    return list(pool.map(one, paths)) if pool else [one(p) for p in paths]


def read_ranges(
    requests: Sequence[tuple[str, int, int]], pool: Executor | None
) -> list[bytes | OSError]:
    def one(request: tuple[str, int, int]) -> bytes | OSError:
        try:
            return read_range(*request)
        except OSError as e:
            return e

    return list(pool.map(one, requests)) if pool else [one(r) for r in requests]


def read_range(path: str, offset: int, length: int) -> bytes:
    fd = os.open(path, READ_FLAGS)
    try:
        buf = bytearray()
        while len(buf) < length:
            block = os.pread(fd, length - len(buf), offset + len(buf))
            if not block:
                break
            buf += block
        return bytes(buf)
    finally:
        os.close(fd)
