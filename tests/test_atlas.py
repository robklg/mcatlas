"""The durable atlas: plain pages from one document model, deterministic files, safe writing."""

import csv
import json
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mcatlas.adapters import guard
from mcatlas.adapters.atlas_fs import WRITTEN_LIST, AtlasFolderWriter, AtlasPathError
from mcatlas.core.activity import ActivityProfile, DaySignals
from mcatlas.core.annotations import Annotation
from mcatlas.core.atlas import atlas_files, world_schema
from mcatlas.core.build import BuildSite, BuildSummary
from mcatlas.core.catalog import Catalog, PlayerSummary, WorldEntry
from mcatlas.core.document import (
    Code,
    Document,
    Items,
    Paragraph,
    Pre,
    Table,
    link,
    page,
    to_html,
    to_markdown,
)
from mcatlas.core.facts import TextEntry
from mcatlas.core.model import GameMode, Language, WorldFormat, WorldId
from mcatlas.core.render import RenderArea, RenderedMap

WID = WorldId("droom-wereld-abc123")


def test_markdown_and_html_come_from_one_document():
    doc = Document(
        "A <b> & *c*",
        [
            Paragraph(["1. not a list, ", page("other", "../x/"), " ", Code("tp @s 1 2 3")]),
            Items(["- no bullet", link("map", "plek 1.png")]),
            Table(["Blok", "Aantal"], [["oak_planks | x", "1.234"]], numeric=(1,)),
            Pre("```\nline"),
        ],
    )
    md = to_markdown(doc)
    assert md.startswith("# A \\<b\\> & \\*c\\*\n")
    assert "\\1. not a list, [other](../x/README.md) `tp @s 1 2 3`" in md
    assert "- \\- no bullet\n- [map](<plek 1.png>)" in md
    assert "| oak_planks \\| x | 1.234 |" in md and "| --- | ---: |" in md
    assert "````text\n```\nline\n````" in md

    page_html = to_html(doc)
    assert "<title>A &lt;b&gt; &amp; *c*</title>" in page_html
    assert '<a href="../x/index.html">other</a>' in page_html
    assert '<td class="n">1.234</td>' in page_html
    assert "<script" not in page_html


def _entry() -> WorldEntry:
    days = {
        date(2023, 2, 12): DaySignals(chunk_saves=3),
        date(2023, 3, 1): DaySignals(advancements=1),
    }
    return WorldEntry(
        world_id=WID,
        source_id="archive",
        relpath="Alex en Sam's droom wereld",
        folder_name="Alex en Sam's droom wereld",
        name="droom wereld",
        format=WorldFormat.ANVIL,
        version_name="1.20.1",
        game_mode=GameMode.CREATIVE,
        seed=-42,
        spawn=(0, 64, 0),
        players=[PlayerSummary(uuid="5a305a30", name="SamCraft2024", known=True, play_hours=12)],
        play_hours=12,
        sessions=15,
        days_upper=15,
        activity=ActivityProfile(
            days=days,
            distinct_days=2,
            first_day=date(2023, 2, 12),
            last_day=date(2023, 3, 1),
            span_days=18,
            active_months=2,
        ),
        build=BuildSummary(
            built=1234,
            below=900,
            pct_below=72.9,
            top_blocks=[("minecraft:oak_planks", 1000)],
            sites=[
                BuildSite(
                    dimension="minecraft:overworld",
                    x=88,
                    z=8,
                    bbox=(80, 0, 95, 15),
                    chunks=1,
                    built=1234,
                    below=900,
                    no_ground=0,
                    min_y=40,
                    max_y=70,
                    pct_below=72.9,
                    hours_nearby=2.0,
                )
            ],
        ),
        text_counts={"sign": 1},
        annotation=Annotation(world=WID, title="Gevonden!", tags=["trein"], rating=5, note="*ja*"),
    )


def _catalog() -> Catalog:
    rendered = RenderedMap(
        map_id="droom_wereld_abc123",
        world_id=WID,
        world_name="droom wereld",
        dimension="minecraft:overworld",
        name="droom wereld",
        sorting=0,
        areas=[RenderArea(label="Site 1", site=0, box=(48, -32, 127, 47), x=88, y=70, z=8)],
        show_caves=True,
        level_file="level.dat",
        region_files=["region/r.0.0.mca"],
        rendered_at=datetime(2026, 9, 26, tzinfo=UTC),
        images={0: "flat/droom_wereld_abc123/0.png"},
    )
    entry = _entry()
    return Catalog(
        generated_at=datetime.now(UTC),
        timezone="UTC",
        worlds=[entry],
        texts={
            WID: [
                TextEntry(
                    kind="sign", text="Sams / geheime basis", holder="oak_sign", x=83, y=61, z=3
                )
            ]
        },
        annotations={
            WID: entry.annotation or Annotation(world=WID),
            WorldId("gone-000000"): Annotation(world=WorldId("gone-000000"), title="weg"),
        },
        renders={WID: [rendered]},
    )


def _files(language: Language = "nl") -> dict[str, bytes]:
    return atlas_files(
        _catalog(),
        icons={WID: b"icon"},
        images={"flat/droom_wereld_abc123/0.png": b"png"},
        generated=date(2026, 9, 27),
        tool="mcatlas test",
        language=language,
    )


def test_atlas_files_are_complete_and_deterministic():
    files = _files()
    base = f"worlds/{WID}/"
    assert set(files) == {
        "README.md",
        "index.md",
        "index.html",
        "worlds.csv",
        "schema/world.schema.json",
        *(base + f for f in ("README.md", "index.html", "facts.toml", "icon.png", "site-1.png")),
        base + "texts.md",
        base + "texts.html",
    }
    assert files == _files()  # the same catalog gives the same bytes
    assert files[base + "site-1.png"] == b"png" and files[base + "icon.png"] == b"icon"
    assert not any(p.startswith("annotations") for p in files)

    facts = tomllib.loads(files[base + "facts.toml"].decode())
    assert facts["schema_version"] == 1 and facts["game_mode"] == "creative"
    assert facts["activity"]["days"] == [date(2023, 2, 12), date(2023, 3, 1)]
    assert facts["build"]["sites"][0]["image"] == "site-1.png"
    assert (
        facts["build"]["sites"][0]["teleport"]
        == "/execute in minecraft:overworld run tp @s 88 72 8"
    )
    assert facts["note"] == {"title": "Gevonden!", "tags": ["trein"], "rating": 5}
    assert "properties" in json.loads(world_schema())

    rows = list(csv.DictReader(files["worlds.csv"].decode().splitlines()))
    assert rows[0]["world_id"] == WID and rows[0]["built"] == "1234" and rows[0]["days_max"] == "15"

    readme = files[base + "README.md"].decode()
    assert "| Gebouwd | 1.234 blokken, 73% onder de grond |" in readme
    assert "februari 2023: 12 (1 dag)" in readme and "maart 2023: 1 (1 dag)" in readme
    assert "![Plek 1 van bovenaf](site-1.png)" in readme
    assert "Gevonden! · ★★★★★ · trein" in readme and "\n*ja*\n" in readme
    assert "[teksten](texts.md)" in readme
    index = files["index.md"].decode()
    assert f"[droom wereld](worlds/{WID}/README.md)" in index
    assert "Notities zonder wereld" in index and "gone-000000" in index
    assert f'href="worlds/{WID}/index.html"' in files["index.html"].decode()
    assert "Sams / geheime basis" in files[base + "texts.md"].decode()
    assert '<html lang="nl">' in files[base + "index.html"].decode()


def test_atlas_in_english_has_the_same_files():
    nl, en = _files("nl"), _files("en")
    assert set(en) == set(nl)
    base = f"worlds/{WID}/"
    assert en[base + "facts.toml"] == nl[base + "facts.toml"]  # facts are language-neutral
    assert en["worlds.csv"] == nl["worlds.csv"]

    readme = en[base + "README.md"].decode()
    assert "| Built | 1,234 blocks, 73% underground |" in readme
    assert "February 2023: 12 (1 day)" in readme
    assert "![Site 1 from above](site-1.png)" in readme and "[texts](texts.md)" in readme
    assert '<html lang="en">' in en[base + "index.html"].decode()
    assert "Notes without a world" in en["index.md"].decode()
    assert "## Updating" in en["README.md"].decode()
    pages = b"".join(v for k, v in en.items() if k.endswith((".md", ".html"))).decode()
    for dutch in ("blokken", "werelden", "Plek ", "Bouwplekken", "Speeltijd", "onder de grond"):
        assert dutch not in pages, dutch


def test_writer_writes_changes_and_removes_only_its_own_files(tmp_path: Path):
    atlas = tmp_path / "atlas"
    notes = atlas / "annotations"
    notes.mkdir(parents=True)
    (notes / "x.md").write_text("mine")
    (atlas / "family.txt").write_text("ours")
    writer = AtlasFolderWriter(atlas, notes_dir=notes)

    first = writer.write(
        {"index.md": b"a", "worlds/w1/README.md": b"b", "worlds/w2/facts.toml": b"c"}
    )
    assert (first.written, first.unchanged, first.removed) == (3, 0, 0)
    stamp = (atlas / "index.md").stat().st_mtime_ns

    second = writer.write({"index.md": b"a", "worlds/w1/README.md": b"B"})
    assert (second.written, second.unchanged, second.removed) == (1, 1, 1)
    assert (atlas / "index.md").stat().st_mtime_ns == stamp  # unchanged: not rewritten
    assert not (atlas / "worlds" / "w2").exists()  # emptied folder pruned
    assert (notes / "x.md").read_text() == "mine" and (atlas / "family.txt").read_text() == "ours"
    assert json.loads((atlas / WRITTEN_LIST).read_text())["files"] == [
        "index.md",
        "worlds/w1/README.md",
    ]


def test_writer_ignores_a_tampered_list(tmp_path: Path):
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    (tmp_path / "precious").write_text("keep")
    (atlas / "annotations").mkdir()
    (atlas / "annotations" / "n.md").write_text("keep")
    listing = {"files": ["../precious", "annotations/n.md", "/etc/hosts"]}
    (atlas / WRITTEN_LIST).write_text(json.dumps(listing))
    report = AtlasFolderWriter(atlas, notes_dir=atlas / "annotations").write({"index.md": b"a"})
    assert report.removed == 0
    assert (tmp_path / "precious").read_text() == "keep"
    assert (atlas / "annotations" / "n.md").read_text() == "keep"


@pytest.mark.parametrize("relpath", ["../out.md", "/abs.md", "annotations/x.md", WRITTEN_LIST])
def test_writer_refuses_paths_outside_its_files(tmp_path: Path, relpath: str):
    writer = AtlasFolderWriter(tmp_path / "atlas", notes_dir=tmp_path / "atlas" / "annotations")
    with pytest.raises(AtlasPathError):
        writer.write({relpath: b"x"})


def test_writer_refuses_a_protected_source(tmp_path: Path):
    source = tmp_path / "worlds"
    source.mkdir()
    with guard.protected([source]), pytest.raises(guard.SafetyError):
        AtlasFolderWriter(source / "atlas", notes_dir=None).write({"index.md": b"x"})
