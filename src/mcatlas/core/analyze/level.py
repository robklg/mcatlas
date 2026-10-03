from mcatlas.core.facts import LevelFacts
from mcatlas.core.formats.level import apply_level_data, parse_level
from mcatlas.core.model import WorldFiles, WorldLayout
from mcatlas.core.nbt import decode_file


class NoLevelFileError(LookupError):
    pass


def analyze_level(files: WorldFiles, layout: WorldLayout) -> LevelFacts:
    base = None
    if layout.level_dat is not None:
        base = parse_level(decode_file(files.read_bytes(layout.level_dat)), layout.level_dat)
        if not layout.level_data:
            return base
    elif not layout.level_data:
        raise NoLevelFileError("world has no level.dat")
    parts = {path: decode_file(files.read_bytes(path)) for path in layout.level_data}
    return apply_level_data(base, parts, layout.level_data[0])
