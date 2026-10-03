import http.client
import io
import threading
from pathlib import Path

import pytest
from builders import FAKE_BLUEMAP, fake_java
from PIL import Image

from mcatlas.adapters import guard
from mcatlas.adapters.bluemap import (
    BlueMapRenderer,
    RenderError,
    stitch,
    surface_height,
    tile_path,
)
from mcatlas.adapters.serve import serve
from mcatlas.core.build import BuildSite, BuildSummary
from mcatlas.core.catalog import WorldEntry
from mcatlas.core.model import (
    NETHER,
    OVERWORLD,
    DimensionKey,
    DimensionLayout,
    Language,
    SourceFile,
    WorldFormat,
    WorldId,
    WorldLayout,
)
from mcatlas.core.render import (
    MapPlan,
    RenderArea,
    clamp,
    map_id,
    plan_maps,
    regions,
    without_texts,
)

WORLD = WorldId("sams-lab-a1b2c3")


def _site(dimension: str, bbox: tuple[int, int, int, int], *, pct_below: float = 10.0) -> BuildSite:
    return BuildSite(
        dimension=dimension,
        x=(bbox[0] + bbox[2]) // 2,
        z=(bbox[1] + bbox[3]) // 2,
        bbox=bbox,
        chunks=4,
        built=1234,
        below=100,
        no_ground=0,
        min_y=40,
        max_y=319,
        pct_below=pct_below,
        hours_nearby=1.0,
    )


def _entry(sites: list[BuildSite], **update: object) -> WorldEntry:
    entry = WorldEntry(
        world_id=WORLD,
        source_id="archive",
        relpath="Sams lab",
        folder_name="Sams lab",
        name="Sams lab",
        format=WorldFormat.ANVIL,
        data_version=3465,
        spawn=(10, 70, -20),
        build=BuildSummary(sites=sites),
    )
    return entry.model_copy(update=update)


def _dim(key: str, region_dir: str, coords: list[tuple[int, int]]) -> DimensionLayout:
    files = tuple(SourceFile(f"{region_dir}/r.{x}.{z}.mca", 100, 0) for x, z in coords)
    return DimensionLayout(key=DimensionKey(key), region_dir=region_dir, region_files=files)


LAYOUT = WorldLayout(
    format=WorldFormat.ANVIL,
    level_dat="level.dat",
    level_data=(),
    dimensions=(
        _dim(OVERWORLD, "region", [(0, 0), (-1, 0), (0, -1), (-1, -1), (5, 5)]),
        _dim(NETHER, "DIM-1/region", [(0, 0)]),
        _dim("mydatapack:moon", "dimensions/mydatapack/moon/region", [(0, 0)]),
    ),
    player_data=(),
    stats=(),
    advancements=(),
    icon=None,
    converted_from_mcregion=False,
)


def _plan(entry: WorldEntry, language: Language = "en") -> list[MapPlan]:
    return plan_maps(
        entry, LAYOUT, pad_blocks=32, spawn_radius=96, max_side=2048, language=language
    )


def test_map_ids_are_what_bluemap_accepts():
    assert map_id(WORLD, OVERWORLD) == "sams_lab_a1b2c3"
    assert map_id(WORLD, NETHER) == "sams_lab_a1b2c3__nether"
    with pytest.raises(ValueError, match="cannot be rendered"):
        map_id(WORLD, "mydatapack:moon")


def test_box_helpers():
    assert regions((-1, -1, 0, 0)) == {(-1, -1), (-1, 0), (0, -1), (0, 0)}
    assert regions((0, 0, 511, 511)) == {(0, 0)}
    assert clamp((0, 0, 99, 9), 90, 5, 20) == (80, 0, 99, 9)  # kept inside, (x, z) included
    assert clamp((0, 0, 99, 9), 3, 5, 20) == (0, 0, 19, 9)


def test_plans_cover_sites_per_dimension_and_copy_only_needed_regions():
    entry = _entry(
        [
            _site(OVERWORLD, (0, 0, 31, 31)),
            _site(NETHER, (16, 16, 47, 47), pct_below=0),
            _site("mydatapack:moon", (0, 0, 15, 15)),  # custom dimension: not rendered
            _site(OVERWORLD, (2600, 2600, 2615, 2615), pct_below=80),
        ],
        name="Lab",
    )
    over, nether = _plan(entry)
    assert over.map_id == "sams_lab_a1b2c3" and over.name == "Lab"
    assert [a.label for a in over.areas] == ["Site 1", "Site 4"]
    assert over.areas[0].box == (-32, -32, 63, 63)
    assert over.region_files == [
        "region/r.-1.-1.mca",
        "region/r.-1.0.mca",
        "region/r.0.-1.mca",
        "region/r.0.0.mca",
        "region/r.5.5.mca",
    ]
    assert over.show_caves  # site 4 is mostly underground
    assert over.areas[1].detail == "1,234 blocks built, 80% underground"
    assert over.marker_set == "Build sites"
    dutch, _ = _plan(entry, "nl")
    assert [a.label for a in dutch.areas] == ["Plek 1", "Plek 4"]
    assert dutch.areas[1].detail == "1.234 blokken gebouwd, 80% onder de grond"
    assert without_texts(dutch) == without_texts(over)  # same tiles in any language
    assert nether.name == "Lab (Nether)" and nether.region_files == ["DIM-1/region/r.0.0.mca"]
    assert nether.areas[0].max_y == 120 and nether.areas[0].y == 120  # below the roof
    assert over.sorting < nether.sorting


def test_worlds_without_sites_show_their_spawn_and_old_worlds_nothing():
    [plan] = _plan(_entry([]))
    assert [(a.label, a.box) for a in plan.areas] == [("Spawn", (-86, -116, 106, 76))]
    assert plan.region_files == [
        "region/r.-1.-1.mca",
        "region/r.-1.0.mca",
        "region/r.0.-1.mca",
        "region/r.0.0.mca",
    ]
    assert _plan(_entry([], data_version=1343)) == []  # 1.12: other chunk format
    assert _plan(_entry([], build=None)) == []  # not analyzed with tier 2
    assert _plan(_entry([], spawn=None)) == []


def test_tile_path_matches_bluemap():
    assert tile_path(0, 0) == "x0/z0"
    assert tile_path(-17, 3) == "x-1/7/z3"
    assert tile_path(123, -45) == "x1/2/3/z-4/5"


def _tile(path: Path, colour: tuple[int, int, int, int], height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (501, 1002))
    raw = height & 0xFFFF
    for x in range(501):
        for z in range(501):
            img.putpixel((x, z), colour)
            img.putpixel((x, z + 501), (0, raw >> 8, raw & 0xFF, 255))
    img.save(path)


def test_stitch_and_heights_across_tiles(tmp_path: Path):
    tiles = tmp_path / "tiles"
    _tile(tiles / "1" / "x-1" / "z0.png", (255, 0, 0, 255), -12)
    _tile(tiles / "1" / "x0" / "z0.png", (0, 0, 255, 255), 70)
    png = stitch(tiles, (-10, 5, 9, 14))
    assert png is not None
    with Image.open(io.BytesIO(png)) as img:
        assert img.size == (20, 10)
        assert img.getpixel((0, 0)) == (255, 0, 0, 255)  # x = -10
        assert img.getpixel((10, 9)) == (0, 0, 255, 255)  # x = 0
    assert surface_height(tiles, -3, 7) == -12
    assert surface_height(tiles, 3, 7) == 70
    assert surface_height(tiles, 3, -7) is None  # no tile there
    assert stitch(tiles, (0, -600, 10, -590)) is None
    # Large areas use a coarser level so that images stay reasonable.
    _tile(tiles / "2" / "x0" / "z0.png", (0, 255, 0, 255), 64)
    big = stitch(tiles, (0, 0, 9999, 99))
    assert big is not None
    with Image.open(io.BytesIO(big)) as img:
        assert img.size == (2000, 20)


def _renderer(tmp_path: Path, **kwargs: object) -> BlueMapRenderer:
    return BlueMapRenderer(
        tmp_path / "render",
        java=fake_java(tmp_path),
        jar=FAKE_BLUEMAP,
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def test_staging_keeps_mtimes_and_refuses_escapes(tmp_path: Path):
    r = _renderer(tmp_path)
    r.stage(WORLD, "region/r.0.0.mca", b"abc", 1_700_000_000_000_000_000)
    r.stage(WORLD, "level.dat", b"x", 5_000_000_000)
    assert r.staged(WORLD) == {
        "region/r.0.0.mca": (3, 1_700_000_000_000_000_000),
        "level.dat": (1, 5_000_000_000),
    }
    assert r.unstage(WORLD, {"level.dat"}) == 1
    assert set(r.staged(WORLD)) == {"level.dat"}
    for bad in ("../x", "/etc/passwd", "region/../../x"):
        with pytest.raises(ValueError, match="unsafe"):
            r.stage(WORLD, bad, b"", 0)


def test_workspace_inside_a_source_is_refused(tmp_path: Path):
    source = tmp_path / "Minecraft_worlds"
    source.mkdir()
    with guard.protected([source]), pytest.raises(guard.SafetyError):
        BlueMapRenderer(source / "render", java=None, jar=None)


def test_render_writes_index_images_and_config(tmp_path: Path):
    r = _renderer(tmp_path)
    r.stage(WORLD, "level.dat", b"x", 0)
    plan = MapPlan(
        map_id="sams_lab_a1b2c3",
        world_id=WORLD,
        world_name="Lab",
        dimension=OVERWORLD,
        name="Lab",
        sorting=0,
        areas=[RenderArea(label="Site 1", site=0, box=(0, 0, 31, 31), x=16, y=319, z=16)],
        level_file="level.dat",
    )
    progress: list[str] = []
    [done] = r.render([plan], {plan.map_id}, force=False, progress=progress.append)
    assert done.heights == {0: 70} and done.images == {0: "flat/sams_lab_a1b2c3/0.png"}
    assert r.image(done.images[0]).startswith(b"\x89PNG")
    assert r.rendered() == [done]
    assert any("rendered sams_lab_a1b2c3" in p for p in progress)
    conf = (tmp_path / "render" / "config" / "maps" / "sams_lab_a1b2c3.conf").read_text()
    assert '"y": 71' in conf  # marker moved from the site's top (319) to the ground
    core = (tmp_path / "render" / "config" / "core.conf").read_text()
    assert '"metrics": false' in core and '"accept-download": false' in core
    with pytest.raises(ValueError, match="flat"):
        r.image("config/core.conf")
    # Only the texts changed (another language): new markers, no new tiles.
    dutch = plan.model_copy(
        update={
            "marker_set": "Bouwplekken",
            "areas": [plan.areas[0].model_copy(update={"label": "Plek 1"})],
        }
    )
    progress.clear()
    assert r.render([dutch], set(), force=False, progress=progress.append) == []
    assert not any("rendered" in p for p in progress)
    [relabelled] = r.rendered()
    assert relabelled.areas[0].label == "Plek 1" and relabelled.heights == {0: 70}
    conf = (tmp_path / "render" / "config" / "maps" / "sams_lab_a1b2c3.conf").read_text()
    assert '"label": "Plek 1"' in conf and '"label": "Bouwplekken"' in conf
    assert "--markers sams_lab_a1b2c3" in (tmp_path / "render" / "fake-bluemap.log").read_text()
    # A map that is no longer planned disappears from the configuration.
    r.render([], set(), force=False, progress=progress.append)
    assert not (tmp_path / "render" / "config" / "maps" / "sams_lab_a1b2c3.conf").exists()


@pytest.mark.parametrize(("unsaved", "stale"), [(b"old", 0), (b"new", 1)])
def test_tiles_a_share_would_not_replace_are_settled(tmp_path: Path, unsaved: bytes, stale: int):
    r = _renderer(tmp_path)
    r.stage(WORLD, "level.dat", b"x", 0)
    plan = MapPlan(
        map_id="sams_lab_a1b2c3",
        world_id=WORLD,
        world_name="Lab",
        dimension=OVERWORLD,
        name="Lab",
        sorting=0,
        areas=[RenderArea(label="Site 1", site=0, box=(0, 0, 15, 15), x=8, y=64, z=8)],
        level_file="level.dat",
    )
    # The stand-in leaves an unsaved tile next to the old one, like an SMB "Resource busy".
    (tmp_path / "render" / "fail-once").write_bytes(unsaved)
    progress: list[str] = []
    [done] = r.render([plan], {plan.map_id}, force=False, progress=progress.append)
    part = tmp_path / "render/web/maps/sams_lab_a1b2c3/tiles/0/x0/z0.prbm.gz.filepart"
    assert done.stale_tiles == stale
    assert part.exists() == bool(stale)  # identical leftovers are cleaned up
    assert any("could not be replaced" in p for p in progress) == bool(stale)


def test_missing_jar_or_client_is_explained(tmp_path: Path):
    r = BlueMapRenderer(tmp_path / "render", java=fake_java(tmp_path), jar=tmp_path / "none.jar")
    plan = MapPlan(
        map_id="m",
        world_id=WORLD,
        world_name="w",
        dimension=OVERWORLD,
        name="w",
        sorting=0,
        areas=[RenderArea(label="Spawn", box=(0, 0, 1, 1), x=0, y=64, z=0)],
        level_file="level.dat",
    )
    with pytest.raises(RenderError, match="jar not found"):
        r.render([plan], {"m"}, force=False, progress=lambda _: None)
    bad_client = tmp_path / "client.jar"
    bad_client.write_bytes(b"not a zip")
    with pytest.raises(RenderError, match="client jar"):
        _renderer(tmp_path, client_jar=bad_client).render(
            [plan], {"m"}, force=False, progress=lambda _: None
        )


def test_serve_maps_3d_and_atlas_folders_read_only(tmp_path: Path):
    site, web, atlas = tmp_path / "site", tmp_path / "web", tmp_path / "atlas"
    site.mkdir()
    atlas.mkdir()
    (atlas / "timeline.html").write_text("timeline")
    (web / "maps").mkdir(parents=True)
    (site / "index.html").write_text("site")
    (web / "index.html").write_text("bluemap")
    (web / "maps" / "settings.json").write_text("{}")
    server = serve(site, "127.0.0.1", 0, extra={"3d": web, "atlas": atlas})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        def get(path: str) -> tuple[int, bytes]:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()

        assert get("/index.html") == (200, b"site")
        assert get("/3d/index.html") == (200, b"bluemap")
        assert get("/3d/maps/settings.json") == (200, b"{}")
        assert get("/3d/../site/index.html")[0] == 404  # ".." is dropped, never outside
        assert get("/3d/%2e%2e/index.html") != (200, b"site")
        assert get("/atlas/timeline.html") == (200, b"timeline")
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("POST", "/atlas/timeline.html", body=b"x", headers={"X-Mcatlas": "1"})
        assert conn.getresponse().status >= 400  # nothing but notes can be written
        assert (atlas / "timeline.html").read_text() == "timeline"
    finally:
        server.shutdown()
        server.server_close()
