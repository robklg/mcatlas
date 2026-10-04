import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from mcatlas.adapters import guard
from mcatlas.adapters.guard import SafetyError, check_output_path
from mcatlas.config import load_settings


@pytest.fixture
def src(tmp_path: Path):
    root = tmp_path / "worlds"
    (root / "w").mkdir(parents=True)
    (root / "w" / "level.dat").write_bytes(b"x")
    with guard.protected([root]):
        yield root


def test_reading_is_allowed(src):
    assert (src / "w" / "level.dat").read_bytes() == b"x"
    fd = os.open(src / "w" / "level.dat", os.O_RDONLY)
    os.close(fd)
    assert list(os.scandir(src / "w"))


@pytest.mark.parametrize(
    "action",
    [
        lambda p: (p / "w" / "level.dat").write_bytes(b"y"),
        lambda p: open(p / "w" / "level.dat", "a"),  # noqa: SIM115
        lambda p: open(p / "w" / "new.txt", "x"),  # noqa: SIM115
        lambda p: open(p / "w" / "level.dat", "r+b"),  # noqa: SIM115
        lambda p: os.open(p / "w" / "level.dat", os.O_WRONLY),
        lambda p: os.open(p / "w" / "level.dat", os.O_RDONLY | os.O_TRUNC),
        lambda p: os.remove(p / "w" / "level.dat"),
        lambda p: os.rename(p / "w" / "level.dat", p / "w" / "moved"),
        lambda p: os.rename(p / "w" / "level.dat", p.parent / "outside"),
        lambda p: os.mkdir(p / "w" / "sub"),
        lambda p: os.rmdir(p / "w"),
        lambda p: os.chmod(p / "w" / "level.dat", 0o600),
        lambda p: os.utime(p / "w" / "level.dat"),
        lambda p: (p / "w" / "level.dat").touch(),
        lambda p: shutil.rmtree(p / "w"),
        lambda p: shutil.copyfile(p.parent / "elsewhere", p / "w" / "copy"),
        lambda p: sqlite3.connect(p / "w" / "db.sqlite"),
    ],
)
def test_every_write_path_is_blocked(src, action):
    (src.parent / "elsewhere").write_bytes(b"z")
    before = sorted(str(q) for q in src.rglob("*"))
    with pytest.raises(SafetyError):
        action(src)
    assert sorted(str(q) for q in src.rglob("*")) == before
    assert (src / "w" / "level.dat").read_bytes() == b"x"


def test_relative_and_case_variants_are_blocked(src, monkeypatch):
    monkeypatch.chdir(src / "w")
    with pytest.raises(SafetyError):
        Path("level.dat").write_bytes(b"y")
    if os.name == "posix" and os.uname().sysname == "Darwin":
        with pytest.raises(SafetyError):
            os.remove(str(src / "w" / "LEVEL.DAT"))


def test_writes_elsewhere_are_fine(src, tmp_path):
    (tmp_path / "out.txt").write_text("ok")
    assert check_output_path(tmp_path / "out") == (tmp_path / "out").resolve()
    with pytest.raises(SafetyError):
        check_output_path(src / "site")


def _write_config(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "mcatlas.toml"
    cfg.write_text(body)
    return cfg


def test_config_loads_and_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "worlds").mkdir()
    cfg = _write_config(
        tmp_path,
        """
[[sources]]
id = "archive"
path = "~/worlds"

[paths]
state_dir = "~/state"
site_dir = "~/site"

[players.names]
"A1E0A1E0-0000-4000-8000-000000000001" = "AlexCraft2020"

[analysis]
timezone = "Europe/Amsterdam"
""",
    )
    settings, path = load_settings(cfg)
    assert path == cfg
    assert settings.sources[0].path == tmp_path / "worlds"
    assert settings.paths.state_dir == tmp_path / "state"
    assert settings.analysis.zone().key == "Europe/Amsterdam"


def test_serving_needs_no_archive(tmp_path):
    """A web server holds the site, the fact store and the notes, not the worlds themselves."""
    cfg = _write_config(
        tmp_path,
        f"""
[[sources]]
id = "archive"
path = "{tmp_path / "not-on-this-machine"}"
[paths]
state_dir = "{tmp_path / "state"}"
site_dir = "{tmp_path / "site"}"
[serve]
allowed_hosts = [" Atlas.Example.org ", ""]
""",
    )
    settings, _ = load_settings(cfg)
    assert not settings.sources[0].path.exists()
    assert settings.serve.allowed_hosts == ["atlas.example.org"]
    guard.protect(s.path for s in settings.sources)  # as the CLI does; must not need the folder


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg = _write_config(
        tmp_path,
        f"""
[[sources]]
id = "a"
path = "{tmp_path / "worlds"}"
[paths]
state_dir = "{tmp_path / "state"}"
site_dir = "{tmp_path / "site"}"
[analysis]
jobs = 3
""",
    )
    monkeypatch.setenv("MCATLAS_ANALYSIS__JOBS", "5")
    settings, _ = load_settings(cfg)
    assert settings.analysis.jobs == 5


@pytest.mark.parametrize("inside", ["worlds/site", "."])
def test_outputs_may_not_overlap_sources(tmp_path, inside):
    cfg = _write_config(
        tmp_path,
        f"""
[[sources]]
id = "a"
path = "{tmp_path / "worlds"}"
[paths]
state_dir = "{tmp_path / "state"}"
site_dir = "{(tmp_path / inside).as_posix()}"
""",
    )
    with pytest.raises(ValueError, match="overlaps source"):
        load_settings(cfg)


def test_bad_timezone_and_missing_file(tmp_path):
    cfg = _write_config(
        tmp_path,
        f"""
[[sources]]
id = "a"
path = "{tmp_path / "worlds"}"
[paths]
state_dir = "{tmp_path / "state"}"
site_dir = "{tmp_path / "site"}"
[analysis]
timezone = "Mars/Olympus"
""",
    )
    with pytest.raises(ValueError, match="unknown timezone"):
        load_settings(cfg)
    with pytest.raises(ValueError, match="not found"):
        load_settings(tmp_path / "nope.toml")
