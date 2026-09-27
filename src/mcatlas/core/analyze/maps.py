import zlib

from mcatlas.core.facts import InGameMap, MapFacts
from mcatlas.core.maps import MAP_FILE, Pixels, parse_map, pictures
from mcatlas.core.model import WorldFiles, WorldLayout
from mcatlas.core.nbt import decode_file


def analyze_maps(files: WorldFiles, _layout: WorldLayout) -> MapFacts:
    wanted = sorted((int(m[1]), f) for f in files.listing.files if (m := MAP_FILE.match(f.relpath)))
    if not wanted:
        return MapFacts()
    raw = files.read_ranges([(f.relpath, 0, f.size) for _, f in wanted])
    maps: list[tuple[InGameMap, Pixels]] = []
    errors: list[str] = []
    for (map_id, f), data in zip(wanted, raw, strict=True):
        try:
            if isinstance(data, OSError):
                raise data
            maps.append(parse_map(map_id, decode_file(data)))
        except (OSError, EOFError, ValueError, zlib.error) as e:
            errors.append(f"{f.relpath}: {type(e).__name__}: {e}")
    shown, mosaics, images = pictures(maps)
    return MapFacts(
        total=len(wanted),
        filled=sum(1 for m, _ in maps if m.filled),
        shown=shown,
        mosaics=mosaics,
        errors=errors,
        images=images,
    )
