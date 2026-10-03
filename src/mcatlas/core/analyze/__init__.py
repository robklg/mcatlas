"""Analyzer registry.

An analyzer is a pure function from a world's files (read-only protocol) and its layout to a
`Facts` model. Heavy analyzers also get a `Mapper` to spread pure work over worker processes.
Its `version` is part of the cache key: bump it whenever its output changes.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from mcatlas.core.analyze.blocks import analyze_blocks
from mcatlas.core.analyze.console import analyze_console
from mcatlas.core.analyze.files import analyze_files
from mcatlas.core.analyze.level import analyze_level
from mcatlas.core.analyze.maps import analyze_maps
from mcatlas.core.analyze.players import analyze_players
from mcatlas.core.analyze.regions import analyze_regions
from mcatlas.core.data.structure_blocks import VERSION as BLOCK_LISTS_VERSION
from mcatlas.core.facts import (
    BlockFacts,
    ConsoleFacts,
    Facts,
    FileFacts,
    LevelFacts,
    MapFacts,
    PlayersFacts,
    RegionFacts,
)
from mcatlas.core.model import Mapper, WorldFiles, WorldLayout

T_co = TypeVar("T_co", bound=Facts, covariant=True)


@dataclass(frozen=True, slots=True)
class Analyzer(Generic[T_co]):  # noqa: UP046 - PEP 695 syntax cannot declare covariance
    name: str
    version: int
    tier: int
    model: type[T_co]
    run: Callable[[WorldFiles, WorldLayout, Mapper], T_co]
    applies: Callable[[WorldLayout], bool] = lambda _layout: True
    """Whether the analyzer makes sense for a layout; if not, the world is marked n/a."""

    def parse(self, payload: str) -> T_co:
        return self.model.model_validate_json(payload)


def _simple[T: Facts](
    fn: Callable[[WorldFiles, WorldLayout], T],
) -> Callable[[WorldFiles, WorldLayout, Mapper], T]:
    return lambda files, layout, _mapper: fn(files, layout)


def _has_anvil_regions(layout: WorldLayout) -> bool:
    """Chunks to read, whether or not a level.dat came along."""
    return any(f.relpath.endswith(".mca") for d in layout.dimensions for f in d.region_files)


LEVEL = Analyzer(
    "level",
    1,
    1,
    LevelFacts,
    _simple(analyze_level),
    lambda lay: lay.level_dat is not None or bool(lay.level_data),
)
PLAYERS = Analyzer("players", 1, 1, PlayersFacts, _simple(analyze_players))
REGIONS = Analyzer(
    "regions", 2, 1, RegionFacts, _simple(analyze_regions), lambda lay: bool(lay.dimensions)
)
FILES = Analyzer("files", 3, 1, FileFacts, _simple(analyze_files))
MAPS = Analyzer("maps", 3, 1, MapFacts, _simple(analyze_maps))
"""In-game maps; their images are stored as assets named `maps/<image>`."""
BLOCKS = Analyzer(
    "blocks",
    BLOCK_LISTS_VERSION * 100 + 4,
    2,
    BlockFacts,
    analyze_blocks,
    _has_anvil_regions,
)
"""Version combines the block lists' version with the analyzer's own."""

CONSOLE = Analyzer(
    "console",
    3,
    1,
    ConsoleFacts,
    _simple(analyze_console),
    lambda lay: lay.console_metadata is not None,
)
"""Dates, play time and players of a world converted from a console save."""

ALL: tuple[Analyzer[Facts], ...] = (LEVEL, PLAYERS, REGIONS, FILES, MAPS, BLOCKS, CONSOLE)
BY_NAME: dict[str, Analyzer[Facts]] = {a.name: a for a in ALL}


def cache_key(analyzer: Analyzer[Facts], layout: WorldLayout, fingerprint: str) -> str:
    """The fingerprint to cache a result under. "Not applicable" gets its own key, so a world
    is analyzed as soon as a newer mcatlas finds that the analyzer does apply to it."""
    return fingerprint if analyzer.applies(layout) else f"{fingerprint}/n-a"


def for_tier(tier: int) -> list[Analyzer[Facts]]:
    return [a for a in ALL if a.tier <= tier]
