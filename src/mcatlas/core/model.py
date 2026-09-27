"""Core domain types shared by analyzers, ports and adapters."""

import hashlib
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Literal, NewType, Protocol

type Language = Literal["en", "nl"]
"""Language of everything people read: the site's default, the atlas, the 3D map markers."""

WorldId = NewType("WorldId", str)
"""Stable, URL- and BlueMap-safe identifier: `<slug>-<6 hex>` derived from source + path."""

DimensionKey = NewType("DimensionKey", str)
"""Namespaced dimension key such as `minecraft:overworld` or `legacy:dim597088138`."""

OVERWORLD = DimensionKey("minecraft:overworld")
NETHER = DimensionKey("minecraft:the_nether")
THE_END = DimensionKey("minecraft:the_end")


class WorldFormat(StrEnum):
    ANVIL = "anvil"
    """Region files in the Anvil format (.mca), Java 1.2+."""
    MCREGION = "mcregion"
    """Only McRegion (.mcr) files: Beta 1.3 – 1.1."""
    NO_TERRAIN = "no_terrain"
    """Has a level.dat but no region files (e.g. a console-edition export or an empty world)."""
    NO_LEVEL_DAT = "no_level_dat"
    """Has region files but no level.dat."""
    EMPTY = "empty"
    """A folder without any recognizable world data."""


class GameMode(IntEnum):
    SURVIVAL = 0
    CREATIVE = 1
    ADVENTURE = 2
    SPECTATOR = 3


class Generator(StrEnum):
    DEFAULT = "default"
    FLAT = "flat"
    VOID = "void"
    AMPLIFIED = "amplified"
    LARGE_BIOMES = "large_biomes"
    SINGLE_BIOME = "single_biome"
    DEBUG = "debug"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One file inside a world, as listed by a read-only source adapter."""

    relpath: str
    """POSIX path relative to the world root, NFC-normalized."""
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class WorldListing:
    """A world (or unrecognized folder) found in a source, with its complete file listing."""

    source_id: str
    relpath: str
    """POSIX path of the world root relative to the source root (zip members use `a.zip!/dir`)."""
    files: tuple[SourceFile, ...]

    @property
    def folder_name(self) -> str:
        return leaf_name(self.relpath)

    @property
    def world_id(self) -> WorldId:
        return make_world_id(self.source_id, self.relpath)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def fingerprint(self) -> str:
        """Content-independent change detector over (path, size, mtime) of every file."""
        h = hashlib.blake2b(digest_size=16)
        for f in sorted(self.files, key=lambda f: f.relpath):
            h.update(f"{f.relpath}\0{f.size}\0{f.mtime_ns}\n".encode())
        return h.hexdigest()


class WorldFiles(Protocol):
    """Read-only access to the bytes of one world. Implemented by the source adapters."""

    @property
    def listing(self) -> WorldListing: ...

    def read_bytes(self, relpath: str) -> bytes: ...

    def read_range(self, relpath: str, offset: int, length: int) -> bytes: ...

    def read_ranges(self, requests: Sequence[tuple[str, int, int]]) -> list[bytes | OSError]:
        """Read many (relpath, offset, length) ranges; adapters may do this concurrently."""
        ...


class Mapper(Protocol):
    """Applies a pure, picklable function to items, possibly in worker processes, in order."""

    def __call__[A, B](self, fn: Callable[[A], B], items: Iterable[A], /) -> Iterator[B]: ...


def serial_map[A, B](fn: Callable[[A], B], items: Iterable[A], /) -> Iterator[B]:
    return (fn(item) for item in items)


@dataclass(frozen=True, slots=True)
class DimensionLayout:
    key: DimensionKey
    region_dir: str
    """Directory holding r.X.Z.mca/.mcr files, relative to the world root."""
    region_files: tuple[SourceFile, ...] = field(default=())
    entity_files: tuple[SourceFile, ...] = field(default=())
    """entities/r.X.Z.mca next to the region dir (1.17+): mobs, item frames, minecarts."""


@dataclass(frozen=True, slots=True)
class WorldLayout:
    format: WorldFormat
    level_dat: str | None
    """Relative path of the level file that was found (level.dat, special_level.dat, ...)."""
    dimensions: tuple[DimensionLayout, ...]
    player_data: tuple[SourceFile, ...]
    stats: tuple[SourceFile, ...]
    advancements: tuple[SourceFile, ...]
    icon: str | None
    converted_from_mcregion: bool


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FORMATTING_CODE = re.compile(r"§.")


def slugify(text: str, max_len: int = 48) -> str:
    plain = _FORMATTING_CODE.sub("", text)
    ascii_text = unicodedata.normalize("NFKD", plain).encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", ascii_text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "world"


def leaf_name(relpath: str) -> str:
    """Last path component; for a world at the root of a zip (`a.zip!/`) the zip's name."""
    return relpath.rstrip("/").removesuffix("!").rsplit("/", 1)[-1] or relpath


def make_world_id(source_id: str, relpath: str) -> WorldId:
    """Stable id; NFC-normalized first because SMB can report names in NFD."""
    key = unicodedata.normalize("NFC", f"{source_id}\0{relpath}")
    digest = hashlib.blake2b(key.encode(), digest_size=3).hexdigest()
    return WorldId(f"{slugify(leaf_name(relpath))}-{digest}")
