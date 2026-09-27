"""Analyzer registry.

An analyzer is a pure function from a world's files (read-only protocol) and its layout to a
`Facts` model. Heavy analyzers also get a `Mapper` to spread pure work over worker processes.
Its `version` is part of the cache key: bump it whenever its output changes.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from mcatlas.core.analyze.blocks import analyze_blocks
from mcatlas.core.analyze.files import analyze_files
from mcatlas.core.analyze.level import analyze_level
from mcatlas.core.analyze.maps import analyze_maps
from mcatlas.core.analyze.players import analyze_players
from mcatlas.core.analyze.regions import analyze_regions
from mcatlas.core.data.structure_blocks import VERSION as BLOCK_LISTS_VERSION
from mcatlas.core.facts import (
    BlockFacts,
    Facts,
    FileFacts,
    LevelFacts,
    MapFacts,
    PlayersFacts,
    RegionFacts,
)
from mcatlas.core.model import Mapper, WorldFiles, WorldFormat, WorldLayout

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


LEVEL = Analyzer(
    "level", 1, 1, LevelFacts, _simple(analyze_level), lambda lay: lay.level_dat is not None
)
PLAYERS = Analyzer("players", 1, 1, PlayersFacts, _simple(analyze_players))
REGIONS = Analyzer(
    "regions", 1, 1, RegionFacts, _simple(analyze_regions), lambda lay: bool(lay.dimensions)
)
FILES = Analyzer("files", 1, 1, FileFacts, _simple(analyze_files))
MAPS = Analyzer("maps", 2, 1, MapFacts, _simple(analyze_maps))
"""In-game maps; their images are stored as assets named `maps/<image>`."""
BLOCKS = Analyzer(
    "blocks",
    BLOCK_LISTS_VERSION * 100 + 2,
    2,
    BlockFacts,
    analyze_blocks,
    lambda lay: lay.format is WorldFormat.ANVIL and bool(lay.dimensions),
)
"""Version combines the block lists' version with the analyzer's own."""

ALL: tuple[Analyzer[Facts], ...] = (LEVEL, PLAYERS, REGIONS, FILES, MAPS, BLOCKS)
BY_NAME: dict[str, Analyzer[Facts]] = {a.name: a for a in ALL}


def for_tier(tier: int) -> list[Analyzer[Facts]]:
    return [a for a in ALL if a.tier <= tier]
