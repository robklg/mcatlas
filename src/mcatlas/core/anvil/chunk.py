"""Chunk payloads inside a region file, and the block sections inside a chunk.

Two chunk layouts are supported:

* 1.18+ (DataVersion >= 2844): root compound with `sections[].block_states{palette, data}`.
* 1.13-1.17: everything under `Level`, with `Sections[].Palette` and `BlockStates`.

Older numeric-id chunks (before 1.13) are reported as unsupported.

Block indices are bit-packed into longs, index = (y * 16 + z) * 16 + x. From DataVersion 2527
(20w17a) an index never spans two longs (each long holds 64 // bits entries, high bits unused);
before that the longs form one continuous bit stream.
"""

import gzip
import zlib
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from mcatlas.core import nbt
from mcatlas.core.anvil.region import SECTOR, RegionHeader
from mcatlas.core.formats.access import bool_, compound, compounds, int_, list_, str_
from mcatlas.core.npx import item

BLOCKS_PER_SECTION: Final = 4096
FLATTENING: Final = 1451
"""DataVersion of 17w47a: block names and palettes replaced numeric ids."""
NO_SPANNING: Final = 2527
MODERN_LAYOUT: Final = 2844
FULL_STATUSES: Final = frozenset(
    {"full", "minecraft:full", "fullchunk", "postprocessed", "minecraft:postprocessed"}
)
EXTERNAL_FLAG: Final = 0x80


class ChunkError(ValueError):
    """A chunk slot that cannot be decoded (corrupt, unsupported compression, ...)."""


@dataclass(frozen=True, slots=True)
class Section:
    y: int
    """Section index: block y = y * 16 + local y."""
    palette: tuple[str, ...]
    indices: NDArray[np.uint16] | None
    """4096 palette indices, or None when the palette has a single entry."""


@dataclass(frozen=True, slots=True)
class Chunk:
    x: int
    z: int
    data_version: int
    full: bool
    """Whether generation finished; proto-chunks at the edge of explored land are not."""
    inhabited_ticks: int
    sections: tuple[Section, ...]
    structures: tuple[str, ...]
    """Structures (village, mineshaft, ...) whose bounding box touches this chunk."""
    block_entities: tuple[nbt.NbtCompound, ...] = ()
    """Signs, chests, command blocks, ... (raw NBT, for text extraction)."""
    entities: tuple[nbt.NbtCompound, ...] = ()
    """Entities stored inside the chunk (before 1.17; later they live in entities/)."""
    legacy: bool = False
    """Upgraded from before 1.13 and not loaded since: it has no structure references."""


def chunk_bytes(region: bytes, header: RegionHeader, slot: int) -> bytes | None:
    """Decompressed NBT of one slot; None for chunks stored in an external .mcc file."""
    start = item(header.offsets, slot) * SECTOR
    if start + 5 > len(region):
        raise ChunkError("chunk offset beyond end of region file")
    length = int.from_bytes(region[start : start + 4], "big")
    kind = region[start + 4]
    if kind & EXTERNAL_FLAG:
        return None
    payload = region[start + 5 : start + 4 + length]
    try:
        match kind:
            case 1:
                return gzip.decompress(payload)
            case 2:
                return zlib.decompress(payload)
            case 3:
                return payload
            case _:
                raise ChunkError(f"unsupported chunk compression {kind}")
    except (OSError, EOFError, zlib.error) as e:
        raise ChunkError(f"corrupt chunk data: {e}") from e


def unpack(
    longs: NDArray[np.int64], bits: int, *, spanning: bool, count: int = BLOCKS_PER_SECTION
) -> NDArray[np.uint16]:
    """Unpack `count` little-end-first `bits`-wide values from Minecraft's packed long array."""
    raw = np.unpackbits(longs.astype("<i8").view(np.uint8), bitorder="little")
    if spanning:
        stream = raw[: count * bits]
    else:
        per_long = 64 // bits
        stream = raw.reshape(-1, 64)[:, : per_long * bits].reshape(-1)[: count * bits]
    if stream.size < count * bits:
        raise ChunkError("packed block data too short")
    weights = (np.uint32(1) << np.arange(bits, dtype=np.uint32)).astype(np.uint32)
    values = stream.reshape(count, bits).astype(np.uint32) @ weights
    return values.astype(np.uint16)


def _block_name(entry: nbt.NbtValue) -> str:
    """A palette entry's block: {Name, Properties}, or since 26.3 {id, properties}, a plain
    string for a block without properties, and {"": name} where a list mixes the two."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str_(entry, "Name") or str_(entry, "id") or str_(entry, "") or "minecraft:air"
    return "minecraft:air"  # keeps the indices of the other entries right


def _section(
    y: int, palette_nbt: nbt.NbtList | None, data: nbt.NbtValue | None, *, spanning: bool
) -> Section | None:
    palette = tuple(_block_name(entry) for entry in palette_nbt or [])
    if not palette:
        return None
    if len(palette) == 1:
        return Section(y, palette, None)
    if not isinstance(data, np.ndarray) or data.dtype.itemsize != 8:
        raise ChunkError(f"section {y}: palette without block data")
    bits = max(4, (len(palette) - 1).bit_length())
    indices = unpack(data.astype(np.int64), bits, spanning=spanning)
    if int(indices.max()) >= len(palette):
        raise ChunkError(f"section {y}: block index outside palette")
    return Section(y, palette, indices)


def _structures(holder: nbt.NbtCompound | None) -> tuple[str, ...]:
    if holder is None:
        return ()
    names: set[str] = set()
    for kind in ("References", "starts", "Starts"):
        for name, value in (compound(holder, kind) or {}).items():
            has_refs = isinstance(value, np.ndarray) and value.size > 0
            has_start = isinstance(value, dict) and str_(value, "id") not in {None, "INVALID"}
            if has_refs or has_start:
                names.add(name.removeprefix("minecraft:").lower())
    return tuple(sorted(names))


def parse_chunk(root: nbt.NbtCompound) -> Chunk:
    data_version = int_(root, "DataVersion") or 0
    if data_version < FLATTENING:
        raise ChunkError(f"pre-1.13 chunk format (DataVersion {data_version}) is not supported")
    modern = data_version >= MODERN_LAYOUT
    level = root if modern else compound(root, "Level")
    if level is None:
        raise ChunkError("chunk without Level compound")
    spanning = data_version < NO_SPANNING

    sections: list[Section] = []
    for sec in compounds(list_(level, "sections" if modern else "Sections")):
        y = int_(sec, "Y")
        if y is None:
            continue
        if modern:
            states = compound(sec, "block_states")
            if states is None:
                continue
            parsed = _section(y, list_(states, "palette"), states.get("data"), spanning=False)
        else:
            parsed = _section(y, list_(sec, "Palette"), sec.get("BlockStates"), spanning=spanning)
        if parsed is not None:
            sections.append(parsed)

    status = str_(level, "Status") or ""
    # A chunk upgraded from before 1.13 keeps its old TerrainPopulated flag. Set, it was fully
    # generated, whatever status the upgrade gave it: "features" until the game first lights
    # it, or "empty" while a default world still has to be extended below y=0 (1.18+).
    populated = bool_(level, "TerrainPopulated")
    return Chunk(
        x=int_(level, "xPos") or 0,
        z=int_(level, "zPos") or 0,
        data_version=data_version,
        full=status in FULL_STATUSES or populated is True,
        inhabited_ticks=int_(level, "InhabitedTime") or 0,
        sections=tuple(sorted(sections, key=lambda s: s.y)),
        structures=_structures(compound(level, "structures" if modern else "Structures")),
        block_entities=tuple(
            compounds(list_(level, "block_entities" if modern else "TileEntities"))
        ),
        entities=tuple(compounds(list_(level, "Entities"))),
        legacy=populated is not None,
    )
