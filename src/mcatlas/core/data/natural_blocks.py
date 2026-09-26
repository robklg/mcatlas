"""Which blocks the world generator places on its own, split by the role they play in analysis.

Includes flowers, crops that spawn wild, Nether/End terrain, coral,
badlands terracotta and the block names of 1.13 up to 1.21.5.

Anything not listed here counts as *built*. The lists are deliberately generous towards
"natural", with two known blind spots:

* Players also build with natural blocks (stone, logs, dirt). Those builds are undercounted;
  the block histogram still shows them.
* Structures (villages, mineshafts, ...) consist of non-natural blocks. Chunks that reference a
  structure are therefore counted separately by the analysis, not in these lists.

Bump `VERSION` whenever a list changes: it is part of the blocks analyzer's cache key.
"""

from typing import Final

VERSION: Final = 1


def _ns(*names: str) -> frozenset[str]:
    return frozenset(f"minecraft:{n}" for n in names)


def _each(prefixes: tuple[str, ...], suffix: str) -> tuple[str, ...]:
    return tuple(f"{p}{suffix}" for p in prefixes)


_CORALS = ("tube", "brain", "bubble", "fire", "horn")
_DEAD_CORALS = tuple(f"dead_{c}" for c in _CORALS)
_BADLANDS = ("white", "orange", "yellow", "brown", "red", "light_gray")

AIR: Final = _ns("air", "cave_air", "void_air")

FLUID: Final = _ns("water", "lava", "bubble_column")

GROUND: Final = _ns(
    # stone family
    "stone",
    "deepslate",
    "andesite",
    "diorite",
    "granite",
    "tuff",
    "calcite",
    "smooth_basalt",
    "bedrock",
    "obsidian",
    "crying_obsidian",
    "magma_block",
    "dripstone_block",
    "infested_stone",
    "infested_deepslate",
    # soil
    "dirt",
    "coarse_dirt",
    "rooted_dirt",
    "grass_block",
    "podzol",
    "mycelium",
    "mud",
    "muddy_mangrove_roots",
    "clay",
    "gravel",
    "sand",
    "red_sand",
    "sandstone",
    "red_sandstone",
    "suspicious_sand",
    "suspicious_gravel",
    "moss_block",
    "pale_moss_block",
    "snow_block",
    "powder_snow",
    "ice",
    "packed_ice",
    "blue_ice",
    "terracotta",
    *_each(_BADLANDS, "_terracotta"),
    # ores
    "coal_ore",
    "iron_ore",
    "copper_ore",
    "gold_ore",
    "redstone_ore",
    "lapis_ore",
    "diamond_ore",
    "emerald_ore",
    "deepslate_coal_ore",
    "deepslate_iron_ore",
    "deepslate_copper_ore",
    "deepslate_gold_ore",
    "deepslate_redstone_ore",
    "deepslate_lapis_ore",
    "deepslate_diamond_ore",
    "deepslate_emerald_ore",
    "raw_iron_block",
    "raw_copper_block",
    # nether
    "netherrack",
    "soul_sand",
    "soul_soil",
    "basalt",
    "blackstone",
    "crimson_nylium",
    "warped_nylium",
    "nether_quartz_ore",
    "nether_gold_ore",
    "ancient_debris",
    "glowstone",
    # end
    "end_stone",
)

VEGETATION: Final = _ns(
    # grass and small plants ("grass" is the pre-1.20.3 name of short_grass)
    "grass",
    "short_grass",
    "tall_grass",
    "fern",
    "large_fern",
    "dead_bush",
    "bush",
    "firefly_bush",
    "short_dry_grass",
    "tall_dry_grass",
    "leaf_litter",
    "wildflowers",
    "pink_petals",
    "sweet_berry_bush",
    "sugar_cane",
    "cactus",
    "cactus_flower",
    "bamboo",
    "bamboo_sapling",
    "pumpkin",
    "melon",
    "cocoa",
    "lily_pad",
    "vine",
    "glow_lichen",
    "hanging_roots",
    "spore_blossom",
    "azalea",
    "flowering_azalea",
    "big_dripleaf",
    "big_dripleaf_stem",
    "small_dripleaf",
    "cave_vines",
    "cave_vines_plant",
    "moss_carpet",
    "pale_moss_carpet",
    "pale_hanging_moss",
    "mangrove_roots",
    "mangrove_propagule",
    "resin_clump",
    "open_eyeblossom",
    "closed_eyeblossom",
    "creaking_heart",
    "brown_mushroom",
    "red_mushroom",
    "brown_mushroom_block",
    "red_mushroom_block",
    "mushroom_stem",
    "snow",
    # flowers
    "dandelion",
    "poppy",
    "blue_orchid",
    "allium",
    "azure_bluet",
    "red_tulip",
    "orange_tulip",
    "white_tulip",
    "pink_tulip",
    "oxeye_daisy",
    "cornflower",
    "lily_of_the_valley",
    "sunflower",
    "lilac",
    "rose_bush",
    "peony",
    # trees
    *_each(
        (
            "oak",
            "birch",
            "spruce",
            "dark_oak",
            "jungle",
            "acacia",
            "mangrove",
            "cherry",
            "pale_oak",
        ),
        "_log",
    ),
    *_each(
        (
            "oak",
            "birch",
            "spruce",
            "dark_oak",
            "jungle",
            "acacia",
            "mangrove",
            "cherry",
            "pale_oak",
            "azalea",
            "flowering_azalea",
        ),
        "_leaves",
    ),
    # water plants and reefs
    "seagrass",
    "tall_seagrass",
    "kelp",
    "kelp_plant",
    "sea_pickle",
    *_each(_CORALS + _DEAD_CORALS, "_coral_block"),
    *_each(_CORALS + _DEAD_CORALS, "_coral"),
    *_each(_CORALS + _DEAD_CORALS, "_coral_fan"),
    *_each(_CORALS + _DEAD_CORALS, "_coral_wall_fan"),
    # caves
    "cobweb",
    "pointed_dripstone",
    "amethyst_block",
    "budding_amethyst",
    "amethyst_cluster",
    "small_amethyst_bud",
    "medium_amethyst_bud",
    "large_amethyst_bud",
    "sculk",
    "sculk_vein",
    "sculk_catalyst",
    "sculk_sensor",
    "sculk_shrieker",
    # nether and end growth
    "crimson_stem",
    "warped_stem",
    "nether_wart_block",
    "warped_wart_block",
    "shroomlight",
    "crimson_fungus",
    "warped_fungus",
    "crimson_roots",
    "warped_roots",
    "nether_sprouts",
    "weeping_vines",
    "weeping_vines_plant",
    "twisting_vines",
    "twisting_vines_plant",
    "fire",
    "soul_fire",
    "chorus_plant",
    "chorus_flower",
    # fossils, taiga boulders and the End's exit portal
    "bone_block",
    "mossy_cobblestone",
    "end_portal",
    "end_gateway",
    "dragon_egg",
)

SEAM: Final = _ns(
    "dirt_path",
    "farmland",
    "rail",
    "powered_rail",
    "detector_rail",
    "activator_rail",
)
"""Traces of players (or villagers) that are not building mass: paths, fields, rails."""

NATURAL: Final = AIR | FLUID | GROUND | VEGETATION
