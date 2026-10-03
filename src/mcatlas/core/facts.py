"""Facts produced by analyzers. These pydantic models are also the persisted JSON schema."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from mcatlas.core.model import GameMode, Generator


class Facts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlayerState(Facts):
    uuid: str | None = None
    position: tuple[float, float, float] | None = None
    dimension: str | None = None
    game_mode: GameMode | None = None
    xp_level: int | None = None


class LevelFacts(Facts):
    level_file: str
    level_name: str | None = None
    """Raw LevelName, possibly containing § formatting codes."""
    display_name: str | None = None
    version_name: str | None = None
    data_version: int | None = None
    game_mode: GameMode | None = None
    hardcore: bool | None = None
    cheats: bool | None = None
    generator: Generator = Generator.UNKNOWN
    generator_detail: str | None = None
    seed: int | None = None
    time_ticks: int | None = None
    """Total game ticks the world has been running (Data.Time)."""
    last_played: datetime | None = None
    spawn: tuple[int, int, int] | None = None
    was_modded: bool | None = None
    server_brands: list[str] = Field(default_factory=list[str])
    datapacks: list[str] = Field(default_factory=list[str])
    enabled_features: list[str] = Field(default_factory=list[str])
    host_player: PlayerState | None = None


class ConsolePlayer(Facts):
    name: str
    """Gamertag on the console."""
    uuid: str
    """UUID of the Java player file the converter wrote for this gamertag."""
    host: bool = False
    last_saved: datetime | None = None
    """When the console last wrote this player's file (corrected), if known for sure."""


class ConsoleFacts(Facts):
    """A world converted from a console edition, as described by the converter's metadata.

    The converted Java files carry the conversion date everywhere (file times, chunk saves,
    LastPlayed), so dates, play time and players come from here instead. The console's clock
    may have been wrong: dates are the converter's corrected ones, and a date that could be
    read two ways is left out, with both readings kept as candidates.
    """

    metadata_file: str
    console: str | None = None
    original_name: str | None = None
    """The world's name in the console's world list."""
    created: date | None = None
    """From the save's file name: usually when the world was created."""
    created_candidates: list[date] = Field(default_factory=list[date])
    last_saved: datetime | None = None
    """When the console last wrote the save: the last time the world was played."""
    last_saved_candidates: list[date] = Field(default_factory=list[date])
    clock_offset_days: float | None = None
    """How far the console's clock was behind at the last save (0 when it was right)."""
    play_days: dict[date, int] = Field(default_factory=dict[date, int])
    """Days on which chunks of this world were last saved, with how many chunks."""
    undated_play_days: int = 0
    """Further days with saved chunks whose date the console's clock leaves open."""
    play_ticks: int | None = None
    """World clock: it only runs while the world is loaded, so roughly the time played."""
    times_loaded: int | None = None
    bundled_map: bool = False
    """Started from a map that came with the game: clock and dates are partly its makers'."""
    players: list[ConsolePlayer] = Field(default_factory=list[ConsolePlayer])
    chunk_times: dict[str, list[tuple[int, int, int]]] = Field(
        default_factory=dict[str, list[tuple[int, int, int]]]
    )
    """Per dimension: (chunk x, chunk z, last saved as Unix time; 0 when undated)."""
    tool: str | None = None
    converted_at: datetime | None = None
    notes: list[str] = Field(default_factory=list[str])
    problems: list[str] = Field(default_factory=list[str])
    """Conversion errors (e.g. a sign whose text could not be converted)."""


class PlayerStats(Facts):
    data_version: int | None = None
    play_ticks: int = 0
    world_ticks: int | None = None
    sessions: int | None = None
    """Number of times the player left the game (≈ play sessions)."""
    deaths: int = 0
    used_total: int = 0
    """Items used, which includes every block placed (also in creative)."""
    mined_total: int = 0
    crafted_total: int = 0
    distance_cm: int = 0
    top_used: list[tuple[str, int]] = Field(default_factory=list[tuple[str, int]])
    top_mined: list[tuple[str, int]] = Field(default_factory=list[tuple[str, int]])


class PlayerFacts(Facts):
    uuid: str
    state: PlayerState | None = None
    stats: PlayerStats | None = None
    advancements_done: int = 0
    advancement_times: list[datetime] = Field(default_factory=list[datetime])


class PlayersFacts(Facts):
    players: list[PlayerFacts] = Field(default_factory=list[PlayerFacts])
    errors: list[str] = Field(default_factory=list[str])


class DimensionFacts(Facts):
    key: str
    region_files: int
    empty_region_files: int
    chunks: int
    bbox_chunks: tuple[int, int, int, int] | None = None
    """(min_x, min_z, max_x, max_z) in chunk coordinates."""
    chunk_saves_by_hour: dict[int, int] = Field(default_factory=dict[int, int])
    """Unix hour -> number of chunks whose last save falls in that hour."""
    footprint: dict[str, str] = Field(default_factory=dict[str, str])
    """Region "x,z" -> which of its 32 × 32 chunks exist: slot x + 32 z, one bit each
    (numpy.packbits order), base64. All land ever generated, explored or not built on."""


class RegionFacts(Facts):
    dimensions: list[DimensionFacts] = Field(default_factory=list[DimensionFacts])
    minhash: list[int] = Field(default_factory=list[int])
    """MinHash signature over (dimension, chunk, save time); similar = shared history."""
    errors: list[str] = Field(default_factory=list[str])


class FileFacts(Facts):
    files: int
    total_size: int
    game_file_saves_by_hour: dict[int, int] = Field(default_factory=dict[int, int])
    """Unix hour -> number of game files (level/region/player data) last modified then."""
    has_icon: bool = False
    map_items: int = 0
    """Number of in-game map items (data/map_*.dat)."""


class ChunkTable(Facts):
    """Per-chunk build data, column-oriented to keep the stored JSON small.

    Holds chunks with any building, seams, structure blocks or at least a minute of player
    presence. All columns have the same length.
    """

    x: list[int] = Field(default_factory=list[int])
    z: list[int] = Field(default_factory=list[int])
    built: list[int] = Field(default_factory=list[int])
    below: list[int] = Field(default_factory=list[int])
    no_ground: list[int] = Field(default_factory=list[int])
    seam: list[int] = Field(default_factory=list[int])
    structure_built: list[int] = Field(default_factory=list[int])
    min_y: list[int] = Field(default_factory=list[int])
    max_y: list[int] = Field(default_factory=list[int])
    inhabited: list[int] = Field(default_factory=list[int])
    """Ticks players spent near the chunk (InhabitedTime; 20 ticks = 1 second)."""
    saved: list[int] = Field(default_factory=list[int])
    """Unix time of the chunk's last save."""


class DimensionBlocks(Facts):
    key: str
    chunks_full: int = 0
    chunks_partial: int = 0
    """Proto-chunks at the edge of explored land; skipped."""
    chunks_external: int = 0
    """Oversized chunks stored in separate .mcc files; skipped."""
    chunks_failed: int = 0
    built: int = 0
    """Non-natural blocks not attributed to structures: our players' building (estimate)."""
    below: int = 0
    """Built blocks under the smoothed natural surface."""
    no_ground: int = 0
    """Built blocks in columns without natural ground (void, sky islands)."""
    seam: int = 0
    structure_built: int = 0
    built_by_section: dict[int, int] = Field(default_factory=dict[int, int])
    """Section (block y // 16) -> built blocks."""
    blocks: dict[str, int] = Field(default_factory=dict[str, int])
    """Built block name -> count."""
    structure_blocks: dict[str, int] = Field(default_factory=dict[str, int])
    modded: int = 0
    """Blocks from other namespaces (mods); neither natural nor built as far as we can tell."""
    modded_blocks: dict[str, int] = Field(default_factory=dict[str, int])
    structures: dict[str, int] = Field(default_factory=dict[str, int])
    """Structure name (or "dungeon") -> chunks it touches."""
    table: ChunkTable = Field(default_factory=ChunkTable)


class TextEntry(Facts):
    """A text found in the world: sign, book, name or command."""

    kind: str
    text: str
    holder: str
    """What holds it: chest, oak_sign, wolf, player, ..."""
    dimension: str | None = None
    x: int | None = None
    y: int | None = None
    z: int | None = None
    history: bool = False
    """In a chunk last saved before our players arrived: probably the makers' text."""


class BlockFacts(Facts):
    dimensions: list[DimensionBlocks] = Field(default_factory=list[DimensionBlocks])
    texts: list[TextEntry] = Field(default_factory=list[TextEntry])
    """Signs, books, names and commands in chunks, entities and player inventories."""
    errors: list[str] = Field(default_factory=list[str])


class ImageFacts(Facts):
    """Facts that come with images (PNG by name). The images are stored next to the facts, not
    in their JSON; an analyzer's images replace all its earlier images of the world."""

    images: dict[str, bytes] = Field(default_factory=dict[str, bytes], exclude=True)


class InGameMap(Facts):
    id: int
    """The number in data/map_<id>.dat, also shown on the map item in the game."""
    scale: int
    """0-4: one map pixel is 2^scale blocks."""
    dimension: str
    x: int
    """Centre of the map in blocks."""
    z: int
    locked: bool = False
    filled: int
    """Pixels with colour, of 128 × 128."""
    image: str | None = None


class MapMosaic(Facts):
    dimension: str
    image: str
    box: tuple[int, int, int, int]
    """Blocks covered: min_x, min_z, max_x, max_z."""
    blocks_per_pixel: int
    maps: int


class MapFacts(ImageFacts):
    total: int = 0
    filled: int = 0
    """Maps with at least one coloured pixel (the rest were never used)."""
    shown: list[InGameMap] = Field(default_factory=list[InGameMap])
    mosaics: list[MapMosaic] = Field(default_factory=list[MapMosaic])
    errors: list[str] = Field(default_factory=list[str])
