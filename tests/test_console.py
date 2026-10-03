"""Worlds converted from a Wii U save by lce2java: metadata, dates and players."""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from mcatlas.core.activity import collect_days
from mcatlas.core.facts import ConsoleFacts, DimensionFacts, RegionFacts
from mcatlas.core.formats.console import lce_player_uuid, parse_console

CONVERTED = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)


def _metadata(**world: object) -> bytes:
    return json.dumps(
        {
            "source": {
                "console": "Nintendo Wii U",
                "date_in_save_name": "2017-01-14T12:00:00",
                "wfs_file_times_utc": {"save_file": {"mtime": "2017-03-02T15:00:00Z"}},
            },
            "world": {
                "name": "Noors kasteel",
                "last_played_utc": "2010-01-01T00:00:00Z",
                "time_played_ticks": 360_000,
                "times_loaded": 4,
                "players": [{"name": "NoorBouwt", "host": True}, {"name": "SamWii"}],
            }
            | world,
            "conversion": {
                "tool": "lce2java 0.1.0",
                "converted_at_utc": CONVERTED.isoformat(),
                "notes": ["A world border of 864x864 blocks is set."],
                "errors": ["x" * 1000],
            },
        }
    ).encode()


def test_player_uuid_is_name_based():
    digest = hashlib.md5(b"lce:NoorBouwt").digest()
    expected = uuid.UUID(bytes=digest, version=3)
    assert lce_player_uuid("NoorBouwt") == str(expected)
    assert uuid.UUID(lce_player_uuid("NoorBouwt")).version == 3


def test_metadata():
    facts = parse_console(_metadata(), "wiiu_metadata.json")
    assert (facts.console, facts.original_name, facts.bundled_map) == (
        "Nintendo Wii U",
        "Noors kasteel",
        False,
    )
    assert facts.save_name_date == date(2017, 1, 14)
    # The console's own file time wins over a LastPlayed decoded with the wrong epoch.
    assert facts.last_saved == datetime(2017, 3, 2, 15, 0, tzinfo=UTC)
    assert (facts.play_ticks, facts.times_loaded) == (360_000, 4)
    assert [(p.name, p.host) for p in facts.players] == [("NoorBouwt", True), ("SamWii", False)]
    assert facts.players[0].uuid == lce_player_uuid("NoorBouwt")
    assert facts.converted_at == CONVERTED and len(facts.problems[0]) == 300


def test_last_played_without_file_time():
    def last_saved(reported: str) -> datetime | None:
        raw = json.loads(_metadata(last_played_utc=reported))
        del raw["source"]["wfs_file_times_utc"]
        return parse_console(json.dumps(raw).encode(), "m").last_saved

    assert last_saved("2010-01-01T00:00:00Z") is None  # before the world was created
    assert last_saved("2017-02-01T08:00:00Z") == datetime(2017, 2, 1, 8, 0, tzinfo=UTC)


def test_conversion_errors_are_condensed():
    log = [
        "[19:34:26] [World Upgrader #0/ERROR]: Failed to unflatten text component json: abc",
        "com.google.gson.JsonSyntaxException: malformed",
        "Caused by: com.google.gson.stream.MalformedJsonException: malformed",
        "[19:35:15] [World Upgrader #0/ERROR]: Failed to unflatten text component json: abc",
    ]
    raw = json.loads(_metadata())
    raw["conversion"]["errors"] = log
    problems = parse_console(json.dumps(raw).encode(), "m").problems
    assert problems == ["[World Upgrader #0/ERROR]: Failed to unflatten text component json: abc"]
    raw["conversion"]["errors"] = [f"problem {n}" for n in range(5)]
    problems = parse_console(json.dumps(raw).encode(), "m").problems
    assert problems == ["problem 0", "problem 1", "problem 2", "... and 2 more"]


def test_bundled_maps_and_unexpected_json():
    assert parse_console(_metadata(name="Tutorial"), "m").bundled_map
    assert parse_console(b"[1, 2]", "m") == ConsoleFacts(metadata_file="m")


def test_activity_uses_console_dates_not_the_conversion():
    console = parse_console(_metadata(), "wiiu_metadata.json")
    hour = int(CONVERTED.timestamp()) // 3600
    regions = RegionFacts(
        dimensions=[
            DimensionFacts(
                key="minecraft:overworld",
                region_files=1,
                empty_region_files=0,
                chunks=500,
                chunk_saves_by_hour={hour: 500},
            )
        ]
    )
    days = collect_days(
        regions=regions, files=None, players=None, level=None, tz=UTC, console=console
    )
    assert sorted(days) == [date(2017, 1, 14), date(2017, 3, 2)]
    assert all(d.console_saves == 1 and not d.chunk_saves for d in days.values())
    # Without console metadata the conversion day is all there is.
    plain = collect_days(regions=regions, files=None, players=None, level=None, tz=UTC)
    assert list(plain) == [CONVERTED.date()] and CONVERTED.date() - timedelta(days=1) not in plain
