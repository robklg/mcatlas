"""advancements/<uuid>.json: criteria keep the timestamp at which they were first met.

These survive later saves, so they preserve play dates that region-file timestamps overwrite.
"""

from datetime import datetime

from pydantic import BaseModel, TypeAdapter

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S %z"


class _Advancement(BaseModel):
    criteria: dict[str, str] = {}
    done: bool = False


_FILE = TypeAdapter(dict[str, _Advancement | int])


def parse_advancements(data: bytes) -> tuple[int, list[datetime]]:
    """Return (number of completed advancements, sorted unique criterion timestamps)."""
    done = 0
    times: set[datetime] = set()
    for value in _FILE.validate_json(data).values():
        if isinstance(value, int):  # the "DataVersion" entry
            continue
        done += value.done
        for stamp in value.criteria.values():
            try:
                times.add(datetime.strptime(stamp, _TIME_FORMAT))
            except ValueError:
                continue
    return done, sorted(times)
