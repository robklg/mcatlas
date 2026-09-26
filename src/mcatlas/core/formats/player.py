"""Player NBT (playerdata/<uuid>.dat and the host player embedded in level.dat)."""

from mcatlas.core.facts import PlayerState
from mcatlas.core.formats.access import floats, int_, list_, str_, uuid_from
from mcatlas.core.model import GameMode
from mcatlas.core.nbt import NbtCompound

_LEGACY_DIMENSIONS = {0: "minecraft:overworld", -1: "minecraft:the_nether", 1: "minecraft:the_end"}


def game_mode(value: int | None) -> GameMode | None:
    return GameMode(value) if value is not None and value in {m.value for m in GameMode} else None


def parse_player_state(c: NbtCompound) -> PlayerState:
    pos = floats(list_(c, "Pos"))
    dimension = str_(c, "Dimension")
    if dimension is None and (legacy := int_(c, "Dimension")) is not None:
        dimension = _LEGACY_DIMENSIONS.get(legacy, f"legacy:dim{legacy}")
    return PlayerState(
        uuid=uuid_from(c),
        position=(pos[0], pos[1], pos[2]) if len(pos) == 3 else None,
        dimension=dimension,
        game_mode=game_mode(int_(c, "playerGameType")),
        xp_level=int_(c, "XpLevel"),
    )
