"""Write protection for world sources.

Two mechanisms, both in-process (mcatlas never mounts or remounts anything):

* `check_output_path` is called by every writing adapter before it writes.
* An audit hook (PEP 578) is a safety net under all code in this process, including third-party
  libraries: any attempt to open a file for writing, create, delete, rename, chmod, touch or
  connect SQLite to a path under a protected root raises `SafetyError`.
"""

import os
import sys
import threading
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Final

_WRITE_FLAGS: Final = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND | os.O_EXCL
_WRITE_MODE_CHARS: Final = frozenset("wax+")
_CASE_INSENSITIVE: Final = sys.platform in {"darwin", "win32"}

# Events whose first argument is a path that would be modified.
_FIRST_ARG_EVENTS: Final = frozenset(
    {
        "os.chflags",
        "os.chmod",
        "os.chown",
        "os.lchflags",
        "os.lchmod",
        "os.lchown",
        "os.mkdir",
        "os.mkfifo",
        "os.mknod",
        "os.remove",
        "os.removexattr",
        "os.rmdir",
        "os.setxattr",
        "os.truncate",
        "os.utime",
        "shutil.rmtree",
        "sqlite3.connect",
    }
)
# Events with (src, dst): a move changes both ends, a copy/link only the destination.
_BOTH_ARGS_EVENTS: Final = frozenset({"os.rename", "shutil.move"})
_SECOND_ARG_EVENTS: Final = frozenset(
    {
        "os.link",
        "os.symlink",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.copytree",
    }
)


class SafetyError(PermissionError):
    """An operation would have modified a protected world source."""


_lock = threading.Lock()
_roots: tuple[str, ...] = ()
_hook_installed = False


def _key(path: str) -> str:
    normalized = os.path.normpath(os.path.abspath(path))
    return normalized.casefold() if _CASE_INSENSITIVE else normalized


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return os.fsdecode(value)
    if isinstance(value, os.PathLike):
        return os.fsdecode(os.fspath(value))  # pyright: ignore[reportUnknownArgumentType]
    return None  # file descriptors and the like


def is_protected(path: object) -> bool:
    text = _as_str(path)
    if text is None or text in {"", ":memory:"}:
        return False
    key = _key(text)
    return any(key == root or key.startswith(root + os.sep) for root in _roots)


def _deny(event: str, path: object) -> None:
    raise SafetyError(f"mcatlas refuses to modify a world source ({event}): {path!r}")


def _audit(event: str, args: tuple[object, ...]) -> None:
    if not _roots:
        return
    if event == "open":
        path, mode, flags = args[0], args[1], args[2]
        writes = (isinstance(mode, str) and not _WRITE_MODE_CHARS.isdisjoint(mode)) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        if writes and is_protected(path):
            _deny(event, path)
    elif event in _FIRST_ARG_EVENTS:
        if args and is_protected(args[0]):
            _deny(event, args[0])
    elif event in _BOTH_ARGS_EVENTS:
        for path in args[:2]:
            if is_protected(path):
                _deny(event, path)
    elif event in _SECOND_ARG_EVENTS and len(args) > 1 and is_protected(args[1]):
        _deny(event, args[1])


def _variants(root: Path) -> set[str]:
    return {_key(str(root.expanduser())), _key(os.path.realpath(root.expanduser()))}


def protect(roots: Iterable[Path]) -> None:
    """Protect these directory trees for the rest of the process lifetime."""
    global _roots, _hook_installed  # noqa: PLW0603 - process-wide registry by design
    with _lock:
        new = set(_roots)
        for root in roots:
            new |= _variants(root)
        _roots = tuple(sorted(new))
        if not _hook_installed:
            sys.addaudithook(_audit)
            _hook_installed = True


@contextmanager
def protected(roots: Iterable[Path]) -> Generator[None]:
    """Temporarily protect roots (tests); the audit hook itself stays installed."""
    global _roots  # noqa: PLW0603
    before = _roots
    protect(roots)
    try:
        yield
    finally:
        with _lock:
            _roots = before


def check_output_path(path: Path) -> Path:
    """Return the real path of an output location, or raise if it lies inside a source."""
    real = Path(os.path.realpath(path.expanduser()))
    if is_protected(real) or is_protected(path.expanduser()):
        raise SafetyError(f"output path lies inside a protected world source: {path}")
    return real
