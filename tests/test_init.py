"""`mcatlas init`: a few questions, then a config file that loads and validates."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcatlas import cli
from mcatlas.adapters import environment
from mcatlas.config import InitAnswers, config_text, load_settings, validate_config_text


@pytest.fixture
def no_launcher(monkeypatch: pytest.MonkeyPatch):
    """Keep this computer's Minecraft launcher and locale out of the suggestions."""
    monkeypatch.setattr(environment, "minecraft_dir", lambda: None)
    monkeypatch.setattr(environment, "java", lambda: None)
    monkeypatch.setattr(environment, "language", lambda: "en")
    monkeypatch.setattr(environment, "timezone", lambda: "Europe/Amsterdam")


def _run(config: Path, answers: list[str], *args: str):
    return CliRunner().invoke(
        cli.app, ["--config", str(config), "init", *args], input="\n".join(answers) + "\n"
    )


def test_init_writes_a_config_that_loads(tmp_path: Path, no_launcher: None):
    worlds = tmp_path / "Minecraft_worlds"
    worlds.mkdir()
    config = tmp_path / "config.toml"
    result = _run(config, ["nl", str(worlds), str(tmp_path / "out"), "", "n"])
    assert result.exit_code == 0, result.output
    assert "mcatlas snapshot" in result.output

    settings, _ = load_settings(config)
    assert settings.language == "nl"
    assert settings.sources[0].path == worlds
    assert settings.paths.site_dir == tmp_path / "out" / "site"
    assert settings.paths.atlas_dir == tmp_path / "Minecraft_worlds_atlas"  # the suggestion
    assert settings.paths.render_dir is None
    assert settings.analysis.timezone == "Europe/Amsterdam"


def test_init_does_not_overwrite_without_force(tmp_path: Path, no_launcher: None):
    worlds = tmp_path / "w"
    worlds.mkdir()
    config = tmp_path / "config.toml"
    config.write_text("# mine\n")
    assert _run(config, []).exit_code == 1
    assert config.read_text() == "# mine\n"

    result = _run(config, ["en", str(worlds), str(tmp_path / "out"), "", "n"], "--force")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "config.toml.bak").read_text() == "# mine\n"
    assert load_settings(config)[0].language == "en"


def test_init_asks_again_for_a_missing_folder_and_refuses_output_inside(
    tmp_path: Path, no_launcher: None
):
    worlds = tmp_path / "w"
    worlds.mkdir()
    config = tmp_path / "config.toml"
    answers = ["en", str(tmp_path / "nope"), str(worlds), str(worlds / "out"), "", "n"]
    result = _run(config, answers)
    assert "Not a folder" in result.output
    assert result.exit_code == 2 and "do not work" in result.output
    assert not config.exists()


def test_config_text_with_3d_maps_round_trips(tmp_path: Path):
    answers = InitAnswers(
        language="en",
        worlds=tmp_path / "worlds",
        state_dir=Path.home() / ".local" / "state" / "mcatlas",
        site_dir=tmp_path / "out" / "site",
        atlas_dir=None,
        timezone="UTC",
        usercache=tmp_path / "usercache.json",
        render_dir=tmp_path / "out" / "render",
        java=tmp_path / "java",
        jar=tmp_path / "bluemap.jar",
        client_jar=None,
    )
    text = config_text(answers)
    assert 'state_dir = "~/.local/state/mcatlas"' in text  # home written as ~
    assert "# client_jar =" in text and "# atlas_dir =" in text
    settings = validate_config_text(text)
    assert settings.render.jar == tmp_path / "bluemap.jar"
    assert settings.paths.render_dir == tmp_path / "out" / "render"
    assert settings.players.usercache == [tmp_path / "usercache.json"]
