"""TEST-ONLY writers for NBT, region files and whole worlds.

mcatlas itself contains no NBT or region writer on purpose; these exist only to build fixtures.
"""

import gzip
import io
import json
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Byte:
    v: int


@dataclass(frozen=True)
class Short:
    v: int


@dataclass(frozen=True)
class Long:
    v: int


@dataclass(frozen=True)
class Float:
    v: float


@dataclass(frozen=True)
class TypedList:
    tag: int
    items: list


def _tag_of(value) -> int:
    match value:
        case Byte() | bool():
            return 1
        case Short():
            return 2
        case int():
            return 3
        case Long():
            return 4
        case Float():
            return 5
        case float():
            return 6
        case str():
            return 8
        case TypedList() | list():
            return 9
        case dict():
            return 10
        case np.ndarray() if value.dtype == np.int8:
            return 7
        case np.ndarray() if value.dtype == np.int32:
            return 11
        case np.ndarray() if value.dtype == np.int64:
            return 12
    raise TypeError(f"cannot encode {value!r}")


def _string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _payload(value) -> bytes:
    tag = _tag_of(value)
    match tag:
        case 1:
            return struct.pack(">b", int(value.v if isinstance(value, Byte) else value))
        case 2:
            return struct.pack(">h", value.v)
        case 3:
            return struct.pack(">i", value)
        case 4:
            return struct.pack(">q", value.v)
        case 5:
            return struct.pack(">f", value.v)
        case 6:
            return struct.pack(">d", value)
        case 8:
            return _string(value)
        case 9:
            items = value.items if isinstance(value, TypedList) else value
            item_tag = (
                value.tag if isinstance(value, TypedList) else (_tag_of(items[0]) if items else 0)
            )
            return struct.pack(">bi", item_tag, len(items)) + b"".join(_payload(i) for i in items)
        case 10:
            out = bytearray()
            for k, v in value.items():
                out += struct.pack(">b", _tag_of(v)) + _string(k) + _payload(v)
            return bytes(out) + b"\x00"
        case 7 | 11 | 12:
            dtype = {7: ">i1", 11: ">i4", 12: ">i8"}[tag]
            return struct.pack(">i", value.size) + value.astype(dtype).tobytes()
    raise AssertionError(tag)


def nbt(root: dict, name: str = "") -> bytes:
    return b"\x0a" + _string(name) + _payload(root)


def nbt_gz(root: dict) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:
        f.write(nbt(root))
    return buf.getvalue()


def region(chunks: dict[tuple[int, int], tuple[dict, int]]) -> bytes:
    """Build a region file from {(local_x, local_z): (chunk_nbt, unix_timestamp)}."""
    header = bytearray(8192)
    body = bytearray()
    sector = 2
    for (lx, lz), (chunk, ts) in sorted(chunks.items()):
        data = zlib.compress(nbt(chunk))
        payload = struct.pack(">IB", len(data) + 1, 2) + data
        payload += b"\x00" * (-len(payload) % 4096)
        count = len(payload) // 4096
        idx = lx + 32 * lz
        struct.pack_into(">I", header, idx * 4, (sector << 8) | count)
        struct.pack_into(">I", header, 4096 + idx * 4, ts)
        body += payload
        sector += count
    return bytes(header + body)


def pack(values: Sequence[int], bits: int, *, spanning: bool) -> np.ndarray:
    """Naive reference packer (the inverse of mcatlas' vectorized unpack)."""
    longs: list[int] = []
    if spanning:
        stream = 0
        for i, v in enumerate(values):
            stream |= v << (i * bits)
        total = -(-len(values) * bits // 64)
        longs = [(stream >> (64 * i)) & (2**64 - 1) for i in range(total)]
    else:
        per_long = 64 // bits
        for i, v in enumerate(values):
            if i % per_long == 0:
                longs.append(0)
            longs[-1] |= v << ((i % per_long) * bits)
    return np.array([x - 2**64 if x >= 2**63 else x for x in longs], dtype=np.int64)


def chunk_nbt(
    cx: int,
    cz: int,
    blocks: dict[tuple[int, int, int], str],
    *,
    fill: Sequence[tuple[int, int, str]] = (),
    data_version: int = 3465,
    structures: Sequence[str] = (),
    inhabited: int = 0,
    status: str = "minecraft:full",
    block_entities: Sequence[dict] = (),
) -> dict:
    """A chunk whose blocks are `fill` layers (y_from, y_to inclusive, name) plus single blocks
    at local (x, y, z). Uses the 1.18+ layout, or the `Level` layout before DataVersion 2844."""
    sections: dict[int, list[str]] = {}

    def put(x: int, y: int, z: int, name: str) -> None:
        sec = sections.setdefault(y >> 4, ["minecraft:air"] * 4096)
        sec[((y & 15) * 16 + z) * 16 + x] = name

    for y0, y1, name in fill:
        for y in range(y0, y1 + 1):
            for z in range(16):
                for x in range(16):
                    put(x, y, z, name)
    for (x, y, z), name in blocks.items():
        put(x, y, z, name)

    modern = data_version >= 2844
    out_sections = []
    for sy, names in sorted(sections.items()):
        palette = list(dict.fromkeys(names))
        index = {n: i for i, n in enumerate(palette)}
        pal_nbt = TypedList(10, [{"Name": n} for n in palette])
        packed = None
        if len(palette) > 1:
            bits = max(4, (len(palette) - 1).bit_length())
            packed = pack([index[n] for n in names], bits, spanning=data_version < 2527)
        if modern:
            states: dict = {"palette": pal_nbt}
            if packed is not None:
                states["data"] = packed
            out_sections.append({"Y": Byte(sy), "block_states": states})
        else:
            sec: dict = {"Y": Byte(sy), "Palette": pal_nbt}
            if packed is not None:
                sec["BlockStates"] = packed
            out_sections.append(sec)

    refs = {f"minecraft:{s}": np.array([0], dtype=np.int64) for s in structures}
    body = {
        "xPos": cx,
        "zPos": cz,
        "Status": status,
        "InhabitedTime": Long(inhabited),
        ("sections" if modern else "Sections"): TypedList(10, out_sections),
        ("structures" if modern else "Structures"): {"References": refs, "starts": {}},
        ("block_entities" if modern else "TileEntities"): TypedList(10, list(block_entities)),
    }
    if modern:
        return {"DataVersion": data_version, **body}
    return {"DataVersion": data_version, "Level": body}


@dataclass
class PlayerSpec:
    uuid: str
    play_ticks: int = 72_000
    sessions: int = 3
    used: dict[str, int] = field(default_factory=lambda: {"minecraft:stone": 100})
    advancement_times: list[str] = field(default_factory=list)
    pos: tuple[float, float, float] = (1.5, 64.0, -3.5)
    game_type: int = 1
    inventory: list[dict] = field(default_factory=list)


def uuid_ints(u: str) -> np.ndarray:
    raw = bytes.fromhex(u.replace("-", ""))
    return np.frombuffer(raw, dtype=">i4").astype(np.int32)


def make_world(
    root: Path,
    *,
    level_name: str = "Test World",
    data_version: int = 3465,
    version_name: str = "1.20.1",
    game_type: int = 1,
    last_played: datetime | None = None,
    generator: dict | None = None,
    chunks: dict[str, list[tuple[int, int, int]]] | None = None,
    chunk_data: dict[str, list[dict]] | None = None,
    players: Sequence[PlayerSpec] = (),
    level_file: str = "level.dat",
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """Write a minimal but realistic world. `chunks` maps region dir -> [(cx, cz, timestamp)];
    `chunk_data` maps region dir -> full chunk NBT (see `chunk_nbt`), saved at a fixed time."""
    root.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "LevelName": level_name,
        "DataVersion": data_version,
        "Version": {"Name": version_name, "Id": data_version},
        "GameType": game_type,
        "allowCommands": Byte(1),
        "Time": Long(123_456),
        "LastPlayed": Long(int((last_played or datetime(2023, 9, 1, 20)).timestamp() * 1000)),
        "SpawnX": 0,
        "SpawnY": 64,
        "SpawnZ": 0,
        "WorldGenSettings": {
            "seed": Long(42),
            "dimensions": {
                "minecraft:overworld": {
                    "generator": generator
                    or {"type": "minecraft:noise", "settings": "minecraft:overworld"}
                }
            },
        },
    }
    (root / level_file).write_bytes(nbt_gz({"Data": data}))

    default = {"region": [(0, 0, 1_693_591_200)]}
    headers = default if chunks is None else chunks
    region_dirs: list[str] = list(dict.fromkeys([*headers, *(chunk_data or {})]))
    for region_dir in region_dirs:
        entries = headers.get(region_dir, [])
        by_region: dict[tuple[int, int], dict] = {}
        for cx, cz, ts in entries:
            by_region.setdefault((cx >> 5, cz >> 5), {})[(cx & 31, cz & 31)] = (
                {"DataVersion": data_version, "xPos": cx, "zPos": cz, "Status": "minecraft:full"},
                ts,
            )
        for chunk in (chunk_data or {}).get(region_dir, []):
            level = chunk.get("Level", chunk)
            cx, cz = level["xPos"], level["zPos"]
            by_region.setdefault((cx >> 5, cz >> 5), {})[(cx & 31, cz & 31)] = (
                chunk,
                1_693_591_200,
            )
        (root / region_dir).mkdir(parents=True, exist_ok=True)
        for (rx, rz), slots in by_region.items():
            (root / region_dir / f"r.{rx}.{rz}.mca").write_bytes(region(slots))

    for p in players:
        (root / "playerdata").mkdir(exist_ok=True)
        (root / "playerdata" / f"{p.uuid}.dat").write_bytes(
            nbt_gz(
                {
                    "UUID": uuid_ints(p.uuid),
                    "Pos": TypedList(6, list(p.pos)),
                    "Dimension": "minecraft:overworld",
                    "playerGameType": p.game_type,
                    "XpLevel": 5,
                    "Inventory": TypedList(10, p.inventory),
                }
            )
        )
        (root / "stats").mkdir(exist_ok=True)
        (root / "stats" / f"{p.uuid}.json").write_text(
            json.dumps(
                {
                    "stats": {
                        "minecraft:custom": {
                            "minecraft:play_time": p.play_ticks,
                            "minecraft:leave_game": p.sessions,
                        },
                        "minecraft:used": p.used,
                    },
                    "DataVersion": data_version,
                }
            )
        )
        (root / "advancements").mkdir(exist_ok=True)
        (root / "advancements" / f"{p.uuid}.json").write_text(
            json.dumps(
                {
                    "minecraft:story/root": {
                        "criteria": {f"c{i}": t for i, t in enumerate(p.advancement_times)},
                        "done": True,
                    },
                    "DataVersion": data_version,
                }
            )
        )

    for rel, content in (extra_files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    return root
