"""Configuration: TOML file + MCATLAS_* environment variables + CLI overrides.

Precedence (highest first): CLI overrides, environment, config file. No data location has a
default in code: every path comes from configuration.

Config file lookup: `--config`, then $MCATLAS_CONFIG, then ./mcatlas.toml, then
~/.config/mcatlas/config.toml.
"""

import json
import os
import sys
import tomllib
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Self, cast, override
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from mcatlas.core.model import Language

USER_CONFIG = Path("~/.config/mcatlas/config.toml")
"""Where `mcatlas init` writes, and the last place a config file is looked for."""

_CONFIG_FILE: ContextVar[Path | None] = ContextVar("mcatlas_config_file", default=None)


class ConfigError(ValueError):
    pass


def _expand(path: Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


class SourceSettings(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    path: Path
    archives: list[str] = Field(default_factory=lambda: ["*.zip"])
    exclude: list[str] = Field(default_factory=list[str])

    @field_validator("path")
    @classmethod
    def _expand_path(cls, v: Path) -> Path:
        return _expand(v)


class PathSettings(BaseModel):
    state_dir: Path
    """Local: SQLite cache and manifests. Keep it off network shares (SQLite + SMB is unsafe)."""
    site_dir: Path
    cache_dir: Path | None = None
    render_dir: Path | None = None
    atlas_dir: Path | None = None
    annotations_dir: Path | None = None

    @field_validator("*")
    @classmethod
    def _expand_paths(cls, v: Path | None) -> Path | None:
        return _expand(v) if v is not None else None

    def annotations(self) -> Path | None:
        """Where notes live: annotations_dir, else <atlas_dir>/annotations."""
        if self.annotations_dir is not None:
            return self.annotations_dir
        return self.atlas_dir / "annotations" if self.atlas_dir is not None else None

    def outputs(self) -> dict[str, Path]:
        candidates = {
            "state_dir": self.state_dir,
            "site_dir": self.site_dir,
            "cache_dir": self.cache_dir,
            "render_dir": self.render_dir,
            "atlas_dir": self.atlas_dir,
            "annotations_dir": self.annotations_dir,
        }
        return {name: path for name, path in candidates.items() if path is not None}


class PlayerSettings(BaseModel):
    names: dict[str, str] = Field(default_factory=dict[str, str])
    """UUID -> display name; wins over names found in usercache files."""
    gamertags: dict[str, str] = Field(default_factory=dict[str, str])
    """Console gamertag -> display name, for worlds converted from a console (lce2java)."""
    usercache: list[Path] = Field(default_factory=list[Path])

    @field_validator("usercache")
    @classmethod
    def _expand_paths(cls, v: list[Path]) -> list[Path]:
        return [_expand(p) for p in v]


class AnalysisSettings(BaseModel):
    timezone: str = "UTC"
    """IANA zone used to turn timestamps into calendar days."""
    jobs: int = Field(default=8, ge=1, le=64)
    """Worlds analyzed in parallel."""
    processes: int = Field(default_factory=lambda: os.cpu_count() or 1, ge=1, le=256)
    """Worker processes for chunk decoding (tier 2); 1 = in-process."""
    io_threads: int = Field(default=32, ge=1, le=256)
    """Concurrent small reads/stats; hides network-share latency (measured ~20x on SMB)."""
    ignore_file_days: list[date] = Field(default_factory=list[date])
    """Extra days whose file mtimes are not play evidence (copy/backup days). Days on which
    many worlds changed only mtimes are detected automatically as well."""

    @field_validator("timezone")
    @classmethod
    def _valid_zone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"unknown timezone {v!r}") from e
        return v

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class ServeSettings(BaseModel):
    allowed_hosts: list[str] = Field(default_factory=list[str])
    """Host headers the note editor accepts besides the address `serve` binds to: the name a
    reverse proxy serves the site under (e.g. "atlas.example.org"). Compared exactly as the
    browser sends it, so with a port only when the URL has one."""

    @field_validator("allowed_hosts")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return [h.strip().lower() for h in v if h.strip()]


class RenderSettings(BaseModel):
    """3D maps with BlueMap (https://bluemap.bluecolored.de), run as a separate Java program.

    BlueMap only ever sees copies: mcatlas copies the region files around build sites into
    paths.render_dir first. BlueMap needs textures from a Minecraft client jar: point
    `client_jar` at the one your launcher already has, or set `accept_download = true` to let
    BlueMap download it from Mojang (which means accepting the Minecraft EULA).
    """

    java: Path | None = None
    """Java 25+ for BlueMap 5.17 and later; default: `java` on PATH."""
    jar: Path | None = None
    """The BlueMap CLI jar (bluemap-<version>-cli.jar)."""
    client_jar: Path | None = None
    """A Minecraft client jar, e.g. <launcher>/versions/26.3/26.3.jar."""
    accept_download: bool = False
    """Let BlueMap download the client jar; you accept Mojang's EULA by setting this."""
    mc_version: str | None = None
    """Resource version for BlueMap; default: taken from client_jar, else BlueMap's latest."""
    threads: int = Field(default=0, ge=-64, le=256)
    """Render threads; 0 or negative = all cores minus that many."""
    pad: int = Field(default=32, ge=0, le=512)
    """Blocks of surroundings rendered around every build site."""
    spawn_radius: int = Field(default=96, ge=16, le=1024)
    """Worlds without a build site get this area around their spawn point."""
    max_side: int = Field(default=2048, ge=64, le=16384)
    """Largest area rendered per build site, in blocks per side."""

    @field_validator("java", "jar", "client_jar")
    @classmethod
    def _expand_paths(cls, v: Path | None) -> Path | None:
        return _expand(v) if v is not None else None


def _key(path: Path) -> str:
    real = os.path.realpath(path)
    return real.casefold() if sys.platform in {"darwin", "win32"} else real


def _overlap(a: Path, b: Path) -> bool:
    ka, kb = _key(a), _key(b)
    return ka == kb or ka.startswith(kb + os.sep) or kb.startswith(ka + os.sep)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MCATLAS_", env_nested_delimiter="__", extra="forbid"
    )

    language: Language = "en"
    """What people read: the site's default language (switchable on the site), the atlas and
    the 3D map markers. "en" or "nl"."""
    sources: list[SourceSettings] = Field(min_length=1)
    paths: PathSettings
    players: PlayerSettings = Field(default_factory=PlayerSettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    serve: ServeSettings = Field(default_factory=ServeSettings)

    @model_validator(mode="after")
    def _no_overlap(self) -> Self:
        ids = [s.id for s in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("source ids must be unique")
        for source in self.sources:
            for name, out in self.paths.outputs().items():
                if _overlap(source.path, out):
                    raise ValueError(
                        f"paths.{name} ({out}) overlaps source {source.id!r} ({source.path}); "
                        "outputs must live outside the world archive"
                    )
        return self

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        config_file = _CONFIG_FILE.get()
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if config_file is not None:
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=config_file))
        return tuple(sources)


def find_config_file(explicit: Path | None) -> Path | None:
    """An explicitly chosen file (--config or $MCATLAS_CONFIG) must exist: never fall back."""
    env = os.environ.get("MCATLAS_CONFIG")
    chosen = explicit or (Path(env) if env else None)
    if chosen is not None:
        if not chosen.expanduser().is_file():
            raise ConfigError(f"config file not found: {chosen}")
        return chosen.expanduser()
    for candidate in (Path("mcatlas.toml"), USER_CONFIG.expanduser()):
        if candidate.is_file():
            return candidate
    return None


def load_settings(config_file: Path | None = None) -> tuple[Settings, Path | None]:
    path = find_config_file(config_file)
    token = _CONFIG_FILE.set(path)
    try:
        return Settings(), path  # pyright: ignore[reportCallIssue] - fields come from sources
    finally:
        _CONFIG_FILE.reset(token)


# ---------- a first config file (`mcatlas init`) ----------


@dataclass(frozen=True, slots=True)
class InitAnswers:
    language: Language
    worlds: Path
    state_dir: Path
    site_dir: Path
    atlas_dir: Path | None
    timezone: str
    usercache: Path | None = None
    render_dir: Path | None = None
    java: Path | None = None
    jar: Path | None = None
    client_jar: Path | None = None


def _toml_path(path: Path) -> str:
    """A quoted TOML string; paths under the home folder are written with ~."""
    text = str(path.expanduser())
    home = str(Path.home())
    if text == home or text.startswith(home + os.sep):
        text = "~" + text[len(home) :]
    return json.dumps(text, ensure_ascii=False)


def _optional(key: str, path: Path | None, hint: str) -> str:
    return f"{key} = {_toml_path(path)}" if path is not None else f'# {key} = "{hint}"'


def config_text(a: InitAnswers) -> str:
    """A commented config file for these answers (what `mcatlas init` writes)."""
    atlas = _optional("atlas_dir", a.atlas_dir, "/path/next/to/the/archive/worlds_atlas")
    render = _optional("render_dir", a.render_dir, "/path/with/space/mcatlas/render")
    usercache = f"[{_toml_path(a.usercache)}]" if a.usercache is not None else "[]"
    return f"""\
# mcatlas configuration, written by `mcatlas init`. Edit freely; `mcatlas doctor` checks it.
# All options with explanations: mcatlas.example.toml in the mcatlas repository.

# Language of what people read: the site's default (switchable on the site), the atlas and
# the 3D map markers. "en" or "nl".
language = {json.dumps(a.language)}

# The worlds. mcatlas only ever READS below this folder.
[[sources]]
id = "archive"
path = {_toml_path(a.worlds)}
archives = ["*.zip"]        # worlds inside zip files are read in place, never extracted

[paths]
# Local and small: the analysis cache and the manifests that prove the archive is unchanged.
state_dir = {_toml_path(a.state_dir)}
# The catalog website.
site_dir = {_toml_path(a.site_dir)}
# 3D maps: BlueMap's workspace (copies of the files it renders, tiles, the viewer).
{render}
# Durable output next to (never inside) the archive: the atlas, and your notes in annotations/.
{atlas}

[players]
# The launcher's list of player names (read-only).
usercache = {usercache}

[players.names]
# Names for players the launcher does not know, by UUID:
# "0b0e0b0e-0000-4000-8000-000000000003" = "Noor"

[analysis]
timezone = {json.dumps(a.timezone)}   # turns timestamps into calendar days

[render]
# BlueMap CLI (https://github.com/BlueMap-Minecraft/BlueMap/releases) and Java 25 to run it.
{_optional("java", a.java, "/path/to/java")}
{_optional("jar", a.jar, "/path/to/bluemap-cli.jar")}
# Textures from the client jar your Minecraft launcher already has.
{_optional("client_jar", a.client_jar, "/path/to/minecraft/versions/1.21.5/1.21.5.jar")}
"""


def validate_config_text(text: str) -> Settings:
    """Parse and validate a config file's text the same way loading it would."""
    data = cast("dict[str, object]", tomllib.loads(text))
    return Settings.model_validate(data)
