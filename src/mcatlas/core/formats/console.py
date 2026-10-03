"""Metadata that lce2java keeps when it converts a Minecraft: Wii U Edition world to Java.

`wiiu_metadata.json` (see the README.md lce2java writes next to it) holds what the converted
Java files lost: when the world was created and last played, how long and how often it was
loaded, and the players' gamertags. Only the fields used here are read; the rest stays in the
file.
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
                    ConsolePlayer(name=name, uuid=lce_player_uuid(name), host=p.get("host") is True)
                )
    return players


def _last_played(source: _Json, world: _Json, created: date | None) -> datetime | None:
    """The console's own file time; the decoded `last_played_utc` only when it is plausible.

    lce2java decodes LastPlayed with one epoch, but later game versions count from another:
    for those worlds it lands years before the world was even created.
    """
    file_time = _moment(_str(_obj(_obj(source, "wfs_file_times_utc"), "save_file"), "mtime"))
    if file_time is not None:
        return file_time
    reported = _moment(_str(world, "last_played_utc"))
    if reported is not None and (created is None or reported.date() >= created):
        return reported
    return None


def parse_console(data: bytes, metadata_file: str) -> ConsoleFacts:
    raw = cast("object", json.loads(data))
    root = cast("_Json", raw) if isinstance(raw, dict) else {}
    source, world, conversion = _obj(root, "source"), _obj(root, "world"), _obj(root, "conversion")
    name = _str(world, "name")
    created = _day(_str(source, "date_in_save_name"))
    return ConsoleFacts(
        metadata_file=metadata_file,
        console=_str(source, "console"),
        original_name=name,
        save_name_date=created,
        last_saved=_last_played(source, world, created),
        play_ticks=_int(world, "time_played_ticks"),
        times_loaded=_int(world, "times_loaded"),
        bundled_map=name in BUNDLED_MAPS,
        players=_players(world),
        tool=_str(conversion, "tool"),
        converted_at=_moment(_str(conversion, "converted_at_utc")),
        notes=_strings(conversion, "notes"),
        problems=_problems(_strings(conversion, "errors")),
    )
