"""Metadata that lce2java keeps when it converts a Minecraft: Wii U Edition world to Java.

`wiiu_metadata.json` (see the README.md lce2java writes next to it) holds what the converted
Java files lost: when the world was created and last played, on which days its chunks were
saved, how long and how often it was loaded, and the players' gamertags. `wiiu_chunk_times.json`
holds each chunk's last save. Only the fields used here are read; the rest stays in the files.

The console's clock was not always right. Next to each date lce2java writes `<field>_corrected`
and `<field>_clock` (the clock period and how it was decided): a date is used when its period
is known, and kept as two candidates when it is "ambiguous". Metadata from before those
corrections is read as it is.
"""

import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime
from typing import cast

from mcatlas.core.facts import ConsoleFacts, ConsolePlayer

BUNDLED_MAPS = frozenset({"Tutorial", "Super Mario-savegame"})
"""World names of maps that ship with the Wii U game (the tutorial world, the Super Mario
mash-up pack). Their clock and dates already hold the map makers' play when you start them."""

MAX_PROBLEM_CHARS = 300
MAX_PROBLEMS = 3
_LOG_TIME = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] ")
_STACK_LINES = ("Caused by:", "\tat ", "at ", "com.", "java.", "...")

type _Json = dict[str, object]


def lce_player_uuid(gamertag: str) -> str:
    """The UUID lce2java gives the Java player file of a console gamertag.

    A name-based (version 3) UUID of `lce:<gamertag>`, like an offline-mode server's
    `OfflinePlayer:<name>`. Config can map gamertags to names through it.
    """
    digest = hashlib.md5(f"lce:{gamertag}".encode(), usedforsecurity=False).digest()
    return str(uuid.UUID(bytes=digest, version=3))


def _obj(parent: _Json, key: str) -> _Json:
    value = parent.get(key)
    return cast("_Json", value) if isinstance(value, dict) else {}


def _str(parent: _Json, key: str) -> str | None:
    value = parent.get(key)
    return value if isinstance(value, str) else None


def _int(parent: _Json, key: str) -> int | None:
    value = parent.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strings(parent: _Json, key: str) -> list[str]:
    value = parent.get(key)
    items = cast("list[object]", value) if isinstance(value, list) else []
    return [v for v in items if isinstance(v, str)]


def _problems(errors: list[str]) -> list[str]:
    """Conversion errors without log times, stack traces and repeats; at most a few."""
    lines = dict.fromkeys(
        _LOG_TIME.sub("", e).strip()[:MAX_PROBLEM_CHARS]
        for e in errors
        if not e.lstrip().startswith(_STACK_LINES)
    )
    kept = [line for line in lines if line]
    if len(kept) <= MAX_PROBLEMS:
        return kept
    return [*kept[:MAX_PROBLEMS], f"... and {len(kept) - MAX_PROBLEMS} more"]


def _moment(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _day(text: str | None) -> date | None:
    moment = _moment(text)
    return moment.date() if moment else None


DATED_PERIODS = frozenset({"A", "B1", "B2"})
"""Clock periods whose correction is known: right (A), or behind by a known offset (B1, B2)."""
_DIMENSIONS = {0: "minecraft:overworld", -1: "minecraft:the_nether", 1: "minecraft:the_end"}

type _Dated = tuple[datetime | None, list[datetime], float | None]


def _number(parent: _Json, key: str) -> float | None:
    value = parent.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _dated(parent: _Json, key: str) -> _Dated:
    """(date, candidates, clock offset in days) of `parent[key]`, corrected when possible."""
    clock = _obj(parent, f"{key}_clock")
    if not clock:  # written before lce2java corrected dates
        return _moment(_str(parent, key)), [], None
    period = _str(clock, "period")
    if period in DATED_PERIODS:
        return _moment(_str(parent, f"{key}_corrected")), [], _number(clock, "offset_days")
    if period == "ambiguous":
        values = _obj(clock, "candidates").values()
        found = (_moment(v) for v in values if isinstance(v, str))
        return None, sorted(m for m in found if m is not None), None
    return None, [], None


def _players(world: _Json) -> list[ConsolePlayer]:
    value = world.get("players")
    items = cast("list[object]", value) if isinstance(value, list) else []
    players: list[ConsolePlayer] = []
    for item in items:
        if isinstance(item, dict):
            p = cast("_Json", item)
            name = _str(p, "name")
            if name:
                players.append(
                    ConsolePlayer(
                        name=name,
                        uuid=lce_player_uuid(name),
                        host=p.get("host") is True,
                        last_saved=_dated(p, "last_saved_utc")[0],
                    )
                )
    return players


def _last_played(source: _Json, world: _Json, created: date | None) -> _Dated:
    """The console's own file time; the decoded `last_played_utc` only when it is plausible.

    lce2java decodes LastPlayed with one epoch, but later game versions count from another:
    for those worlds it lands years before the world was even created.
    """
    save_file = _obj(_obj(source, "wfs_file_times_utc"), "save_file")
    if _str(save_file, "mtime") is not None:
        return _dated(save_file, "mtime")
    moment, candidates, offset = _dated(world, "last_played_utc")
    if moment is not None and (created is None or moment.date() >= created):
        return moment, [], offset
    return None, candidates, None


def _play_days(world: _Json) -> tuple[dict[date, int], int]:
    """Days chunks were last saved (with how many), and how many more days are undated."""
    value = _obj(world, "play_evidence").get("per_day")
    items = cast("list[object]", value) if isinstance(value, list) else []
    days: dict[date, int] = {}
    undated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = cast("_Json", item)
        day = _day(_str(entry, "date"))
        periods = set(_strings(entry, "clock_periods"))
        if day is None or not periods <= DATED_PERIODS:
            undated += 1
            continue
        dims = _obj(entry, "dimensions")
        chunks = sum(_int(_obj(dims, key), "chunks_last_saved") or 0 for key in dims)
        days[day] = days.get(day, 0) + chunks
    return days, undated


def parse_chunk_times(data: bytes) -> dict[str, list[tuple[int, int, int]]]:
    """`wiiu_chunk_times.json`: each chunk's last save per dimension (0 when undated)."""
    raw = cast("object", json.loads(data))
    root = cast("_Json", raw) if isinstance(raw, dict) else {}
    columns = _strings(root, "columns")
    corrected = "last_saved_corrected_unix" in columns
    saved = "last_saved_corrected_unix" if corrected else "last_saved_unix"
    needed = ["dimension", "chunk_x", "chunk_z", saved]
    if not set(needed) <= set(columns):
        return {}
    at = [columns.index(name) for name in needed]
    period = columns.index("clock_period") if "clock_period" in columns else None
    value = root.get("rows")
    rows = cast("list[object]", value) if isinstance(value, list) else []
    times: dict[str, list[tuple[int, int, int]]] = {}
    for row in rows:
        cells = cast("list[object]", row) if isinstance(row, list) else []
        if len(cells) != len(columns):
            continue
        dim, x, z, when = (cells[i] for i in at)
        if not all(isinstance(v, int) for v in (dim, x, z, when)):
            continue
        key = _DIMENSIONS.get(cast("int", dim))
        if key is None:
            continue
        dated = period is None or cells[period] in DATED_PERIODS
        times.setdefault(key, []).append(
            (cast("int", x), cast("int", z), cast("int", when) if dated else 0)
        )
    return times


def parse_console(
    data: bytes, metadata_file: str, chunk_times: bytes | None = None
) -> ConsoleFacts:
    raw = cast("object", json.loads(data))
    root = cast("_Json", raw) if isinstance(raw, dict) else {}
    source, world, conversion = _obj(root, "source"), _obj(root, "world"), _obj(root, "conversion")
    name = _str(world, "name")
    created, created_candidates, _ = _dated(source, "date_in_save_name")
    created_day = created.date() if created else None
    last_saved, last_candidates, offset = _last_played(source, world, created_day)
    play_days, undated = _play_days(world)
    return ConsoleFacts(
        metadata_file=metadata_file,
        console=_str(source, "console"),
        original_name=name,
        created=created_day,
        created_candidates=[c.date() for c in created_candidates],
        last_saved=last_saved,
        last_saved_candidates=[c.date() for c in last_candidates],
        clock_offset_days=offset,
        play_days=play_days,
        undated_play_days=undated,
        play_ticks=_int(world, "time_played_ticks"),
        times_loaded=_int(world, "times_loaded"),
        bundled_map=name in BUNDLED_MAPS,
        players=_players(world),
        chunk_times=parse_chunk_times(chunk_times) if chunk_times else {},
        tool=_str(conversion, "tool"),
        converted_at=_moment(_str(conversion, "converted_at_utc")),
        finalized=bool(_obj(conversion, "finalized")),
        notes=_strings(conversion, "notes"),
        problems=_problems(_strings(conversion, "errors")),
    )
