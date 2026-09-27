# mcatlas

A strictly **read-only** catalog and explorer for an archive of Minecraft Java worlds.

mcatlas scans a folder full of old world backups, works out for each world *when* it was played,
*how much*, *by whom* and *what kind of world* it is, and publishes a searchable, sortable catalog
website. The goal is to answer "which of these 150 worlds is the one we worked on for months?"
without opening them one by one in Minecraft.

## Safety model

The worlds are irreplaceable, so nothing in mcatlas can modify them:

* **One read-only door.** Only `adapters/source_folder.py` and `adapters/source_zip.py` (via
  `adapters/readonly.py`) read world files, always with `O_RDONLY | O_NOFOLLOW`. They have no
  write methods. Zip archives are read in place, never extracted next to the source.
* **A pure core.** Decoders and analyzers in `mcatlas.core` get bytes through a protocol and
  have no filesystem access at all. The package contains no NBT or region *writer*.
* **Enforced boundaries.** import-linter contracts (`.importlinter`) forbid `core` from
  importing `os`, `pathlib`, `sqlite3` and the like, and keep the layers in order.
* **Guarded outputs.** Every writing adapter checks its target with
  `guard.check_output_path`; configuration refuses output paths that overlap a source.
* **A safety net.** A PEP 578 audit hook blocks any write, delete, rename, chmod, utime or
  SQLite connection under a source path, whatever code attempts it.
* **External programs only see copies.** BlueMap (for 3D maps) runs as a separate Java
  process, out of reach of the audit hook, so it never gets a path into the archive: mcatlas
  copies the few files a map needs through the read-only door into `paths.render_dir` and
  points BlueMap there.
* **Proof afterwards.** `mcatlas snapshot` records a manifest (size, mtime, xxh3-128 of every
  file); `mcatlas verify [--full]` shows that nothing was added, removed or changed.

mcatlas does not mount anything. Mount your share however you like.

## Quick start

```sh
uv sync
cp mcatlas.example.toml ~/.config/mcatlas/config.toml   # then edit paths
uv run mcatlas doctor          # check configuration
uv run mcatlas snapshot        # baseline manifest (hashes every file once)
uv run mcatlas analyze         # incremental: unchanged worlds are skipped
uv run mcatlas analyze --tier 2   # also read every chunk: what was built, where, how deep
uv run mcatlas build-site      # writes the static site to paths.site_dir
uv run mcatlas render          # 3D maps of the build sites (BlueMap), then verify
uv run mcatlas serve           # http://127.0.0.1:8765 (or open index.html directly)
uv run mcatlas export-atlas    # durable plain-file atlas next to the archive
uv run mcatlas verify          # prove the archive is unchanged
```

Other commands: `inventory` (list worlds without analyzing), `search TEXT` (names, players,
signs, books, notes), `show WORLD`, `note WORLD [TEXT] [--title --tag --rating]`, `notes`.

## Adding worlds later

mcatlas only reads **Java Edition** worlds, and only 1.13+ chunks are analyzed in depth and
rendered in 3D. For anything else, work on a *copy* outside the archive first:

1. **Bedrock** (phone, tablet, Switch, Xbox One/Series, Windows "Minecraft") and **old console
   editions** (Wii U, Xbox 360, PS3/PS4: "Legacy Console Edition") store worlds in their own
   formats: convert the copy to Java with a converter tool first.
2. **Old Java worlds** (and converter output, which is often pre-1.13; recognisable by a
   `level.dat_mcr` or no DataVersion): open the copy once in a recent Java version and use
   *Edit World → Optimize World* to rewrite all chunks in the current format. Minecraft
   writes to the world while doing this, so never do it inside the archive.
3. Put the resulting folder into the archive yourself (mcatlas never writes there), then:

```sh
uv run mcatlas verify            # should list only your new files as "added"
uv run mcatlas snapshot          # new baseline that includes them
uv run mcatlas analyze --tier 2  # only new or changed worlds are analyzed
uv run mcatlas render            # only new maps; also refreshes the site
uv run mcatlas export-atlas      # refresh the durable atlas
```

Converting and optimizing re-save every chunk, which has two side effects: the day you did it
shows up as a play day of that world, and mcatlas no longer sees the copy as related to the
original (it recognises copies by their chunk save times). Keep the original next to the copy
if you like, and write both facts in a note (`mcatlas note`).

## 3D maps (BlueMap)

`mcatlas render` shows every build site in 3D with the
[BlueMap](https://bluemap.bluecolored.de) command-line version:

1. For each world it plans one map per dimension (overworld, Nether, End) with a render mask
   around the build sites (`render.pad` blocks of surroundings, at most `render.max_side` per
   side); worlds without a site get the area around their spawn point.
2. It copies `level.dat` and only the region files those areas overlap into
   `<render_dir>/worlds/<world id>/`, keeping their modification times. Unchanged copies are not
   copied again, and maps whose plan and copies did not change are not rendered again.
3. It writes BlueMap's configuration (metrics off), runs BlueMap on those copies in batches,
   stitches a flat top-down PNG per site from BlueMap's low-res tiles, reads the ground height
   at each site from them, and puts a marker on every site.
4. It refreshes the site (flat maps in the world details, "open in 3D" per site) and runs
   `verify` (skip with `--no-check`).

The viewer is served by `mcatlas serve` under `/3d/`; it needs a web server, so the 3D links
only appear when the catalog is opened that way. Requirements, in `[render]`:

* `java`: Java 25 for BlueMap 5.17+ (the Minecraft launcher ships one), `jar`: the BlueMap CLI.
* Textures from a Minecraft client jar: `client_jar` pointing at the jar your launcher already
  has, or `accept_download = true` to let BlueMap download it from Mojang. The latter means
  accepting the [Minecraft EULA](https://www.minecraft.net/eula), so it is off by default.

## Durable atlas (export)

`mcatlas export-atlas` writes the end result to `paths.atlas_dir` (next to the archive, never
inside it) as plain files that stay readable without mcatlas:

```
README.md             what this is and how to read the numbers (in Dutch)
index.md, index.html  all worlds in one table, most played first
worlds.csv            the same, for a spreadsheet
schema/world.schema.json
worlds/<world id>/
  README.md, index.html   everything known about the world (same content twice)
  facts.toml              machine-readable facts, with `schema_version`
  teksten.md, .html       signs, books, names and commands
  plek-<n>.png, icon.png  flat maps of the build sites (from `render`), the world icon
annotations/          the notes (see below): never written by the export
```

The HTML has no scripts. Running it again writes only files that changed, and removes only
files an earlier export wrote (listed in `.mcatlas-export.json`) that are no longer needed.
`--check` runs `verify` afterwards.

## Notes (annotations)

Notes about a world are plain Markdown files with TOML front matter, one per world, in
`paths.annotations_dir` (default `<paths.atlas_dir>/annotations`, next to the archive, never
inside it). They can be written with `mcatlas note`, edited on the site when it is opened through
`mcatlas serve` (a local-only endpoint that only ever writes note files), or edited by hand:

```
+++
world = "trein-statjon-faa7dc"
folder = "trein statjon"
title = "Sams treinstation"
tags = ["gevonden", "trein"]
rating = 5
+++

Gevonden via de bordjes op de perrons.
```

The `world` field ties a file to its world, so files can be renamed. Notes are searchable and
filterable on the site and survive without mcatlas.

After adding or editing notes, run `mcatlas export-atlas` again so the atlas pages quote them
too (the notes themselves are already durable where they are).

## What it measures (tier 1)

| Signal | Source | Notes |
|---|---|---|
| Name, version, game mode, world type, seed | `level.dat` / `special_level.dat` | § formatting stripped; flat/void/amplified/… detected |
| Active days, first/last day, span | chunk save times in region headers, game-file mtimes, advancement criteria dates, `LastPlayed` | Union of all signals; a **lower bound** because each chunk only keeps its last save time |
| Play time, sessions, items used | `stats/<uuid>.json` | "items used" includes every block placed, also in creative |
| Players and their last position | `playerdata/*.dat`, host player in `level.dat` | Names from launcher `usercache.json` plus config |
| Explored area, dimensions | region headers | Vanilla, `DIM<n>` (20w14∞) and `dimensions/<ns>/<name>` layouts |
| Copies / shared history | MinHash over (dimension, chunk, save time) | Flags worlds that are copies of each other |
| "Worked on" score | log-weighted sum of the above | Every component stays visible |

Only 8 KiB per region file is read in tier 1, so a full scan of an 11 GB archive over SMB takes
minutes.

## What it measures (tier 2)

Tier 2 decodes every generated chunk (1.13+ formats) and classifies each block:

| Measure | How |
|---|---|
| Built blocks (≈ m³) | Blocks the world generator does not place itself (`core/data/natural_blocks.py`). Building with natural blocks (stone, dirt, logs) is not counted. |
| Not ours | In chunks touched by a structure, blocks that structure could have placed are counted apart (mineshafts: exact palette; others: broad list). Chunks with a spawner get the dungeon rule. |
| % underground | A block is underground when it lies below the natural surface: the highest natural ground block per column, smoothed per region with a morphological closing (17 blocks) so dug-out cellars and pits count as underground while wide valleys stay valleys. |
| Build sites | Built chunks at most 2 chunks apart, with coordinates, height range, share underground, time spent nearby (InhabitedTime) and a teleport command. |
| Map, height profile, top blocks | Per chunk: built blocks and minutes of player presence. |

Region files are read whole through the read-only source layer; decoding runs in worker
processes (`analysis.processes`, default: all cores) that only ever receive bytes.
The whole archive (1.8 million chunks) takes minutes; results are cached like tier 1.

## Architecture

Light hexagonal (ports & adapters):

```
cli.py          composition root (typer); the only place adapters are wired together
config.py       pydantic-settings: TOML + MCATLAS_* env + CLI
app/            one plain function per use case, against ports only
ports.py        Protocols: WorldSource (read-only), FactStore, SiteWriter, Renderer, AtlasWriter
adapters/       filesystem, zip, SQLite, static site, manifests, audit-hook guard
core/           pure: NBT decoder, region headers, format adapters, analyzers, catalog
```

Typing: basedpyright in strict mode (`reportAny` on), typed format adapters so that no
`dict[str, Any]` escapes the decoding boundary, pydantic models for persisted facts, and
typeguard checking every call during the test run.

## Development

```sh
uv run pytest                 # includes the read-only pipeline test and layer contracts
uv run basedpyright
uv run ruff check && uv run ruff format --check
uv run lint-imports
MCATLAS_ARCHIVE=/Volumes/share/Archive/Minecraft_worlds uv run pytest -m archive   # opt-in
```

The read-only pipeline test builds a fixture archive (nested worlds, zip, McRegion-style edge
cases), makes it read-only with `chmod`, runs the whole pipeline under the audit hook and asserts
that a hashed manifest is identical before and after.
