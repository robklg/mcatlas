"""Blocks that generated structures are made of.

In a chunk that a structure touches, a built block only counts as our players' work when the
structure could not have placed it. Mineshafts touch a large share of all underground chunks
but use a handful of blocks, so they get an exact palette; every other structure uses the broad
`is_generic_structure_block` test, which hides common building blocks (planks, stairs, wool...)
in those chunks. That trade-off favours "no false buildings in villages and ancient cities"
over completeness inside them.

Dungeons (monster rooms) are features, not structures: chunks with a spawner (or next to one)
use `DUNGEON`. Chunks where players spent little time use the generic test as well, because some
upgraded worlds lost their structure references (a whole village without any).
"""

from typing import Final

from mcatlas.core.data.natural_blocks import VERSION as _NATURAL_VERSION


def _ns(*names: str) -> frozenset[str]:
    return frozenset(f"minecraft:{n}" for n in names)


VERSION: Final = _NATURAL_VERSION * 100 + 2

MINESHAFT: Final = _ns(
    "oak_planks",
    "oak_fence",
    "dark_oak_planks",
    "dark_oak_fence",
    "spawner",
    "chest",
    "rail",
    "torch",
    "wall_torch",
)

DUNGEON: Final = _ns("cobblestone", "mossy_cobblestone", "spawner", "chest")

_GENERIC_PARTS: Final = (
    "_planks",
    "_stairs",
    "_slab",
    "_fence",
    "_door",
    "_trapdoor",
    "stripped_",
    "_wood",
    "_log",
    "cobblestone",
    "cobbled_",
    "stone_brick",
    "sandstone",
    "terracotta",
    "deepslate_",
    "polished_",
    "blackstone",
    "nether_brick",
    "purpur",
    "end_stone_brick",
    "prismarine",
    "tuff",
    "copper",
    "mud_brick",
    "_wool",
    "_carpet",
    "_bed",
    "_banner",
    "candle",
    "_pane",
    "torch",
    "lantern",
    "potted_",
    "_glass",
    "_wall",
    "_button",
    "_pressure_plate",
    "_sign",
    "chiseled_",
    "cracked_",
    "mossy_",
    "infested_",
    "smooth_",
    "cut_",
    "_bars",
    "_cauldron",
    "_rail",
    "rail",
    "_skull",
    "_head",
)

_GENERIC_EXACT: Final = _ns(
    "chest",
    "trapped_chest",
    "barrel",
    "spawner",
    "trial_spawner",
    "vault",
    "ladder",
    "chain",
    "glass",
    "bookshelf",
    "chiseled_bookshelf",
    "crafting_table",
    "furnace",
    "smoker",
    "blast_furnace",
    "cartography_table",
    "fletching_table",
    "grindstone",
    "lectern",
    "loom",
    "smithing_table",
    "stonecutter",
    "cauldron",
    "brewing_stand",
    "composter",
    "bell",
    "hay_block",
    "flower_pot",
    "wheat",
    "carrots",
    "potatoes",
    "beetroots",
    "melon_stem",
    "pumpkin_stem",
    "attached_melon_stem",
    "attached_pumpkin_stem",
    "sea_lantern",
    "wet_sponge",
    "sponge",
    "gold_block",
    "end_rod",
    "tnt",
    "piston",
    "sticky_piston",
    "piston_head",
    "dispenser",
    "repeater",
    "comparator",
    "redstone_wire",
    "redstone_lamp",
    "tripwire",
    "tripwire_hook",
    "lever",
    "target",
    "end_portal_frame",
    "end_portal",
    "end_gateway",
    "dragon_egg",
    "decorated_pot",
    "heavy_core",
    "anvil",
    "chipped_anvil",
    "damaged_anvil",
    "jack_o_lantern",
    "carved_pumpkin",
    "reinforced_deepslate",
    "bone_block",
    "gilded_blackstone",
    "magma_block",
)


def is_generic_structure_block(name: str) -> bool:
    return name in _GENERIC_EXACT or any(part in name for part in _GENERIC_PARTS)


def is_structure_block(name: str, structures: tuple[str, ...]) -> bool:
    """Whether one of `structures` (names without namespace) could have placed `name`."""
    for s in structures:
        if s == "unvisited":
            if is_generic_structure_block(name):
                return True
        elif s == "dungeon":
            if name in DUNGEON:
                return True
        elif s.startswith("mineshaft"):
            if name in MINESHAFT:
                return True
        elif is_generic_structure_block(name):
            return True
    return False
