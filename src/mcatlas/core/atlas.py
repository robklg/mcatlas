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
from mcatlas.core.model import GameMode, WorldFormat, WorldId
from mcatlas.core.render import RenderedMap

SCHEMA_VERSION: Final = 1
"""Version of facts.toml and worlds.csv; bump on any incompatible change."""
WORLDS_DIR: Final = "worlds"
NOTES_DIR: Final = "annotations"
"""The notes folder next to the export; the export never writes there."""

_MONTHS: Final = (
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
)  # fmt: skip
_MODES: Final = {
    GameMode.SURVIVAL: "Overleven",
    GameMode.CREATIVE: "Creatief",
    GameMode.ADVENTURE: "Avontuur",
    GameMode.SPECTATOR: "Toeschouwer",
}
_GENERATORS: Final = {
    "default": "Normaal",
    "flat": "Superflat",
    "void": "Leeg (void)",
    "amplified": "Amplified",
    "large_biomes": "Grote biomen",
    "single_biome": "Eén bioom",
    "debug": "Debug",
    "custom": "Aangepast",
    "unknown": "Onbekend",
}
_FORMATS: Final = {
    WorldFormat.MCREGION: "Oud formaat (Beta), niet diep geanalyseerd",
    WorldFormat.NO_TERRAIN: "Geen terrein",
    WorldFormat.NO_LEVEL_DAT: "Geen level.dat",
    WorldFormat.EMPTY: "Lege map",
}
_DIMENSIONS: Final = {
    "minecraft:overworld": "Bovenwereld",
    "minecraft:the_nether": "Nether",
    "minecraft:the_end": "End",
}
_IMPORTANCE: Final = {
    "days": "dagen",
    "weeks": "weken",
    "play_hours": "speeltijd",
    "items_used": "items",
    "chunks": "gebied",
    "built": "gebouwd",
}
_TEXT_KINDS: Final = {
    "sign": "Bordjes",
    "book": "Boeken",
    "name": "Namen",
    "command": "Commando's",
}


@dataclass(frozen=True, slots=True)
class AtlasChanges:
    location: str
    written: int
    unchanged: int
    removed: int
    """Files of an earlier export that are no longer part of it."""


# ---------- formatting ----------


def _num(n: float, decimals: int = 0) -> str:
    """Dutch notation: 1.234,5."""
    text = f"{n:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _day(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _hours(h: float) -> str:
    if h <= 0:
        return "–"
    if h < 1:
        return f"{round(h * 60)} min"
    return f"{_num(h, 1 if h < 10 else 0)} uur"


def _count(n: int, one: str, many: str) -> str:
    return f"{_num(n)} {one if n == 1 else many}"


def _period(e: WorldEntry) -> str:
    a = e.activity
    if a.first_day is None or a.last_day is None:
        return "–"
    if a.first_day == a.last_day:
        return _day(a.first_day)
    return f"{_day(a.first_day)} – {_day(a.last_day)}"


def _days(e: WorldEntry) -> str:
    low = e.activity.distinct_days
    if e.days_upper is not None and e.days_upper > low:
        return f"{_num(low)}–{_num(e.days_upper)}"
    return _num(low)


def _dimension(key: str) -> str:
    return _DIMENSIONS.get(key, key)


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
    return "spawn.png" if site is None else f"plek-{site + 1}.png"


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


def index_document(catalog: Catalog, generated: date) -> Document:
    rows: list[Sequence[Text]] = []
    for n, e in enumerate(catalog.worlds, 1):
        b = e.build
        rows.append(
            [
                str(n),
                page(e.name, world_dir(e.world_id)),
                _period(e),
                _days(e),
                _hours(e.play_hours),
                _num(b.built) if b else "–",
                f"{_num(b.pct_below, 0)}%" if b and b.pct_below is not None else "–",
                _players_line(e),
                _note_line(e.annotation),
            ]
        )
    present = {e.world_id for e in catalog.worlds}
    orphans = sorted(
        (a for w, a in catalog.annotations.items() if w not in present), key=lambda a: a.world
    )
    period = (
        f"Gespeeld tussen {_day(catalog.first_day)} en {_day(catalog.last_day)}. "
        if catalog.first_day and catalog.last_day
        else ""
    )
    blocks: list[Block] = [
        Paragraph(
            [
                f"{_count(len(catalog.worlds), 'wereld', 'werelden')}, van meest naar minst "
                f"gespeeld (belangrijkheid). {period}Bijgewerkt op {_day(generated)}. Uitleg: ",
                Link("README", "README.md", "README.md"),
                "; als spreadsheet: ",
                link("worlds.csv", "worlds.csv"),
                ".",
            ]
        ),
        Table(
            [
                "#",
                "Wereld",
                "Periode",
                "Dagen",
                "Speeltijd",
                "Gebouwd",
                "Ondergronds",
                "Spelers",
                "Notitie",
            ],
            rows,
            numeric=(0, 3, 4, 5, 6),
        ),
    ]
    if orphans:
        blocks += [
            Heading(2, "Notities zonder wereld"),
            Paragraph(
                f"Deze notities in {NOTES_DIR}/ horen bij werelden die niet meer in het "
                "archief staan:"
            ),
            Items([[Code(a.world), f" {a.folder} {a.title}".rstrip()] for a in orphans]),
        ]
    return Document("Minecraft-werelden", blocks)


def _play_rows(e: WorldEntry) -> list[tuple[str, Text]]:
    a, b = e.activity, e.build
    rows: list[tuple[str, Text]] = []
    if e.format is not WorldFormat.ANVIL:
        rows.append(("Soort", _FORMATS.get(e.format, e.format.value)))
    rows.append(
        (
            "Periode",
            _period(e) + (f" ({_count(a.span_days, 'dag', 'dagen')})" if a.span_days > 1 else ""),
        )
    )
    rows.append(
        (
            "Actieve dagen",
            _days(e)
            + (f" in {_count(a.active_months, 'maand', 'maanden')}" if a.active_months > 1 else ""),
        )
    )
    play = _hours(e.play_hours)
    if e.foreign_players:
        play += f" (eigen spelers; alle spelers samen {_hours(e.play_hours_all)})"
    if e.sessions:
        play += f", {_count(e.sessions, 'sessie', 'sessies')}"
    if e.afk_suspect:
        play += "; waarschijnlijk vaak aan laten staan"
    rows.append(("Speeltijd", play))
    if e.items_used:
        rows.append(("Items gebruikt", f"{_num(e.items_used)} (inclusief elk geplaatst blok)"))
    if b is not None:
        built = _count(b.built, "blok", "blokken")
        if b.pct_below is not None:
            built += f", {_num(b.pct_below, 0)}% onder de grond"
        rows.append(("Gebouwd", built))
        if b.history_built:
            rows.append(
                ("Van de makers", f"{_num(b.history_built)} blokken (van vóór onze spelers)")
            )
    return rows


def _world_rows(e: WorldEntry) -> list[tuple[str, Text]]:
    rows: list[tuple[str, Text]] = []
    rows.append(
        (
            "Verkend",
            f"{_num(e.chunks)} chunks"
            + (" in " + ", ".join(_dimension(d.key) for d in e.dimensions) if e.dimensions else ""),
        )
    )
    if e.version_name:
        rows.append(("Versie", e.version_name))
    if e.game_mode is not None:
        mode = _MODES[e.game_mode] + (", hardcore" if e.hardcore else "")
        rows.append(("Spelmodus", mode + (", cheats aan" if e.cheats else "")))
    generator = _GENERATORS.get(e.generator.value, e.generator.value)
    if e.generator_detail:
        generator += f" ({e.generator_detail})"
    rows.append(("Wereldtype", generator))
    if e.modded:
        rows.append(("Mods", "ja"))
    if e.datapacks:
        rows.append(("Datapacks", ", ".join(e.datapacks)))
    if e.seed is not None:
        rows.append(("Seed", Code(str(e.seed))))
    if e.spawn is not None:
        rows.append(("Spawn", Code(" ".join(str(c) for c in e.spawn))))
    if e.last_played is not None:
        rows.append(("Laatst geopend", _day(e.last_played.date())))
    rows.append(
        (
            "Grootte",
            f"{_num(e.size_bytes / 1_048_576, 1)} MB in {_count(e.files, 'bestand', 'bestanden')}",
        )
    )
    parts = ", ".join(
        f"{_IMPORTANCE.get(k, k)} {_num(v, 1)}" for k, v in e.importance.components.items() if v
    )
    rows.append(
        ("Belangrijkheid", f"{_num(e.importance.score, 1)}" + (f" ({parts})" if parts else ""))
    )
    return rows


def _players(e: WorldEntry) -> list[Block]:
    shown = [p for p in e.players if p.play_hours > 0 or p.known]
    if not shown:
        return []
    rows: list[Sequence[Text]] = []
    for p in sorted(shown, key=lambda p: -p.play_hours):
        where = ""
        if p.position is not None:
            x, y, z = (round(c) for c in p.position)
            where = f"{_dimension(p.dimension or '')} {x} {y} {z}".strip()
        rows.append(
            [
                p.name or Code(p.uuid),
                _hours(p.play_hours),
                _num(p.sessions) if p.sessions is not None else "–",
                _num(p.items_used),
                _num(p.advancements),
                _MODES[p.game_mode] if p.game_mode is not None else "",
                where,
            ]
        )
    return [
        Heading(2, "Spelers"),
        Table(
            ["Speler", "Speeltijd", "Sessies", "Items", "Advancements", "Modus", "Laatste positie"],
            rows,
            numeric=(1, 2, 3, 4),
        ),
    ]


def _sites(e: WorldEntry, images: Mapping[int | None, str]) -> list[Block]:
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
                    _dimension(s.dimension),
                    Code(f"{s.x} {s.z}"),
                    f"{s.bbox[2] - s.bbox[0] + 1} × {s.bbox[3] - s.bbox[1] + 1}",
                    f"{s.min_y} tot {s.max_y}",
                    _num(s.built),
                    f"{_num(s.pct_below, 0)}%" if s.pct_below is not None else "–",
                    _hours(s.hours_nearby),
                    Code(_tp(s)),
                ]
            )
        blocks += [
            Heading(2, "Bouwplekken"),
            Paragraph(
                "Plekken waar gebouwd is, groot naar klein. Midden = x en z in blokken; de "
                "teleport-opdracht werkt in een kopie van de wereld met cheats aan."
            ),
            Table(
                [
                    "#",
                    "Dimensie",
                    "Midden",
                    "Gebied",
                    "Hoogte",
                    "Blokken",
                    "Ondergronds",
                    "In de buurt",
                    "Teleport",
                ],
                rows,
                numeric=(0, 5, 6, 7),
            ),
        ]
    for i, s in enumerate(b.sites):
        if i in images:
            blocks.append(
                Image(
                    image_name(i),
                    f"Plek {i + 1} van bovenaf",
                    f"Plek {i + 1} ({_dimension(s.dimension)}, rond {s.x} {s.z}) van bovenaf, "
                    "noorden boven.",
                )
            )
    if None in images:
        spawn = f" rond {e.spawn[0]} {e.spawn[2]}" if e.spawn else ""
        blocks.append(
            Image(image_name(None), "Spawn van bovenaf", f"Het gebied{spawn} van bovenaf.")
        )
    if b.top_blocks:
        blocks += [
            Heading(2, "Meest gebouwde blokken"),
            Table(
                ["Blok", "Aantal"],
                [[_block(name), _num(n)] for name, n in b.top_blocks],
                numeric=(1,),
            ),
        ]
    return blocks


def _timeline(e: WorldEntry) -> list[Block]:
    def months(days: Sequence[date]) -> list[Text]:
        by_month: dict[tuple[int, int], list[int]] = {}
        for d in sorted(days):
            by_month.setdefault((d.year, d.month), []).append(d.day)
        return [
            f"{_MONTHS[m - 1]} {y}: {', '.join(str(d) for d in ds)} "
            f"({_count(len(ds), 'dag', 'dagen')})"
            for (y, m), ds in by_month.items()
        ]

    blocks: list[Block] = []
    if e.activity.days:
        blocks += [
            Heading(2, "Tijdlijn"),
            Paragraph(
                "Dagen met bewijs dat er gespeeld is (opgeslagen chunks, advancements, "
                "bestanden). Het echte aantal ligt hoger: van elk stukje wereld onthoudt "
                "Minecraft alleen de laatste keer opslaan."
            ),
            Items(months(list(e.activity.days))),
        ]
    if e.activity.history:
        blocks += [
            Heading(3, "Voorgeschiedenis"),
            Paragraph(
                "Activiteit van vóór onze spelers, bijvoorbeeld van de makers van een "
                "gedownloade map:"
            ),
            Items(months(list(e.activity.history))),
        ]
    return blocks


def _note(note: Annotation | None) -> list[Block]:
    if note is None or note.is_empty:
        return []
    blocks: list[Block] = [Heading(2, "Onze notitie")]
    line = _note_line(note)
    if line:
        blocks.append(Paragraph(line))
    if note.note.strip():
        blocks.append(Markdown(note.note))
    blocks.append(
        Paragraph(f"(Uit {NOTES_DIR}/, waar de notities zelf staan en bewerkt kunnen worden.)")
    )
    return blocks


def _texts_line(e: WorldEntry) -> list[Block]:
    if not e.text_counts:
        return []
    counts = ", ".join(
        f"{_TEXT_KINDS.get(k, k).lower()} {_num(n)}" for k, n in sorted(e.text_counts.items())
    )
    return [
        Heading(2, "Teksten"),
        Paragraph(
            [
                f"Gevonden: {counts}. Alles staat in ",
                page("teksten", "", md="teksten.md", html="teksten.html"),
                ".",
            ]
        ),
    ]


def _related(e: WorldEntry) -> list[Block]:
    if not e.related:
        return []
    return [
        Heading(2, "Verwante werelden"),
        Paragraph(
            "Werelden met deels dezelfde geschiedenis (kopieën van elkaar of van dezelfde "
            "oorsprong):"
        ),
        Items(
            [
                [
                    page(r.folder_name, f"../{r.world_id}/"),
                    f" ({_num(100 * r.similarity, 0)}% overeenkomst)",
                ]
                for r in e.related
            ]
        ),
    ]


def world_document(e: WorldEntry, images: Mapping[int | None, str], *, has_icon: bool) -> Document:
    where: list[Inline] = ["Map in het archief: ", Code(e.relpath)]
    if e.folder_name != e.name:
        where = [*where, f" (mapnaam {e.folder_name})"]
    blocks: list[Block] = [
        Paragraph(
            [
                page("← alle werelden", "../../", md="index.md"),
                " · ",
                link("feiten (facts.toml)", "facts.toml"),
            ]
        ),
        Paragraph(where),
    ]
    if has_icon:
        blocks.append(Image("icon.png", "Plaatje van de wereld"))
    blocks += _note(e.annotation)
    blocks += [
        Heading(2, "Samenvatting"),
        Table(["", ""], [list(r) for r in _play_rows(e) + _world_rows(e)]),
    ]
    blocks += _sites(e, images)
    blocks += _players(e)
    blocks += _timeline(e)
    blocks += _texts_line(e)
    blocks += _related(e)
    if e.errors:
        blocks += [Heading(2, "Meldingen bij het analyseren"), Items(e.errors)]
    return Document(e.name, blocks)


def _where(t: TextEntry) -> Text:
    if t.x is None or t.y is None or t.z is None:
        return ""
    dim = (
        f"{_dimension(t.dimension)} "
        if t.dimension and t.dimension != "minecraft:overworld"
        else ""
    )
    return [dim, Code(f"{t.x} {t.y} {t.z}")]


def texts_document(e: WorldEntry, texts: Sequence[TextEntry]) -> Document:
    blocks: list[Block] = [
        Paragraph([page(f"← {e.name}", "", md="README.md", html="index.html")]),
        Paragraph(
            "Teksten die spelers in de wereld hebben achtergelaten: op bordjes, in boeken, als "
            "naam van dieren en spullen, en in command blocks."
        ),
    ]
    for history in (False, True):
        group = [t for t in texts if t.history == history]
        if not group:
            continue
        if history:
            blocks += [
                Heading(2, "Van vóór onze spelers"),
                Paragraph(
                    "Deze teksten staan in stukken wereld die al zo waren toen onze "
                    "spelers begonnen (bijvoorbeeld van de makers van een map)."
                ),
            ]
        level = 3 if history else 2
        for kind, label in _TEXT_KINDS.items():
            of_kind = [t for t in group if t.kind == kind]
            if not of_kind:
                continue
            blocks.append(Heading(level, f"{label} ({_num(len(of_kind))})"))
            if kind == "book":
                for t in of_kind:
                    blocks += [Paragraph([f"In {t.holder} ", *_as_list(_where(t))]), Pre(t.text)]
            else:
                blocks.append(
                    Table(
                        ["Tekst", "Op of in", "Plaats"],
                        [
                            [Code(t.text) if kind == "command" else t.text, t.holder, _where(t)]
                            for t in of_kind
                        ],
                    )
                )
    return Document(f"Teksten in {e.name}", blocks)


def _as_list(text: Text) -> list[Inline]:
    return [text] if isinstance(text, str | Link | Code) else list(text)


README: Final = """\
Dit is een overzicht van een archief met Minecraft-werelden (bij elke wereld staat in welke
map van het archief hij zit). Het is gemaakt door *mcatlas*, een programma dat de werelden alleen
leest (nooit wijzigt) en uitzoekt wanneer, hoe lang, door wie en wat er in elke wereld gebouwd is.

Alles hier bestaat uit gewone bestanden die je zonder mcatlas kunt openen, ook over twintig jaar:

- **index.html** (in een webbrowser) of **index.md** (als tekst): alle werelden in een tabel,
  van meest naar minst gespeeld.
- **worlds.csv**: dezelfde tabel voor een spreadsheet (UTF-8, komma-gescheiden).
- `worlds/<wereld>/`: per wereld een map met
  - `index.html` / `README.md`: alles wat over de wereld bekend is,
  - `facts.toml`: dezelfde feiten machineleesbaar (uitleg per veld in
    `schema/world.schema.json`),
  - `teksten.html` / `teksten.md`: bordjes, boeken, namen en commando's uit de wereld,
  - `plek-1.png`, `plek-2.png`, ...: de bouwplekken van bovenaf (noorden boven, 1 pixel is
    1 of meer blokken), `icon.png`: het plaatje van de wereld uit het Minecraft-menu.
- **annotations/**: onze eigen notities per wereld (Markdown). mcatlas overschrijft die nooit;
  de pagina's hier citeren ze alleen.

## Hoe je de getallen leest

- **Actieve dagen**: dagen waarop aantoonbaar gespeeld is. Minecraft onthoudt van elk stukje
  wereld alleen de laatste keer opslaan, dus dit is een ondergrens. Het getal erachter (bijv.
  `8–15`) is een bovengrens: het aantal keer dat het spel is afgesloten.
- **Speeltijd**: uit de statistieken van de spelers zelf; "eigen spelers" zijn de spelers met
  een bekende naam, anderen (vrienden, makers van een map) staan apart.
- **Gebouwd**: blokken die Minecraft zelf nooit neerzet (dus geen steen, aarde, bomen), ongeveer
  het aantal kubieke meters dat gebouwd is. Bouwen met natuurlijke blokken telt niet mee.
- **Ondergronds**: het deel van het gebouwde onder het natuurlijke maaiveld.
- **Bouwplekken**: groepjes chunks (16×16 blokken) waarin gebouwd is, met coördinaten.
- **Belangrijkheid**: één getal dat dagen, weken, speeltijd, items, gebied en bouwen optelt
  (elk logaritmisch), alleen om te sorteren.

## Bijwerken

Deze map wordt niet vanzelf bijgewerkt. Na een nieuwe notitie of nieuwe werelden in het archief
draai je mcatlas opnieuw (in de map van het mcatlas-project):

```sh
uv run mcatlas analyze --tier 2   # alleen bij nieuwe of veranderde werelden
uv run mcatlas render             # alleen bij nieuwe werelden: kaartjes van bovenaf
uv run mcatlas export-atlas       # deze map bijwerken
```

Alleen gewijzigde bestanden worden opnieuw geschreven. De map `annotations/` blijft altijd
onaangeroerd.

## Een wereld weer spelen

Kopieer de wereldmap uit het archief naar de `saves`-map van Minecraft (Java Edition) en
open de kopie. Speel nooit in het archief zelf: Minecraft verandert een wereld zodra je hem
opent.
"""


def readme_document(catalog: Catalog, generated: date, tool: str) -> str:
    head = (
        "# Minecraft-werelden: atlas\n\n"
        f"Gemaakt op {_day(generated)} door {tool}, schema-versie {SCHEMA_VERSION}, "
        f"{_count(len(catalog.worlds), 'wereld', 'werelden')}.\n\n"
    )
    return head + README


# ---------- all files ----------


def atlas_files(
    catalog: Catalog,
    *,
    icons: Mapping[WorldId, bytes],
    images: Mapping[str, bytes],
    generated: date,
    tool: str,
) -> dict[str, bytes]:
    """Every file of the atlas by relative path. `images` are flat maps by render path."""
    files: dict[str, bytes] = {
        "README.md": readme_document(catalog, generated, tool).encode(),
        "worlds.csv": worlds_csv(catalog.worlds).encode(),
        "schema/world.schema.json": world_schema().encode(),
    }
    index = index_document(catalog, generated)
    files["index.md"] = to_markdown(index).encode()
    files["index.html"] = to_html(index).encode()
    for e in catalog.worlds:
        base = world_dir(e.world_id)
        paths = {
            site: path
            for site, path in _site_images(catalog.renders.get(e.world_id, [])).items()
            if path in images
        }
        icon = icons.get(e.world_id)
        doc = world_document(e, paths, has_icon=icon is not None)
        files[base + "README.md"] = to_markdown(doc).encode()
        files[base + "index.html"] = to_html(doc).encode()
        files[base + "facts.toml"] = facts_toml(atlas_world(e, paths)).encode()
        if icon is not None:
            files[base + "icon.png"] = icon
        for site, path in paths.items():
            files[base + image_name(site)] = images[path]
        texts = catalog.texts.get(e.world_id, [])
        if texts:
            tdoc = texts_document(e, texts)
            files[base + "teksten.md"] = to_markdown(tdoc).encode()
            files[base + "teksten.html"] = to_html(tdoc).encode()
    return files
