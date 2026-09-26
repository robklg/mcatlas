"""File-level facts from the listing alone: size, icon, in-game maps and save times.

Only game files count towards save times; Finder litter such as .DS_Store would otherwise
show up as "activity".
"""

import re
from collections import Counter

from mcatlas.core.discovery import parse_region_name
from mcatlas.core.facts import FileFacts
from mcatlas.core.model import SourceFile, WorldFiles, WorldLayout

_MAP_ITEM = re.compile(r"(^|/)data/map_\d+\.dat$")
_PLAYER_DIRS = ("playerdata/", "stats/", "advancements/", "players/")


def is_game_file(f: SourceFile) -> bool:
    name = f.relpath.rsplit("/", 1)[-1]
    if name.startswith(("level.dat", "special_level.dat")):
        return True
    if parse_region_name(name):
        return True
    if f.relpath.startswith(_PLAYER_DIRS) or "/players/" in f.relpath:
        return True
    return "data/" in f.relpath and name.endswith(".dat")


def analyze_files(files: WorldFiles, layout: WorldLayout) -> FileFacts:
    listing = files.listing
    hours = Counter(f.mtime_ns // 3_600_000_000_000 for f in listing.files if is_game_file(f))
    return FileFacts(
        files=len(listing.files),
        total_size=listing.total_size,
        game_file_saves_by_hour=dict(sorted(hours.items())),
        has_icon=layout.icon is not None,
        map_items=sum(1 for f in listing.files if _MAP_ITEM.search(f.relpath)),
    )
