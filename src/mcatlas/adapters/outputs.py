"""The one way mcatlas writes files: guarded against the sources, atomically replaced."""

import os
from pathlib import Path

from mcatlas.adapters.guard import check_output_path


def atomic_write(path: Path, data: bytes) -> Path:
    """Write via a temporary file and rename, so readers never see half a file."""
    target = check_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target


def remove(path: Path) -> None:
    check_output_path(path).unlink(missing_ok=True)


def write_if_changed(path: Path, data: bytes) -> bool:
    """Write only when the content differs (cheap on network shares); True when written."""
    try:
        if path.stat().st_size == len(data) and path.read_bytes() == data:
            return False
    except OSError:
        pass
    atomic_write(path, data)
    return True
