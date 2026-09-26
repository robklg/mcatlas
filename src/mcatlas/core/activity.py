"""Combine all dated signals of a world into one activity profile.

Every signal only gives a lower bound on real play days: region timestamps are overwritten on
each save, file mtimes only keep the last write. Their union is the best available estimate, and
each day records which signals support it so the UI can show the evidence.

Two corrections keep the estimate honest:

* **Archive artifacts.** Copying an archive can stamp many files with the copy date. A day on
  which many *different* worlds changed only file mtimes (no chunk saves, no advancements) is an
  archive operation, not play; file-only signals on such days are ignored everywhere.
* **Imported history.** A downloaded map carries its makers' chunk timestamps. When the caller
  knows when "our" players arrived (`history_before`), earlier days are kept separately as
  history instead of counting as our activity.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime, tzinfo

from pydantic import Field

from mcatlas.core.facts import Facts, FileFacts, LevelFacts, PlayersFacts, RegionFacts

ARTIFACT_MIN_WORLDS = 5
ARTIFACT_MIN_SHARE = 0.10


class DaySignals(Facts):
    chunk_saves: int = 0
    """Chunks whose last save happened on this day."""
    file_saves: int = 0
    """Game files last modified on this day."""
    advancements: int = 0
    """Advancement criteria first met on this day."""
    last_played: bool = False

    @property
    def file_only(self) -> bool:
        return self.file_saves > 0 and not (
            self.chunk_saves or self.advancements or self.last_played
        )


class ActivityProfile(Facts):
    days: dict[date, DaySignals] = Field(default_factory=dict[date, DaySignals])
    distinct_days: int = 0
    first_day: date | None = None
    last_day: date | None = None
    span_days: int = 0
    """Calendar days from first to last activity, inclusive."""
    active_months: int = 0
    history: dict[date, DaySignals] = Field(default_factory=dict[date, DaySignals])
    """Activity from before our players arrived (e.g. the makers of a downloaded map)."""


def _hour_to_day(hour: int, tz: tzinfo) -> date:
    return datetime.fromtimestamp(hour * 3600, tz).date()


def _count_by_day(by_hour: Iterable[tuple[int, int]], tz: tzinfo) -> dict[date, int]:
    days: dict[date, int] = {}
    for hour, n in by_hour:
        day = _hour_to_day(hour, tz)
        days[day] = days.get(day, 0) + n
    return days


def collect_days(
    *,
    regions: RegionFacts | None,
    files: FileFacts | None,
    players: PlayersFacts | None,
    level: LevelFacts | None,
    tz: tzinfo,
) -> dict[date, DaySignals]:
    """All dated evidence of a world, per local calendar day, without any correction."""
    chunk_days: dict[date, int] = {}
    if regions is not None:
        for dim in regions.dimensions:
            for day, n in _count_by_day(dim.chunk_saves_by_hour.items(), tz).items():
                chunk_days[day] = chunk_days.get(day, 0) + n
    file_days = _count_by_day(files.game_file_saves_by_hour.items(), tz) if files else {}
    adv_days: dict[date, int] = {}
    for player in players.players if players else []:
        for moment in player.advancement_times:
            day = moment.astimezone(tz).date()
            adv_days[day] = adv_days.get(day, 0) + 1
    played = level.last_played.astimezone(tz).date() if level and level.last_played else None

    day_set = set(chunk_days) | set(file_days) | set(adv_days)
    if played is not None:
        day_set.add(played)
    return {
        d: DaySignals(
            chunk_saves=chunk_days.get(d, 0),
            file_saves=file_days.get(d, 0),
            advancements=adv_days.get(d, 0),
            last_played=d == played,
        )
        for d in sorted(day_set)
    }


def archive_artifact_days(worlds: Sequence[dict[date, DaySignals]]) -> frozenset[date]:
    """Days on which many worlds show nothing but file-mtime changes: copy/backup operations."""
    active = sum(1 for days in worlds if days)
    threshold = max(ARTIFACT_MIN_WORLDS, ARTIFACT_MIN_SHARE * active)
    counts = Counter(d for days in worlds for d, sig in days.items() if sig.file_only)
    return frozenset(d for d, n in counts.items() if n >= threshold)


def build_profile(
    days: dict[date, DaySignals],
    *,
    ignore_file_days: frozenset[date] = frozenset(),
    history_before: date | None = None,
) -> ActivityProfile:
    kept: dict[date, DaySignals] = {}
    history: dict[date, DaySignals] = {}
    for d, raw in days.items():
        sig = raw.model_copy(update={"file_saves": 0}) if d in ignore_file_days else raw
        if not (sig.chunk_saves or sig.file_saves or sig.advancements or sig.last_played):
            continue
        (history if history_before is not None and d < history_before else kept)[d] = sig

    ordered = sorted(kept)
    if not ordered:
        return ActivityProfile(history=history)
    first, last = ordered[0], ordered[-1]
    return ActivityProfile(
        days={d: kept[d] for d in ordered},
        distinct_days=len(ordered),
        first_day=first,
        last_day=last,
        span_days=(last - first).days + 1,
        active_months=len({(d.year, d.month) for d in ordered}),
        history=history,
    )


def build_activity(
    *,
    regions: RegionFacts | None,
    files: FileFacts | None,
    players: PlayersFacts | None,
    level: LevelFacts | None,
    tz: tzinfo,
    ignore_file_days: frozenset[date] = frozenset(),
    history_before: date | None = None,
) -> ActivityProfile:
    days = collect_days(regions=regions, files=files, players=players, level=level, tz=tz)
    return build_profile(days, ignore_file_days=ignore_file_days, history_before=history_before)
