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
