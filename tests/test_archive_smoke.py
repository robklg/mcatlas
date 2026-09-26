"""Opt-in smoke test against the real archive: MCATLAS_ARCHIVE=/path/to/worlds pytest -m archive."""

import os
from pathlib import Path

import pytest

from mcatlas.adapters import guard, manifest
from mcatlas.adapters.source_folder import FolderSource
from mcatlas.adapters.store_sqlite import SqliteFactStore
from mcatlas.app.analyze import AnalyzeOptions, analyze_sources

ARCHIVE = os.environ.get("MCATLAS_ARCHIVE")
pytestmark = [
    pytest.mark.archive,
    pytest.mark.skipif(not ARCHIVE, reason="set MCATLAS_ARCHIVE to run against the real archive"),
]
SAMPLE = os.environ.get("MCATLAS_ARCHIVE_SAMPLE", "Sam stad")


def test_analyze_one_real_world(tmp_path: Path):
    root = Path(ARCHIVE or "")
    world = root / SAMPLE
    with guard.protected([root]):
        before = manifest.take("sample", world, hashed=True)
        store = SqliteFactStore(tmp_path / "state.sqlite")
        try:
            report = analyze_sources(
                [FolderSource("archive", root)],
                store,
                AnalyzeOptions(world_glob=SAMPLE, jobs=2),
            )
        finally:
            store.close()
        after = manifest.take("sample", world, hashed=True)
    assert report.worlds == 1 and not report.failures
    assert manifest.compare(before, after).clean
