"""Assemble per-world facts into the catalog that the site (and later the atlas) presents."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from pydantic import Field

from mcatlas.core import analyze
from mcatlas.core.activity import (
    ActivityProfile,
    DaySignals,
    archive_artifact_days,
    build_profile,
    collect_days,
)
from mcatlas.core.annotations import Annotation
from mcatlas.core.build import BuildMap, BuildSummary, summarize
from mcatlas.core.dedupe import similarity
from mcatlas.core.facts import (
    BlockFacts,
    Facts,
    FileFacts,
    InGameMap,
    LevelFacts,
    MapFacts,
    MapMosaic,
    PlayerFacts,
    PlayersFacts,
    PlayerState,
    RegionFacts,
    TextEntry,
)
from mcatlas.core.model import GameMode, Generator, WorldFormat, WorldId
from mcatlas.core.render import RenderedMap
from mcatlas.core.scoring import Importance, importance
from mcatlas.core.texts import clean, worth_keeping

TICKS_PER_HOUR = 72_000
RELATED_THRESHOLD = 0.15
AFK_SESSION_HOURS = 6.0
"""An average session this long suggests the game was left running (AFK, recording)."""
_BUILTIN_PACKS = frozenset({"vanilla", "file/bukkit"})


@dataclass(frozen=True, slots=True)
class StoredWorld:
    """A world as persisted by the fact store: identity plus raw facts JSON per analyzer."""

    world_id: WorldId
    source_id: str
    relpath: str
    folder_name: str
    format: WorldFormat
    fingerprint: str
    total_size: int
    facts: Mapping[str, str] = field(default_factory=dict[str, str])
    errors: Mapping[str, str] = field(default_factory=dict[str, str])
    has_icon_asset: bool = False


class PlayerSummary(Facts):
    uuid: str
    name: str | None = None
    known: bool = False
    """One of "our" players: the UUID has a name from the config or a usercache file."""
    play_hours: float = 0.0
    sessions: int | None = None
    items_used: int = 0
    advancements: int = 0
    game_mode: GameMode | None = None
    dimension: str | None = None
    position: tuple[float, float, float] | None = None


class DimensionSummary(Facts):
    key: str
    chunks: int
    region_files: int
    bbox_chunks: tuple[int, int, int, int] | None = None


class Related(Facts):
    world_id: WorldId
    folder_name: str
    similarity: float


class InGameMaps(Facts):
    """The world's in-game maps; images are named `maps/<image>` in the asset store."""

    total: int = 0
    filled: int = 0
    shown: list[InGameMap] = Field(default_factory=list[InGameMap])
    mosaics: list[MapMosaic] = Field(default_factory=list[MapMosaic])


MAX_MAP_ERRORS = 5


class WorldEntry(Facts):
    world_id: WorldId
    source_id: str
    relpath: str
    folder_name: str
    name: str
    """Best human-readable name: the in-game name, or the folder name when that is missing."""
    level_name: str | None = None
    format: WorldFormat
    version_name: str | None = None
    data_version: int | None = None
    game_mode: GameMode | None = None
    generator: Generator = Generator.UNKNOWN
    generator_detail: str | None = None
    hardcore: bool | None = None
    cheats: bool | None = None
    modded: bool | None = None
    datapacks: list[str] = Field(default_factory=list[str])
    seed: int | None = None
    last_played: datetime | None = None
    spawn: tuple[int, int, int] | None = None
    size_bytes: int = 0
    files: int = 0
    has_icon: bool = False
    map_items: int = 0
    in_game_maps: InGameMaps | None = None
    """None when there are none (or they were not analyzed yet)."""
    chunks: int = 0
    dimensions: list[DimensionSummary] = Field(default_factory=list[DimensionSummary])
    players: list[PlayerSummary] = Field(default_factory=list[PlayerSummary])
    play_hours: float = 0.0
    """Play time of our players (of all players when none of them is known)."""
    play_hours_all: float = 0.0
    foreign_players: int = 0
    """Players with play time whose UUID is not known (friends, or the makers of a map)."""
    sessions: int = 0
    """Sessions (`leave_game`) of the counted players, summed: dateless, but an upper bound."""
    days_upper: int | None = None
    """At most this many play days: every play day ends at least one session. The activity
    profile's distinct days are the lower bound; the truth lies in between."""
    hours_per_session: float | None = None
    """Longest average session among the counted players."""
    afk_suspect: bool = False
    """Play time is probably inflated by a game left running."""
    items_used: int = 0
    activity: ActivityProfile = Field(default_factory=ActivityProfile)
    build: BuildSummary | None = None
    """What players built and where (tier-2 analysis); None when not analyzed."""
    text_counts: dict[str, int] = Field(default_factory=dict[str, int])
    """Signs, books, names and commands found (tier 2), by kind."""
    annotation: Annotation | None = None
    """Our own notes about this world."""
    importance: Importance = Field(default_factory=Importance)
    related: list[Related] = Field(default_factory=list[Related])
    errors: list[str] = Field(default_factory=list[str])


class Catalog(Facts):
    generated_at: datetime
    timezone: str
    ignored_file_days: list[date] = Field(default_factory=list[date])
    """Days whose file-mtime evidence was discarded as archive/copy operations."""
    first_day: date | None = None
    last_day: date | None = None
    worlds: list[WorldEntry] = Field(default_factory=list[WorldEntry])
    maps: dict[WorldId, BuildMap] = Field(default_factory=dict[WorldId, BuildMap])
    """Per-chunk build maps, by world; large, so writers may store them separately."""
    texts: dict[WorldId, list[TextEntry]] = Field(default_factory=dict[WorldId, list[TextEntry]])
    """Texts found per world; large, so writers may store them separately."""
    annotations: dict[WorldId, Annotation] = Field(default_factory=dict[WorldId, Annotation])
    """Notes by world, including notes of worlds no longer in the archive."""
    renders: dict[WorldId, list[RenderedMap]] = Field(
        default_factory=dict[WorldId, list[RenderedMap]]
    )
    """3D maps (BlueMap) by world, with their flat top-down images."""


def _player(p: PlayerFacts, host: PlayerState | None, names: Mapping[str, str]) -> PlayerSummary:
    state = p.state or (host if host and host.uuid == p.uuid else None)
    stats = p.stats
    return PlayerSummary(
        uuid=p.uuid,
        name=names.get(p.uuid),
        known=p.uuid in names,
        play_hours=round(stats.play_ticks / TICKS_PER_HOUR, 2) if stats else 0.0,
        sessions=stats.sessions if stats else None,
        items_used=stats.used_total if stats else 0,
        advancements=p.advancements_done,
        game_mode=state.game_mode if state else None,
        dimension=state.dimension if state else None,
        position=state.position if state else None,
    )


@dataclass(frozen=True, slots=True)
class _Parsed:
    stored: StoredWorld
    level: LevelFacts | None
    players: PlayersFacts | None
    regions: RegionFacts | None
    files: FileFacts | None
    blocks: BlockFacts | None
    maps: MapFacts | None


def _parse(stored: StoredWorld) -> _Parsed:
    parsed: dict[str, Facts] = {}
    for name, payload in stored.facts.items():
        analyzer = analyze.BY_NAME.get(name)
        if analyzer is not None:
            parsed[name] = analyzer.parse(payload)
    level = parsed.get(analyze.LEVEL.name)
    players = parsed.get(analyze.PLAYERS.name)
    regions = parsed.get(analyze.REGIONS.name)
    files = parsed.get(analyze.FILES.name)
    blocks = parsed.get(analyze.BLOCKS.name)
    maps = parsed.get(analyze.MAPS.name)
    return _Parsed(
        stored=stored,
        level=level if isinstance(level, LevelFacts) else None,
        players=players if isinstance(players, PlayersFacts) else None,
        regions=regions if isinstance(regions, RegionFacts) else None,
        files=files if isinstance(files, FileFacts) else None,
        blocks=blocks if isinstance(blocks, BlockFacts) else None,
        maps=maps if isinstance(maps, MapFacts) else None,
    )


HISTORY_MARGIN = timedelta(days=1)


def _history_before(p: _Parsed, summaries: Sequence[PlayerSummary], tz: tzinfo) -> date | None:
    """Our history starts (with a day of margin) at our players' first advancement.

    Advancement criteria keep the moment they were first met, so in a world we created the
    first one lands on day one. Activity well before it came with the world: the makers of a
    downloaded map, or whoever played a copy before us. It is kept as history, not discarded.
    """
    if p.players is None:
        return None
    known = {s.uuid for s in summaries if s.known}
    own_times = [t for pl in p.players.players if pl.uuid in known for t in pl.advancement_times]
    return min(own_times).astimezone(tz).date() - HISTORY_MARGIN if own_times else None


def _hours_per_session(players: Sequence[PlayerSummary]) -> float | None:
    averages = [p.play_hours / p.sessions for p in players if p.sessions]
    return round(max(averages), 2) if averages else None


def _history_cutoff(p: _Parsed, names: Mapping[str, str], tz: tzinfo) -> int | None:
    """Unix time before which chunk saves belong to someone else's history (see activity)."""
    known = (
        [PlayerSummary(uuid=pl.uuid, known=pl.uuid in names) for pl in p.players.players]
        if p.players
        else []
    )
    before = _history_before(p, known, tz)
    if before is None:
        return None
    return int(datetime.combine(before, datetime.min.time(), tz).timestamp())


def _build(
    p: _Parsed, names: Mapping[str, str], tz: tzinfo
) -> tuple[BuildSummary, BuildMap] | None:
    if p.blocks is None or (p.level is not None and p.level.generator is Generator.DEBUG):
        return None  # a debug world shows every block state: nothing was built
    return summarize(p.blocks, history_before=_history_cutoff(p, names, tz))


def _texts(p: _Parsed, names: Mapping[str, str], tz: tzinfo) -> list[TextEntry]:
    """Cleaned texts; those in chunks saved before our players arrived are marked history."""
    if p.blocks is None:
        return []
    cutoff = _history_cutoff(p, names, tz)
    saved: dict[tuple[str, int, int], int] = {}
    if cutoff is not None:
        for d in p.blocks.dimensions:
            t = d.table
            for x, z, when in zip(t.x, t.z, t.saved, strict=False):
                saved[d.key, x, z] = when
    out: list[TextEntry] = []
    for t in p.blocks.texts:
        text = clean(t.text)
        if not worth_keeping(t.kind, text):
            continue
        history = False
        if cutoff is not None and t.dimension is not None and t.x is not None and t.z is not None:
            when = saved.get((t.dimension, t.x >> 4, t.z >> 4))
            history = when is not None and 0 < when < cutoff
        out.append(t.model_copy(update={"text": text, "history": history}))
    return out


def build_entry(
    p: _Parsed,
    names: Mapping[str, str],
    tz: tzinfo,
    days: dict[date, DaySignals],
    ignore_file_days: frozenset[date],
    *,
    build: BuildSummary | None = None,
    texts: Sequence[TextEntry] = (),
) -> WorldEntry:
    stored, level, players, regions, files = p.stored, p.level, p.players, p.regions, p.files
    errors = [f"{name}: {msg}" for name, msg in stored.errors.items()]
    host = level.host_player if level else None
    player_list = [_player(pl, host, names) for pl in players.players] if players else []
    if players:
        errors += players.errors
    if regions:
        errors += regions.errors
    chunks = sum(d.chunks for d in regions.dimensions) if regions else 0
    maps = p.maps
    if maps and maps.errors:
        errors += maps.errors[:MAX_MAP_ERRORS]
        if len(maps.errors) > MAX_MAP_ERRORS:
            errors.append(f"maps: {len(maps.errors) - MAX_MAP_ERRORS} more unreadable map files")

    activity = build_profile(
        days,
        ignore_file_days=ignore_file_days,
        history_before=_history_before(p, player_list, tz),
    )
    ours = [s for s in player_list if s.known and s.play_hours > 0]
    counted = ours or player_list
    play_hours = round(sum(s.play_hours for s in counted), 2)
    items_used = sum(s.items_used for s in counted)
    sessions = sum(s.sessions or 0 for s in counted)
    per_session = _hours_per_session(counted)

    return WorldEntry(
        world_id=stored.world_id,
        source_id=stored.source_id,
        relpath=stored.relpath,
        folder_name=stored.folder_name,
        name=(level.display_name if level and level.display_name else stored.folder_name),
        level_name=level.level_name if level else None,
        format=stored.format,
        version_name=level.version_name if level else None,
        data_version=level.data_version if level else None,
        game_mode=level.game_mode if level else None,
        generator=level.generator if level else Generator.UNKNOWN,
        generator_detail=level.generator_detail if level else None,
        hardcore=level.hardcore if level else None,
        cheats=level.cheats if level else None,
        modded=level.was_modded if level else None,
        datapacks=[d for d in (level.datapacks if level else []) if d not in _BUILTIN_PACKS],
        seed=level.seed if level else None,
        last_played=level.last_played if level else None,
        spawn=level.spawn if level else None,
        size_bytes=files.total_size if files else stored.total_size,
        files=files.files if files else 0,
        has_icon=stored.has_icon_asset,
        map_items=files.map_items if files else 0,
        in_game_maps=InGameMaps(
            total=maps.total, filled=maps.filled, shown=maps.shown, mosaics=maps.mosaics
        )
        if maps and maps.total
        else None,
        chunks=chunks,
        dimensions=[
            DimensionSummary(
                key=d.key, chunks=d.chunks, region_files=d.region_files, bbox_chunks=d.bbox_chunks
            )
            for d in (regions.dimensions if regions else [])
        ],
        players=player_list,
        play_hours=play_hours,
        play_hours_all=round(sum(s.play_hours for s in player_list), 2),
        foreign_players=sum(1 for s in player_list if not s.known and s.play_hours > 0),
        sessions=sessions,
        days_upper=max(sessions, activity.distinct_days) if sessions else None,
        hours_per_session=per_session,
        afk_suspect=per_session is not None and per_session >= AFK_SESSION_HOURS,
        items_used=items_used,
        activity=activity,
        build=build,
        text_counts=dict(Counter(t.kind for t in texts if not t.history)),
        importance=importance(
            distinct_days=activity.distinct_days,
            span_days=activity.span_days,
            play_hours=play_hours,
            items_used=items_used,
            chunks=chunks,
            built=build.built if build else 0,
        ),
        errors=errors,
    )


def _related(entries: Sequence[WorldEntry], stored: Sequence[StoredWorld]) -> list[WorldEntry]:
    signatures: dict[WorldId, list[int]] = {}
    for s in stored:
        payload = s.facts.get(analyze.REGIONS.name)
        if payload is not None:
            signatures[s.world_id] = analyze.REGIONS.parse(payload).minhash
    by_id = {e.world_id: e for e in entries}
    links: dict[WorldId, list[Related]] = {e.world_id: [] for e in entries}
    ids = [i for i in by_id if signatures.get(i)]
    for n, a in enumerate(ids):
        for b in ids[n + 1 :]:
            sim = similarity(signatures[a], signatures[b])
            if sim >= RELATED_THRESHOLD:
                links[a].append(
                    Related(world_id=b, folder_name=by_id[b].folder_name, similarity=sim)
                )
                links[b].append(
                    Related(world_id=a, folder_name=by_id[a].folder_name, similarity=sim)
                )
    return [
        e.model_copy(update={"related": sorted(links[e.world_id], key=lambda r: -r.similarity)})
        for e in entries
    ]


def _renders(
    renders: Sequence[RenderedMap], present: set[WorldId]
) -> dict[WorldId, list[RenderedMap]]:
    by_world: dict[WorldId, list[RenderedMap]] = {}
    for r in sorted(renders, key=lambda r: r.sorting):
        if r.world_id in present and r.rendered_at is not None:
            by_world.setdefault(r.world_id, []).append(r)
    return by_world


def build_catalog(
    stored: Sequence[StoredWorld],
    names: Mapping[str, str],
    tz: tzinfo,
    now: datetime,
    *,
    ignore_file_days: frozenset[date] = frozenset(),
    annotations: Mapping[WorldId, Annotation] | None = None,
    renders: Sequence[RenderedMap] = (),
) -> Catalog:
    notes = dict(annotations or {})
    parsed = [_parse(s) for s in stored]
    raw_days = [
        collect_days(regions=p.regions, files=p.files, players=p.players, level=p.level, tz=tz)
        for p in parsed
    ]
    ignored = archive_artifact_days(raw_days) | ignore_file_days
    builds = [_build(p, names, tz) for p in parsed]
    texts = {p.stored.world_id: _texts(p, names, tz) for p in parsed}
    entries = _related(
        [
            build_entry(
                p, names, tz, d, ignored, build=b[0] if b else None, texts=texts[p.stored.world_id]
            )
            for p, d, b in zip(parsed, raw_days, builds, strict=True)
        ],
        stored,
    )
    entries.sort(key=lambda e: (-e.importance.score, e.name.casefold()))
    firsts = [e.activity.first_day for e in entries if e.activity.first_day]
    lasts = [e.activity.last_day for e in entries if e.activity.last_day]
    return Catalog(
        generated_at=now,
        timezone=str(tz),
        ignored_file_days=sorted(ignored),
        first_day=min(firsts) if firsts else None,
        last_day=max(lasts) if lasts else None,
        worlds=[e.model_copy(update={"annotation": notes.get(e.world_id)}) for e in entries],
        annotations=notes,
        maps={p.stored.world_id: b[1] for p, b in zip(parsed, builds, strict=True) if b},
        texts={w: t for w, t in texts.items() if t},
        renders=_renders(renders, {e.world_id for e in entries}),
    )
