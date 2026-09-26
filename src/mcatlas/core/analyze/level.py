from mcatlas.core.facts import LevelFacts
from mcatlas.core.formats.level import parse_level
from mcatlas.core.model import WorldFiles, WorldLayout
from mcatlas.core.nbt import decode_file


class NoLevelFileError(LookupError):
    pass


def analyze_level(files: WorldFiles, layout: WorldLayout) -> LevelFacts:
    if layout.level_dat is None:
        raise NoLevelFileError("world has no level.dat")
    return parse_level(decode_file(files.read_bytes(layout.level_dat)), layout.level_dat)
