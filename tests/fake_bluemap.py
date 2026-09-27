"""Stands in for the BlueMap CLI in tests: `fakejava -jar fake_bluemap.py -c CONFIG -r -m IDS`.

It "renders" by writing low-res tiles over each map's render mask (grass green, height 70) and
logs which world folders it was pointed at, so tests can check BlueMap never sees the archive.
"""

import json
import sys
from pathlib import Path

from PIL import Image

TILE = 500


def tile_path(x: int, z: int) -> str:
    parts: list[str] = []
    current = ""
    for c in f"x{x}z{z}":
        current += c
        if c.isdigit():
            parts.append(current)
            current = ""
    return "/".join(parts)


def main(args: list[str]) -> int:
    config = Path(args[args.index("-c") + 1])
    ids = args[args.index("-m") + 1].split(",")
    storage = Path(json.loads((config / "storages" / "file.conf").read_text())["root"])
    log = config.parent / "fake-bluemap.log"
    for map_id in ids:
        conf = json.loads((config / "maps" / f"{map_id}.conf").read_text())
        world = Path(conf["world"])
        with log.open("a") as f:
            f.write(f"{args[args.index('-c') + 2]} {map_id} {world}\n")
        if "-r" not in args:
            continue
        if not (world / "level.dat").is_file():
            print(f"[ERROR] no level.dat in {world}")
            return 3
        for mask in conf["render-mask"]:
            for x in range(mask["min-x"], mask["max-x"] + 1, 16):
                for z in range(mask["min-z"], mask["max-z"] + 1, 16):
                    tx, tz = x // TILE, z // TILE
                    path = storage / map_id / "tiles" / "1" / f"{tile_path(tx, tz)}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tile = (
                        Image.open(path).copy()
                        if path.is_file()
                        else Image.new("RGBA", (TILE + 1, 2 * TILE + 2))
                    )
                    px, pz = x - tx * TILE, z - tz * TILE
                    for dx in range(16):
                        for dz in range(16):
                            if px + dx <= TILE and pz + dz <= TILE:
                                tile.putpixel((px + dx, pz + dz), (90, 160, 60, 255))
                                tile.putpixel((px + dx, pz + dz + TILE + 1), (0, 0, 70, 255))
                    tile.save(path)
        fail_once = config.parent / "fail-once"
        if fail_once.is_file():
            content = fail_once.read_bytes()
            fail_once.unlink()
            tile = storage / map_id / "tiles" / "0" / "x0" / "z0.prbm.gz"
            tile.parent.mkdir(parents=True, exist_ok=True)
            tile.write_bytes(b"old")
            tile.with_name("z0.prbm.gz.filepart").write_bytes(content)
            print("[ERROR] Failed to save hires model: (0, 0)")
            print(
                f"java.nio.file.FileSystemException: {storage}/{map_id}/tiles/0/x0/z0.prbm.gz: "
                "Resource busy"
            )
        print(f"[INFO] rendered {map_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
