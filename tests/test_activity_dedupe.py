from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import numpy as np

from mcatlas.core.activity import build_activity
from mcatlas.core.dedupe import chunk_keys, minhash, similarity
from mcatlas.core.facts import (
    DimensionFacts,
    FileFacts,
    LevelFacts,
    PlayerFacts,
    PlayersFacts,
    RegionFacts,
)
from mcatlas.core.scoring import importance

AMS = ZoneInfo("Europe/Amsterdam")


def hour(y, m, d, h) -> int:
    return int(datetime(y, m, d, h, tzinfo=UTC).timestamp()) // 3600


def test_days_use_local_timezone():
    # 23:30 UTC on 1 July is already 2 July in Amsterdam (CEST, UTC+2).
    regions = RegionFacts(
        dimensions=[
            DimensionFacts(
                key="minecraft:overworld",
                region_files=1,
                empty_region_files=0,
                chunks=3,
                chunk_saves_by_hour={hour(2023, 7, 1, 23): 3},
            )
        ]
    )
    profile = build_activity(regions=regions, files=None, players=None, level=None, tz=AMS)
    assert list(profile.days) == [date(2023, 7, 2)]
    utc = build_activity(regions=regions, files=None, players=None, level=None, tz=UTC)
    assert list(utc.days) == [date(2023, 7, 1)]


def test_union_of_signals():
    regions = RegionFacts(
        dimensions=[
            DimensionFacts(
                key="minecraft:overworld",
                region_files=1,
                empty_region_files=0,
                chunks=10,
                chunk_saves_by_hour={hour(2023, 11, 23, 12): 10},
            )
        ]
    )
    files = FileFacts(
        files=5,
        total_size=1,
        game_file_saves_by_hour={hour(2023, 11, 23, 12): 2, hour(2023, 3, 26, 12): 1},
    )
    players = PlayersFacts(
        players=[PlayerFacts(uuid="u", advancement_times=[datetime(2023, 2, 12, 15, tzinfo=AMS)])]
    )
    level = LevelFacts(level_file="level.dat", last_played=datetime(2023, 11, 23, 18, tzinfo=UTC))
    p = build_activity(regions=regions, files=files, players=players, level=level, tz=AMS)
    assert p.distinct_days == 3
    assert p.first_day == date(2023, 2, 12) and p.last_day == date(2023, 11, 23)
    assert p.span_days == (date(2023, 11, 23) - date(2023, 2, 12)).days + 1
    assert p.active_months == 3
    last = p.days[date(2023, 11, 23)]
    assert last.chunk_saves == 10 and last.file_saves == 2 and last.last_played
    assert p.days[date(2023, 2, 12)].advancements == 1


def test_empty_activity():
    p = build_activity(regions=None, files=None, players=None, level=None, tz=AMS)
    assert p.distinct_days == 0 and p.first_day is None


def test_importance_is_monotonic_and_explained():
    small = importance(distinct_days=1, span_days=1, play_hours=0.5, items_used=10, chunks=100)
    big = importance(
        distinct_days=40,
        span_days=200,
        play_hours=60,
        items_used=50_000,
        chunks=20_000,
        built=80_000,
    )
    assert big.score > small.score
    assert set(big.components) == {"days", "weeks", "play_hours", "items_used", "chunks", "built"}
    assert abs(sum(big.components.values()) - big.score) < 0.05


def _keys(xs, ts):
    xs = np.array(xs, dtype=np.int64)
    return chunk_keys(1, xs, np.zeros_like(xs), np.array(ts, dtype=np.int64))


def test_minhash_similarity():
    base = _keys(range(2000), [1000] * 2000)
    copy = _keys(range(2000), [1000] * 2000)
    continued = _keys(range(2000), [1000] * 1000 + [2000] * 1000)  # half re-saved later
    other = _keys(range(2000, 4000), [1000] * 2000)
    sig = minhash(base)
    assert similarity(sig, minhash(copy)) == 1.0
    assert 0.15 < similarity(sig, minhash(continued)) < 0.6
    assert similarity(sig, minhash(other)) < 0.1
    assert minhash(np.array([], dtype=np.uint64)) == []
    assert similarity([], sig) == 0.0


def test_archive_copy_days_are_detected_and_ignored():
    from mcatlas.core.activity import DaySignals, archive_artifact_days, build_profile

    copy_day, play_day = date(2025, 10, 10), date(2023, 5, 1)
    worlds = [
        {play_day: DaySignals(chunk_saves=5), copy_day: DaySignals(file_saves=3)} for _ in range(8)
    ]
    worlds.append({date(2023, 6, 1): DaySignals(file_saves=1)})  # a lone file-only day is kept
    ignored = archive_artifact_days(worlds)
    assert ignored == frozenset({copy_day})
    profile = build_profile(worlds[0], ignore_file_days=ignored)
    assert list(profile.days) == [play_day] and profile.span_days == 1
    assert list(build_profile(worlds[-1], ignore_file_days=ignored).days) == [date(2023, 6, 1)]
    # A copy day with real chunk saves keeps the day, minus the file evidence.
    mixed = {copy_day: DaySignals(chunk_saves=2, file_saves=9)}
    kept = build_profile(mixed, ignore_file_days=ignored).days[copy_day]
    assert kept.chunk_saves == 2 and kept.file_saves == 0


def test_history_before_our_players_is_kept_apart():
    from mcatlas.core.activity import DaySignals, build_profile

    days = {
        date(2020, 3, 1): DaySignals(chunk_saves=900),
        date(2020, 7, 1): DaySignals(chunk_saves=500),
        date(2023, 9, 30): DaySignals(chunk_saves=10, advancements=2),
    }
    profile = build_profile(days, history_before=date(2023, 9, 1))
    assert list(profile.days) == [date(2023, 9, 30)]
    assert list(profile.history) == [date(2020, 3, 1), date(2020, 7, 1)]
    assert profile.first_day == date(2023, 9, 30) and profile.distinct_days == 1


def test_hours_per_session_flags_a_game_left_running() -> None:
    from mcatlas.core.catalog import AFK_SESSION_HOURS, PlayerSummary, _hours_per_session

    normal = PlayerSummary(uuid="a", play_hours=10.0, sessions=20)
    left_on = PlayerSummary(uuid="b", play_hours=33.4, sessions=1)
    no_stats = PlayerSummary(uuid="c", play_hours=0.0, sessions=None)
    assert _hours_per_session([normal, no_stats]) == 0.5
    assert (_hours_per_session([normal, left_on]) or 0) >= AFK_SESSION_HOURS
    assert _hours_per_session([no_stats]) is None
