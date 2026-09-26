"""Player UUID -> name from Minecraft launcher/server usercache.json files (read-only)."""

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, TypeAdapter, ValidationError


class _Entry(BaseModel):
    name: str
    uuid: str


_FILE = TypeAdapter(list[_Entry])


def load_names(paths: Iterable[Path]) -> dict[str, str]:
    names: dict[str, str] = {}
    for path in paths:
        try:
            for entry in _FILE.validate_json(path.expanduser().read_bytes()):
                names.setdefault(entry.uuid.lower(), entry.name)
        except OSError, ValidationError:
            continue
    return names
