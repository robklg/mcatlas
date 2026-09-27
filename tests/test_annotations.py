import http.client
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mcatlas.adapters import guard
from mcatlas.adapters.annotations_md import AnnotationStoreError, MarkdownAnnotations
from mcatlas.adapters.serve import serve
from mcatlas.app.annotations import NoteChange, apply_change, change_from_form, find_world
from mcatlas.config import PathSettings
from mcatlas.core.annotations import (
    Annotation,
    AnnotationError,
    format_annotation,
    parse_annotation,
)
from mcatlas.core.catalog import WorldEntry
from mcatlas.core.model import WorldFormat, WorldId

WORLD = WorldId("trein-statjon-faa7dc")
NOW = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)


def _entry(world_id: str = WORLD, folder: str = "trein statjon") -> WorldEntry:
    return WorldEntry(
        world_id=WorldId(world_id),
        source_id="archive",
        relpath=folder,
        folder_name=folder,
        name=folder,
        format=WorldFormat.ANVIL,
    )


def test_format_and_parse_roundtrip_is_readable():
    a = Annotation(
        world=WORLD,
        folder="trein statjon",
        title='Sams "treinstation"',
        tags=["gevonden", "Trein"],
        rating=5,
        updated=NOW,
        note="Gevonden via de bordjes.\n\n- perron 1\n- perron 2",
    )
    text = format_annotation(a)
    assert text.startswith('+++\nworld = "trein-statjon-faa7dc"\nfolder = "trein statjon"\n')
    assert "\n+++\n\nGevonden via de bordjes." in text
    assert parse_annotation(text) == a.model_copy(update={"tags": ["gevonden", "trein"]})


@given(
    title=st.text(max_size=80),
    note=st.text(max_size=300),
    tags=st.lists(st.from_regex(r"[a-z0-9][a-z0-9 -]{0,20}", fullmatch=True), max_size=4),
)
def test_roundtrip_of_arbitrary_text(title, note, tags):
    a = Annotation(world=WORLD, title=title, note=note, tags=tags)
    assert parse_annotation(format_annotation(a)) == a


def test_hand_edited_files_are_tolerated_and_bad_ones_rejected():
    crlf = '﻿+++\r\nworld = "x-1"\r\ntitle = "hoi"\r\n+++\r\n\r\ntekst\r\n'
    assert parse_annotation(crlf).note == "tekst"
    for bad in (
        "geen frontmatter",
        '+++\nworld = "x"\n',
        '+++\nworld = "x"\nkleur = 1\n+++\n',
        '+++\ntitle = "zonder world"\n+++\n',
        '+++\nworld = "x"\nrating = 9\n+++\n',
    ):
        with pytest.raises(AnnotationError):
            parse_annotation(bad)


def test_store_saves_loads_and_removes(tmp_path: Path):
    store = MarkdownAnnotations(tmp_path / "annotations")
    assert store.load() == ({}, [])
    where = store.save(Annotation(world=WORLD, folder="trein statjon", title="Station"))
    assert where.endswith(f"{WORLD}.md")
    assert (tmp_path / "annotations" / "README.md").read_text().startswith("# Notes on")
    # A renamed file is still found through its `world` field.
    (tmp_path / "annotations" / f"{WORLD}.md").rename(tmp_path / "annotations" / "station.md")
    notes, problems = store.load()
    assert notes[WORLD].title == "Station" and not problems
    store.save(notes[WORLD].model_copy(update={"title": "Treinstation"}))
    assert (tmp_path / "annotations" / "station.md").read_text().count("Treinstation") == 1
    (tmp_path / "annotations" / "kapot.md").write_text("zomaar tekst")
    _, problems = store.load()
    assert problems and problems[0].startswith("kapot.md")
    store.save(Annotation(world=WORLD))  # empty note: file removed
    assert not (tmp_path / "annotations" / "station.md").exists()
    # The README is written once, in the configured language, and then left alone.
    dutch = MarkdownAnnotations(tmp_path / "notes", language="nl")
    dutch.save(Annotation(world=WORLD, title="x"))
    assert (tmp_path / "notes" / "README.md").read_text().startswith("# Notities")
    MarkdownAnnotations(tmp_path / "notes").save(Annotation(world=WORLD, title="y"))
    assert (tmp_path / "notes" / "README.md").read_text().startswith("# Notities")


def test_store_needs_a_directory_and_respects_the_guard(tmp_path: Path):
    with pytest.raises(AnnotationStoreError):
        MarkdownAnnotations(None).save(Annotation(world=WORLD, title="x"))
    source = tmp_path / "Minecraft_worlds"
    source.mkdir()
    with guard.protected([source]):
        with pytest.raises(guard.SafetyError):
            MarkdownAnnotations(source / "notes").save(Annotation(world=WORLD, title="x"))
        # A sibling folder with a similar name is fine.
        MarkdownAnnotations(tmp_path / "Minecraft_worlds_atlas").save(
            Annotation(world=WORLD, title="x")
        )


def test_annotations_dir_defaults_to_atlas_dir(tmp_path: Path):
    paths = PathSettings(state_dir=tmp_path, site_dir=tmp_path / "s", atlas_dir=tmp_path / "atlas")
    assert paths.annotations() == tmp_path / "atlas" / "annotations"
    assert PathSettings(state_dir=tmp_path, site_dir=tmp_path).annotations() is None


def test_apply_change_merges_and_replaces():
    first = apply_change(None, _entry(), NoteChange(append="eerste", add_tags=["gevonden"]), NOW)
    assert (first.note, first.tags, first.folder) == ("eerste", ["gevonden"], "trein statjon")
    second = apply_change(
        first, _entry(), NoteChange(append="tweede", add_tags=["trein"], rating=4), NOW
    )
    assert (second.note, second.tags, second.rating) == (
        "eerste\n\ntweede",
        ["gevonden", "trein"],
        4,
    )
    third = apply_change(second, _entry(), NoteChange(remove_tags=["GEVONDEN"], title="T"), NOW)
    assert (third.tags, third.title, third.rating) == (["trein"], "T", 4)
    form = change_from_form({"title": "", "note": "nieuw", "tags": [], "rating": None})
    fourth = apply_change(third, _entry(), form, NOW)
    assert (fourth.title, fourth.note, fourth.tags, fourth.rating) == ("", "nieuw", [], None)
    with pytest.raises(ValueError, match="extra"):
        change_from_form({"note": "x", "world": "other"})


def test_find_world_prefers_exact_matches():
    worlds = [_entry("a-1", "trein"), _entry("b-2", "trein statjon")]
    assert [e.world_id for e in find_world(worlds, "trein")] == ["a-1"]
    assert [e.world_id for e in find_world(worlds, "statj")] == ["b-2"]


def _post(port: int, path: str, body: object, headers: dict[str, str]) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body).encode()
    conn.request("POST", path, data, {"Content-Type": "application/json", **headers})
    response = conn.getresponse()
    return response.status, json.loads(response.read() or b"{}")


def test_serve_note_api_requires_header_and_host(tmp_path: Path):
    saved: list[tuple[str, dict]] = []

    def on_note(world: str, payload):
        if world != WORLD:
            raise KeyError(world)
        saved.append((world, dict(payload)))
        return {"ok": True}

    server = serve(tmp_path, "127.0.0.1", 0, on_note=on_note)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = f"/api/notes/{WORLD}"
        assert _post(port, path, {"note": "x"}, {})[0] == 403  # no custom header
        assert (
            _post(port, path, {"note": "x"}, {"X-Mcatlas": "1", "Host": "evil.example"})[0] == 403
        )
        assert _post(port, "/api/notes/other-1", {"note": "x"}, {"X-Mcatlas": "1"})[0] == 404
        assert _post(port, path, ["not", "an", "object"], {"X-Mcatlas": "1"})[0] == 400
        assert _post(port, path, {"note": "x"}, {"X-Mcatlas": "1"}) == (200, {"ok": True})
        assert saved == [(WORLD, {"note": "x"})]
    finally:
        server.shutdown()
        server.server_close()
