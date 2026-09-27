"""The durable atlas: what mcatlas found, as plain files that outlive mcatlas.

Written next to the archive, readable in twenty years with nothing but a text editor or a web
browser: Markdown and script-free HTML pages (the same content twice), one TOML file of facts
per world (schema in `schema/world.schema.json`), a CSV for spreadsheets and PNG images (the
world icon and flat maps of the build sites). No database, no JavaScript.

Everything here is pure: `atlas_files` turns a catalog into file contents by relative path, and
the same catalog always gives the same files. Notes (`annotations/`) are never part of it: they
are the family's own files, and the pages only quote them.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

import tomli_w
from pydantic import Field

from mcatlas.core.annotations import Annotation
from mcatlas.core.build import BuildSite
from mcatlas.core.catalog import Catalog, WorldEntry
from mcatlas.core.document import (
    Block,
    Code,
    Document,
    Heading,
    Image,
    Inline,
    Items,
    Link,
    Markdown,
    Paragraph,
    Pre,
    Table,
    Text,
    link,
    page,
    to_html,
    to_markdown,
)
from mcatlas.core.facts import Facts, TextEntry
from mcatlas.core.model import Language, WorldFormat, WorldId
from mcatlas.core.render import RenderedMap
from mcatlas.core.words import WORDS, Words, count, day, hours, num

SCHEMA_VERSION: Final = 1
"""Version of facts.toml and worlds.csv; bump on any incompatible change."""
WORLDS_DIR: Final = "worlds"
NOTES_DIR: Final = "annotations"
"""The notes folder next to the export; the export never writes there."""
TEXTS: Final = "texts"
"""Base name of the texts page of a world (texts.md, texts.html)."""


@dataclass(frozen=True, slots=True)
class AtlasChanges:
    location: str
    written: int
    unchanged: int
    removed: int
    """Files of an earlier export that are no longer part of it."""


# ---------- formatting ----------


def _period(w: Words, e: WorldEntry) -> str:
    a = e.activity
    if a.first_day is None or a.last_day is None:
        return "–"
    if a.first_day == a.last_day:
        return day(w, a.first_day)
    return f"{day(w, a.first_day)} – {day(w, a.last_day)}"


def _days(w: Words, e: WorldEntry) -> str:
    low = e.activity.distinct_days
    if e.days_upper is not None and e.days_upper > low:
        return f"{num(w, low)}–{num(w, e.days_upper)}"
    return num(w, low)


def _pct(w: Words, pct: float | None) -> str:
    return f"{num(w, pct)}%" if pct is not None else "–"


def _dimension(w: Words, key: str) -> str:
    return w.dimensions.get(key, key)


def _block(name: str) -> str:
    return name.removeprefix("minecraft:").replace("_", " ")


def _rating(r: int | None) -> str:
    return "★" * r + "☆" * (5 - r) if r else ""


def _tp(site: BuildSite) -> str:
    return f"/execute in {site.dimension} run tp @s {site.x} {site.max_y + 2} {site.z}"


def world_dir(world_id: WorldId) -> str:
    return f"{WORLDS_DIR}/{world_id}/"


# ---------- facts.toml ----------


class AtlasPlayer(Facts):
    uuid: str
    name: str | None = None
    ours: bool = False
    """One of our players (named in the launcher's user cache or the mcatlas config)."""
    play_hours: float = 0.0
    sessions: int | None = None
    items_used: int = 0
    advancements: int = 0
    game_mode: str | None = None
    dimension: str | None = None
    position: list[float] | None = None


class AtlasActivity(Facts):
    first_day: date | None = None
    last_day: date | None = None
    span_days: int = 0
    days_min: int = 0
    """Days with dated evidence of play: a lower bound."""
    days_max: int | None = None
    """Sessions counted by the game: every play day has at least one, so an upper bound."""
    active_months: int = 0
    days: list[date] = Field(default_factory=list[date])
    history_days: list[date] = Field(default_factory=list[date])
    """Activity before our players arrived (the makers of a downloaded map)."""


class AtlasPlay(Facts):
    hours: float = 0.0
    """Play time of our players (of all players when none of them is known)."""
    hours_all_players: float = 0.0
    sessions: int = 0
    items_used: int = 0
    """Includes every block placed, also in creative mode."""
    longest_average_session_hours: float | None = None
    left_running: bool = False
    """Play time is probably inflated by a game left running."""
    other_players: int = 0


class AtlasSite(Facts):
    number: int
    dimension: str
    x: int
    z: int
    area: list[int]
    """min_x, min_z, max_x, max_z in blocks."""
    min_y: int
    max_y: int
    chunks: int
    built: int
    below: int
    pct_below: float | None = None
    hours_nearby: float
    teleport: str
    image: str | None = None


class AtlasBuild(Facts):
    built: int = 0
    """Blocks the world generator does not place itself (≈ m³ of building)."""
    below: int = 0
    pct_below: float | None = None
    no_ground: int = 0
    structure_blocks: int = 0
    history_built: int = 0
    built_chunks: int = 0
    main_dimension: str | None = None
    top_blocks: dict[str, int] = Field(default_factory=dict[str, int])
    sites: list[AtlasSite] = Field(default_factory=list[AtlasSite])


class AtlasNote(Facts):
    title: str = ""
    tags: list[str] = Field(default_factory=list[str])
    rating: int | None = None


class AtlasRelated(Facts):
    world_id: str
    folder: str
    similarity: float


class AtlasWorld(Facts):
    """facts.toml: everything mcatlas found about one world."""

    schema_version: int = SCHEMA_VERSION
    world_id: str
    name: str
    folder: str
    source: str
    path: str
    """Folder of the world, relative to the source (the archive)."""
    level_name: str | None = None
    format: str
    version: str | None = None
    data_version: int | None = None
    game_mode: str | None = None
    generator: str
    generator_detail: str | None = None
    hardcore: bool | None = None
    cheats: bool | None = None
    modded: bool | None = None
    datapacks: list[str] = Field(default_factory=list[str])
    seed: int | None = None
    last_played: datetime | None = None
    spawn: list[int] | None = None
    size_bytes: int = 0
    files: int = 0
    chunks: int = 0
    importance: float = 0.0
    importance_parts: dict[str, float] = Field(default_factory=dict[str, float])
    texts: dict[str, int] = Field(default_factory=dict[str, int])
    errors: list[str] = Field(default_factory=list[str])
    note: AtlasNote | None = None
    activity: AtlasActivity
    play: AtlasPlay
    players: list[AtlasPlayer] = Field(default_factory=list[AtlasPlayer])
    build: AtlasBuild | None = None
    related: list[AtlasRelated] = Field(default_factory=list[AtlasRelated])


def _site_images(renders: Sequence[RenderedMap]) -> dict[int | None, str]:
    """Render image path per build site index (None = spawn area)."""
    found: dict[int | None, str] = {}
    for m in renders:
        for i, path in sorted(m.images.items()):
            if 0 <= i < len(m.areas):
                found.setdefault(m.areas[i].site, path)
    return found


def image_name(site: int | None) -> str:
    return "spawn.png" if site is None else f"site-{site + 1}.png"


def atlas_world(e: WorldEntry, images: Mapping[int | None, str]) -> AtlasWorld:
    a = e.activity
    b = e.build
    note = e.annotation
    return AtlasWorld(
        world_id=e.world_id,
        name=e.name,
        folder=e.folder_name,
        source=e.source_id,
        path=e.relpath,
        level_name=e.level_name,
        format=e.format.value,
        version=e.version_name,
        data_version=e.data_version,
        game_mode=e.game_mode.name.lower() if e.game_mode is not None else None,
        generator=e.generator.value,
        generator_detail=e.generator_detail,
        hardcore=e.hardcore,
        cheats=e.cheats,
        modded=e.modded,
        datapacks=e.datapacks,
        seed=e.seed,
        last_played=e.last_played,
        spawn=list(e.spawn) if e.spawn else None,
        size_bytes=e.size_bytes,
        files=e.files,
        chunks=e.chunks,
        importance=e.importance.score,
        importance_parts=e.importance.components,
        texts=dict(sorted(e.text_counts.items())),
        errors=e.errors,
        note=AtlasNote(title=note.title, tags=note.tags, rating=note.rating) if note else None,
        activity=AtlasActivity(
            first_day=a.first_day,
            last_day=a.last_day,
            span_days=a.span_days,
            days_min=a.distinct_days,
            days_max=e.days_upper,
            active_months=a.active_months,
            days=sorted(a.days),
            history_days=sorted(a.history),
        ),
        play=AtlasPlay(
            hours=e.play_hours,
            hours_all_players=e.play_hours_all,
            sessions=e.sessions,
            items_used=e.items_used,
            longest_average_session_hours=e.hours_per_session,
            left_running=e.afk_suspect,
            other_players=e.foreign_players,
        ),
        players=[
            AtlasPlayer(
                uuid=p.uuid,
                name=p.name,
                ours=p.known,
                play_hours=p.play_hours,
                sessions=p.sessions,
                items_used=p.items_used,
                advancements=p.advancements,
                game_mode=p.game_mode.name.lower() if p.game_mode is not None else None,
                dimension=p.dimension,
                position=[round(c, 1) for c in p.position] if p.position else None,
            )
            for p in e.players
        ],
        build=AtlasBuild(
            built=b.built,
            below=b.below,
            pct_below=b.pct_below,
            no_ground=b.no_ground,
            structure_blocks=b.structure_built,
            history_built=b.history_built,
            built_chunks=b.built_chunks,
            main_dimension=b.main_dimension,
            top_blocks=dict(b.top_blocks),
            sites=[
                AtlasSite(
                    number=i + 1,
                    dimension=s.dimension,
                    x=s.x,
                    z=s.z,
                    area=list(s.bbox),
                    min_y=s.min_y,
                    max_y=s.max_y,
                    chunks=s.chunks,
                    built=s.built,
                    below=s.below,
                    pct_below=s.pct_below,
                    hours_nearby=s.hours_nearby,
                    teleport=_tp(s),
                    image=image_name(i) if i in images else None,
                )
                for i, s in enumerate(b.sites)
            ],
        )
        if b is not None
        else None,
        related=[
            AtlasRelated(
                world_id=r.world_id, folder=r.folder_name, similarity=round(r.similarity, 3)
            )
            for r in e.related
        ],
    )


def facts_toml(world: AtlasWorld) -> str:
    header = (
        f"# {world.name}: facts found by mcatlas (schema {world.schema_version}).\n"
        "# Field descriptions: ../../schema/world.schema.json\n\n"
    )
    return header + tomli_w.dumps(world.model_dump(exclude_none=True))


def world_schema() -> str:
    return json.dumps(AtlasWorld.model_json_schema(), indent=2, ensure_ascii=False) + "\n"


# ---------- worlds.csv ----------

CSV_COLUMNS: Final = (
    "world_id", "name", "folder", "path", "version", "game_mode", "generator",
    "first_day", "last_day", "span_days", "days_min", "days_max", "active_months",
    "play_hours", "sessions", "items_used", "built", "pct_below", "sites", "chunks",
    "size_bytes", "players", "importance", "note_title", "note_tags", "note_rating",
)  # fmt: skip


def _csv_field(value: object) -> str:
    """RFC 4180: quote fields holding a comma, quote or line break."""
    text = str(value)
    if any(c in text for c in ',"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def _csv_row(e: WorldEntry) -> list[object]:
    a, b, note = e.activity, e.build, e.annotation
    return [
        e.world_id,
        e.name,
        e.folder_name,
        e.relpath,
        e.version_name or "",
        e.game_mode.name.lower() if e.game_mode is not None else "",
        e.generator.value,
        a.first_day.isoformat() if a.first_day else "",
        a.last_day.isoformat() if a.last_day else "",
        a.span_days,
        a.distinct_days,
        e.days_upper if e.days_upper is not None else "",
        a.active_months,
        e.play_hours,
        e.sessions,
        e.items_used,
        b.built if b else "",
        b.pct_below if b and b.pct_below is not None else "",
        len(b.sites) if b else "",
        e.chunks,
        e.size_bytes,
        "; ".join(p.name or p.uuid for p in e.players if p.play_hours > 0),
        e.importance.score,
        note.title if note else "",
        "; ".join(note.tags) if note else "",
        note.rating if note and note.rating else "",
    ]


def worlds_csv(worlds: Sequence[WorldEntry]) -> str:
    rows = [list(CSV_COLUMNS), *(_csv_row(e) for e in worlds)]
    return "".join(",".join(_csv_field(v) for v in row) + "\n" for row in rows)


# ---------- pages ----------


def _note_line(note: Annotation | None) -> str:
    if note is None:
        return ""
    parts = [note.title, _rating(note.rating), ", ".join(note.tags)]
    return " · ".join(p for p in parts if p)


def _players_line(e: WorldEntry) -> str:
    return ", ".join(p.name or p.uuid[:8] for p in e.players if p.play_hours > 0 and p.known)


def index_document(w: Words, catalog: Catalog, generated: date) -> Document:
    rows: list[Sequence[Text]] = []
    for n, e in enumerate(catalog.worlds, 1):
        b = e.build
        rows.append(
            [
                str(n),
                page(e.name, world_dir(e.world_id)),
                _period(w, e),
                _days(w, e),
                hours(w, e.play_hours),
                num(w, b.built) if b else "–",
                _pct(w, b.pct_below) if b else "–",
                _players_line(e),
                _note_line(e.annotation),
            ]
        )
    present = {e.world_id for e in catalog.worlds}
    orphans = sorted(
        (a for wid, a in catalog.annotations.items() if wid not in present),
        key=lambda a: a.world,
    )
    period = (
        w.played_between.format(first=day(w, catalog.first_day), last=day(w, catalog.last_day))
        if catalog.first_day and catalog.last_day
        else ""
    )
    intro = w.index_intro.format(
        worlds=count(w, len(catalog.worlds), w.worlds), period=period, day=day(w, generated)
    )
    blocks: list[Block] = [
        Paragraph(
            [
                intro,
                Link("README", "README.md", "README.md"),
                w.as_spreadsheet,
                link("worlds.csv", "worlds.csv"),
                ".",
            ]
        ),
        Table(list(w.index_header), rows, numeric=(0, 3, 4, 5, 6)),
    ]
    if orphans:
        blocks += [
            Heading(2, w.orphans_heading),
            Paragraph(w.orphans_text.format(dir=NOTES_DIR)),
            Items([[Code(a.world), f" {a.folder} {a.title}".rstrip()] for a in orphans]),
        ]
    return Document(w.index_title, blocks)


def _play_rows(w: Words, e: WorldEntry) -> list[tuple[str, Text]]:
    a, b = e.activity, e.build
    rows: list[tuple[str, Text]] = []
    if e.format is not WorldFormat.ANVIL:
        rows.append((w.kind, w.formats.get(e.format, e.format.value)))
    span = f" ({count(w, a.span_days, w.days)})" if a.span_days > 1 else ""
    rows.append((w.period, _period(w, e) + span))
    months = (
        w.in_months.format(months=count(w, a.active_months, w.months_count))
        if a.active_months > 1
        else ""
    )
    rows.append((w.active_days, _days(w, e) + months))
    play = hours(w, e.play_hours)
    if e.foreign_players:
        play += w.own_players.format(hours=hours(w, e.play_hours_all))
    if e.sessions:
        play += f", {count(w, e.sessions, w.sessions)}"
    if e.afk_suspect:
        play += w.left_running
    rows.append((w.play_time, play))
    if e.items_used:
        rows.append((w.items_used, w.items_used_value.format(n=num(w, e.items_used))))
    if b is not None:
        built = count(w, b.built, w.blocks)
        if b.pct_below is not None:
            built += ", " + w.below.format(pct=num(w, b.pct_below))
        rows.append((w.built, built))
        if b.history_built:
            rows.append((w.by_makers, w.by_makers_value.format(n=num(w, b.history_built))))
    return rows


def _world_rows(w: Words, e: WorldEntry) -> list[tuple[str, Text]]:
    rows: list[tuple[str, Text]] = []
    where = ", ".join(_dimension(w, d.key) for d in e.dimensions)
    rows.append((w.explored, f"{num(w, e.chunks)} chunks" + (f" in {where}" if where else "")))
    if e.version_name:
        rows.append((w.version, e.version_name))
    if e.game_mode is not None:
        mode = w.modes[e.game_mode] + (", hardcore" if e.hardcore else "")
        rows.append((w.game_mode, mode + (f", {w.cheats_on}" if e.cheats else "")))
    generator = w.generators.get(e.generator.value, e.generator.value)
    if e.generator_detail:
        generator += f" ({e.generator_detail})"
    rows.append((w.world_type, generator))
    if e.modded:
        rows.append((w.mods, w.yes))
    if e.datapacks:
        rows.append((w.datapacks, ", ".join(e.datapacks)))
    if e.seed is not None:
        rows.append(("Seed", Code(str(e.seed))))
    if e.spawn is not None:
        rows.append(("Spawn", Code(" ".join(str(c) for c in e.spawn))))
    if e.last_played is not None:
        rows.append((w.last_opened, day(w, e.last_played.date())))
    size = w.size_value.format(
        mb=num(w, e.size_bytes / 1_048_576, 1), files=count(w, e.files, w.files)
    )
    rows.append((w.size, size))
    parts = ", ".join(
        f"{w.importance.get(k, k)} {num(w, v, 1)}" for k, v in e.importance.components.items() if v
    )
    score = num(w, e.importance.score, 1) + (f" ({parts})" if parts else "")
    rows.append((w.importance_label, score))
    return rows


def _players(w: Words, e: WorldEntry) -> list[Block]:
    shown = [p for p in e.players if p.play_hours > 0 or p.known]
    if not shown:
        return []
    rows: list[Sequence[Text]] = []
    for p in sorted(shown, key=lambda p: -p.play_hours):
        where = ""
        if p.position is not None:
            x, y, z = (round(c) for c in p.position)
            where = f"{_dimension(w, p.dimension or '')} {x} {y} {z}".strip()
        rows.append(
            [
                p.name or Code(p.uuid),
                hours(w, p.play_hours),
                num(w, p.sessions) if p.sessions is not None else "–",
                num(w, p.items_used),
                num(w, p.advancements),
                w.modes[p.game_mode] if p.game_mode is not None else "",
                where,
            ]
        )
    return [
        Heading(2, w.players_heading),
        Table(list(w.players_header), rows, numeric=(1, 2, 3, 4)),
    ]


def _sites(w: Words, e: WorldEntry, images: Mapping[int | None, str]) -> list[Block]:
    b = e.build
    if b is None:
        return []
    blocks: list[Block] = []
    if b.sites:
        rows: list[Sequence[Text]] = []
        for i, s in enumerate(b.sites):
            rows.append(
                [
                    str(i + 1),
                    _dimension(w, s.dimension),
                    Code(f"{s.x} {s.z}"),
                    f"{s.bbox[2] - s.bbox[0] + 1} × {s.bbox[3] - s.bbox[1] + 1}",
                    w.height_range.format(low=s.min_y, high=s.max_y),
                    num(w, s.built),
                    _pct(w, s.pct_below),
                    hours(w, s.hours_nearby),
                    Code(_tp(s)),
                ]
            )
        blocks += [
            Heading(2, w.sites_heading),
            Paragraph(w.sites_text),
            Table(list(w.sites_header), rows, numeric=(0, 5, 6, 7)),
        ]
    for i, s in enumerate(b.sites):
        if i in images:
            caption = w.site_caption.format(
                n=i + 1, dimension=_dimension(w, s.dimension), x=s.x, z=s.z
            )
            blocks.append(Image(image_name(i), w.site_alt.format(n=i + 1), caption))
    if None in images:
        around = w.around.format(x=e.spawn[0], z=e.spawn[2]) if e.spawn else ""
        blocks.append(Image(image_name(None), w.spawn_alt, w.spawn_caption.format(around=around)))
    if b.top_blocks:
        blocks += [
            Heading(2, w.top_blocks),
            Table(
                list(w.top_blocks_header),
                [[_block(name), num(w, n)] for name, n in b.top_blocks],
                numeric=(1,),
            ),
        ]
    return blocks


def _timeline(w: Words, e: WorldEntry) -> list[Block]:
    def months(days: Sequence[date]) -> list[Text]:
        by_month: dict[tuple[int, int], list[int]] = {}
        for d in sorted(days):
            by_month.setdefault((d.year, d.month), []).append(d.day)
        return [
            f"{w.months[m - 1]} {y}: {', '.join(str(d) for d in ds)} ({count(w, len(ds), w.days)})"
            for (y, m), ds in by_month.items()
        ]

    blocks: list[Block] = []
    if e.activity.days:
        blocks += [
            Heading(2, w.timeline),
            Paragraph(w.timeline_text),
            Items(months(list(e.activity.days))),
        ]
    if e.activity.history:
        blocks += [
            Heading(3, w.history),
            Paragraph(w.history_text),
            Items(months(list(e.activity.history))),
        ]
    return blocks


def _note(w: Words, note: Annotation | None) -> list[Block]:
    if note is None or note.is_empty:
        return []
    blocks: list[Block] = [Heading(2, w.note_heading)]
    line = _note_line(note)
    if line:
        blocks.append(Paragraph(line))
    if note.note.strip():
        blocks.append(Markdown(note.note))
    blocks.append(Paragraph(w.note_source.format(dir=NOTES_DIR)))
    return blocks


def _texts_line(w: Words, e: WorldEntry) -> list[Block]:
    if not e.text_counts:
        return []
    counts = ", ".join(
        f"{w.text_kinds.get(k, k).lower()} {num(w, n)}" for k, n in sorted(e.text_counts.items())
    )
    return [
        Heading(2, w.texts_heading),
        Paragraph(
            [
                w.texts_found.format(counts=counts),
                page(w.texts_link, "", md=f"{TEXTS}.md", html=f"{TEXTS}.html"),
                ".",
            ]
        ),
    ]


def _related(w: Words, e: WorldEntry) -> list[Block]:
    if not e.related:
        return []
    return [
        Heading(2, w.related),
        Paragraph(w.related_text),
        Items(
            [
                [
                    page(r.folder_name, f"../{r.world_id}/"),
                    w.similarity.format(pct=num(w, 100 * r.similarity)),
                ]
                for r in e.related
            ]
        ),
    ]


def world_document(
    w: Words, e: WorldEntry, images: Mapping[int | None, str], *, has_icon: bool
) -> Document:
    where: list[Inline] = [w.in_archive, Code(e.relpath)]
    if e.folder_name != e.name:
        where = [*where, w.folder_name.format(folder=e.folder_name)]
    blocks: list[Block] = [
        Paragraph(
            [
                page(w.all_worlds, "../../", md="index.md"),
                " · ",
                link(w.facts_link, "facts.toml"),
            ]
        ),
        Paragraph(where),
    ]
    if has_icon:
        blocks.append(Image("icon.png", w.icon_alt))
    blocks += _note(w, e.annotation)
    blocks += [
        Heading(2, w.summary),
        Table(["", ""], [list(r) for r in _play_rows(w, e) + _world_rows(w, e)]),
    ]
    blocks += _sites(w, e, images)
    blocks += _players(w, e)
    blocks += _timeline(w, e)
    blocks += _texts_line(w, e)
    blocks += _related(w, e)
    if e.errors:
        blocks += [Heading(2, w.problems), Items(e.errors)]
    return Document(e.name, blocks)


def _where(w: Words, t: TextEntry) -> Text:
    if t.x is None or t.y is None or t.z is None:
        return ""
    dim = (
        f"{_dimension(w, t.dimension)} "
        if t.dimension and t.dimension != "minecraft:overworld"
        else ""
    )
    return [dim, Code(f"{t.x} {t.y} {t.z}")]


def texts_document(w: Words, e: WorldEntry, texts: Sequence[TextEntry]) -> Document:
    blocks: list[Block] = [
        Paragraph([page(f"← {e.name}", "", md="README.md", html="index.html")]),
        Paragraph(w.texts_intro),
    ]
    for history in (False, True):
        group = [t for t in texts if t.history == history]
        if not group:
            continue
        if history:
            blocks += [Heading(2, w.texts_history), Paragraph(w.texts_history_text)]
        level = 3 if history else 2
        for kind, label in w.text_kinds.items():
            of_kind = [t for t in group if t.kind == kind]
            if not of_kind:
                continue
            blocks.append(Heading(level, f"{label} ({num(w, len(of_kind))})"))
            if kind == "book":
                for t in of_kind:
                    held = w.book_in.format(holder=t.holder)
                    blocks += [Paragraph([held, *_as_list(_where(w, t))]), Pre(t.text)]
            else:
                blocks.append(
                    Table(
                        list(w.texts_header),
                        [
                            [Code(t.text) if kind == "command" else t.text, t.holder, _where(w, t)]
                            for t in of_kind
                        ],
                    )
                )
    return Document(w.texts_title.format(name=e.name), blocks)


def _as_list(text: Text) -> list[Inline]:
    return [text] if isinstance(text, str | Link | Code) else list(text)


def readme_document(w: Words, catalog: Catalog, generated: date, tool: str) -> str:
    made = w.readme_made.format(
        day=day(w, generated),
        tool=tool,
        schema=SCHEMA_VERSION,
        worlds=count(w, len(catalog.worlds), w.worlds),
    )
    return f"# {w.readme_title}\n\n{made}\n\n{w.readme}"


# ---------- all files ----------


def atlas_files(
    catalog: Catalog,
    *,
    icons: Mapping[WorldId, bytes],
    images: Mapping[str, bytes],
    generated: date,
    tool: str,
    language: Language = "en",
) -> dict[str, bytes]:
    """Every file of the atlas by relative path. `images` are flat maps by render path.

    File names are the same in every language, so a change of language rewrites the pages
    but leaves no files of the other language behind.
    """
    w = WORDS[language]
    files: dict[str, bytes] = {
        "README.md": readme_document(w, catalog, generated, tool).encode(),
        "worlds.csv": worlds_csv(catalog.worlds).encode(),
        "schema/world.schema.json": world_schema().encode(),
    }
    index = index_document(w, catalog, generated)
    files["index.md"] = to_markdown(index).encode()
    files["index.html"] = to_html(index, lang=language).encode()
    for e in catalog.worlds:
        base = world_dir(e.world_id)
        paths = {
            site: path
            for site, path in _site_images(catalog.renders.get(e.world_id, [])).items()
            if path in images
        }
        icon = icons.get(e.world_id)
        doc = world_document(w, e, paths, has_icon=icon is not None)
        files[base + "README.md"] = to_markdown(doc).encode()
        files[base + "index.html"] = to_html(doc, lang=language).encode()
        files[base + "facts.toml"] = facts_toml(atlas_world(e, paths)).encode()
        if icon is not None:
            files[base + "icon.png"] = icon
        for site, path in paths.items():
            files[base + image_name(site)] = images[path]
        texts = catalog.texts.get(e.world_id, [])
        if texts:
            tdoc = texts_document(w, e, texts)
            files[base + f"{TEXTS}.md"] = to_markdown(tdoc).encode()
            files[base + f"{TEXTS}.html"] = to_html(tdoc, lang=language).encode()
    return files
