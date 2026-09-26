"""Facts produced by analyzers. These pydantic models are also the persisted JSON schema."""

from datetime import datetime

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
