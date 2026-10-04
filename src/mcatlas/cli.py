"""Command-line interface and composition root: the only place adapters are wired to the app."""

import shutil
import sys
import webbrowser
from collections.abc import Mapping
from contextlib import nullcontext
from contextvars import ContextVar
from datetime import datetime
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated, cast

import click
import platformdirs
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mcatlas.adapters import environment, guard, manifest
from mcatlas.adapters.annotations_md import AnnotationStoreError, MarkdownAnnotations
from mcatlas.adapters.atlas_fs import AtlasFolderWriter
from mcatlas.adapters.bluemap import BlueMapRenderer, RenderError
from mcatlas.adapters.outputs import atomic_write
from mcatlas.adapters.serve import serve as make_server
from mcatlas.adapters.site_static import StaticSiteWriter
from mcatlas.adapters.source_folder import FolderSource
from mcatlas.adapters.store_sqlite import SqliteFactStore
from mcatlas.adapters.usercache import load_names
from mcatlas.adapters.workers import process_mapper
from mcatlas.app.analyze import AnalyzeOptions, analyze_sources
from mcatlas.app.annotations import NoteChange, change_from_form, find_world, save_note
from mcatlas.app.catalog import load_catalog, publish_site
from mcatlas.app.export import export_atlas
from mcatlas.app.render import RenderOptions, render_worlds
from mcatlas.config import (
    USER_CONFIG,
    ConfigError,
    InitAnswers,
    Settings,
    config_text,
    load_settings,
    validate_config_text,
)
from mcatlas.core.catalog import Catalog, WorldEntry
from mcatlas.core.discovery import classify
from mcatlas.core.facts import TextEntry
from mcatlas.core.formats.console import lce_player_uuid
from mcatlas.core.model import Language, WorldId, fold, serial_map

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Read-only catalog and explorer for an archive of Minecraft Java worlds.",
)
console = Console()
SEARCH_TEXTS_SHOWN = 8
err = Console(stderr=True)

ConfigOpt = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        help="Config file (default: $MCATLAS_CONFIG, ./mcatlas.toml, "
        "~/.config/mcatlas/config.toml)",
    ),
]


_config_file: ContextVar[Path | None] = ContextVar("mcatlas_cli_config", default=None)


def _settings() -> Settings:
    try:
        settings, _ = load_settings(_config_file.get())
    except (ConfigError, ValidationError) as e:
        err.print(f"[red]Configuration error:[/red] {e}")
        err.print("Start from mcatlas.example.toml and pass it with --config.")
        raise typer.Exit(2) from e
    # From here on, nothing in this process may modify the world sources.
    guard.protect(s.path for s in settings.sources)
    return settings


def _sources(settings: Settings) -> list[FolderSource]:
    return [
        FolderSource(
            s.id,
            s.path,
            archives=s.archives,
            exclude=s.exclude,
            jobs=settings.analysis.jobs,
            io_threads=settings.analysis.io_threads,
        )
        for s in settings.sources
    ]


def _store(settings: Settings) -> SqliteFactStore:
    return SqliteFactStore(settings.paths.state_dir / "mcatlas.sqlite")


def _names(settings: Settings) -> dict[str, str]:
    names = load_names(settings.players.usercache)
    names.update({lce_player_uuid(tag): name for tag, name in settings.players.gamertags.items()})
    names.update({k.lower(): v for k, v in settings.players.names.items()})
    return names


def _manifest_dir(settings: Settings) -> Path:
    return settings.paths.state_dir / "manifests"


def _renderer(settings: Settings) -> BlueMapRenderer | None:
    """The 3D renderer, when paths.render_dir is configured."""
    render_dir = settings.paths.render_dir
    if render_dir is None:
        return None
    r = settings.render
    return BlueMapRenderer(
        render_dir,
        java=r.java,
        jar=r.jar,
        client_jar=r.client_jar,
        accept_download=r.accept_download,
        mc_version=r.mc_version,
        threads=r.threads,
    )


def _size(n: int) -> str:
    value = float(n)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


@app.callback()
def main_callback(config: ConfigOpt = None) -> None:
    _config_file.set(config)


def _prompt(question: str, default: str | None = None, **options: object) -> str:
    answer = cast("object", typer.prompt(question, default=default, **options))  # pyright: ignore[reportArgumentType]
    return str(answer).strip()


def _ask_path(question: str, default: Path | None = None, *, must_exist: bool = False) -> Path:
    while True:
        answer = _prompt(question, str(default) if default is not None else None)
        path = Path(answer).expanduser().absolute()
        if not must_exist or path.is_dir():
            return path
        err.print(f"[yellow]Not a folder:[/] {path}")


def _ask_optional_file(question: str, default: Path | None) -> Path | None:
    answer = _prompt(question, str(default) if default else "", show_default=bool(default))
    return Path(answer).expanduser().absolute() if answer else None


@app.command()
def init(
    force: Annotated[
        bool, typer.Option(help="Replace an existing config file (a .bak copy is kept)")
    ] = False,
) -> None:
    """Create a config file by answering a few questions."""
    target = (_config_file.get() or USER_CONFIG).expanduser()
    if target.exists() and not force:
        err.print(f"[yellow]{target} already exists.[/] Edit it, or run `mcatlas init --force`.")
        raise typer.Exit(1)
    console.print(f"This writes [bold]{target}[/]. Press Enter to accept a suggestion.\n")
    chosen = _prompt(
        "Language of the site and the atlas",
        environment.language(),
        type=click.Choice(["en", "nl"]),
    )
    language: Language = "nl" if chosen == "nl" else "en"
    worlds = _ask_path("Folder with the Minecraft worlds (only ever read)", must_exist=True)
    base = _ask_path("Folder for the generated site and 3D maps", Path.home() / "mcatlas")
    atlas = _ask_path(
        "Folder for the durable atlas and your notes (next to the worlds, not inside)",
        worlds.parent / f"{worlds.name}_atlas",
    )
    render_dir = java = jar = client_jar = None
    if typer.confirm("Make 3D maps with BlueMap? (needs Java 25 and the BlueMap CLI jar)"):
        render_dir = base / "render"
        java = _ask_optional_file("Java 25", environment.java())
        jar = _ask_optional_file("BlueMap CLI jar (download: github.com/BlueMap-Minecraft)", None)
        client_jar = _ask_optional_file(
            "Minecraft client jar (for textures)", environment.client_jar()
        )
    answers = InitAnswers(
        language=language,
        worlds=worlds,
        state_dir=platformdirs.user_state_path("mcatlas"),
        site_dir=base / "site",
        atlas_dir=atlas,
        timezone=environment.timezone(),
        usercache=environment.usercache(),
        render_dir=render_dir,
        java=java,
        jar=jar,
        client_jar=client_jar,
    )
    text = config_text(answers)
    try:
        validate_config_text(text)
    except ValidationError as e:
        err.print(f"[red]These answers do not work:[/] {e}")
        raise typer.Exit(2) from e
    # From here on nothing may write into the worlds folder, this config file included.
    guard.protect([worlds])
    if target.exists():
        atomic_write(target.with_name(target.name + ".bak"), target.read_bytes())
    atomic_write(target, text.encode())
    console.print(f"\n[green]Written:[/] {target}")
    console.print(
        f"Time zone {answers.timezone}; player names from {answers.usercache or 'nowhere yet'}."
    )
    if render_dir is not None and (jar is None or client_jar is None):
        console.print("[yellow]For 3D maps, fill in render.jar and render.client_jar later.[/]")
    console.print(
        "\nNext:\n"
        "  uv run mcatlas doctor            # check the configuration\n"
        "  uv run mcatlas snapshot          # record the archive, to prove later nothing changed\n"
        "  uv run mcatlas analyze --tier 2  # analyze every world\n"
        "  uv run mcatlas build-site        # write the catalog site\n"
        "  uv run mcatlas serve             # open it on http://127.0.0.1:8765"
    )


@app.command()
def doctor() -> None:
    """Check configuration, paths and prerequisites."""
    settings = _settings()
    ok = True
    table = Table("check", "status", "detail", show_header=False, box=None)
    for s in settings.sources:
        readable = s.path.is_dir()
        ok &= readable
        table.add_row(
            f"source {s.id}", "[green]ok[/]" if readable else "[red]missing[/]", str(s.path)
        )
    table.add_row("outputs vs sources", "[green]ok[/]", "no overlap (validated)")
    for name, path in settings.paths.outputs().items():
        parent = next((p for p in [path, *path.parents] if p.exists()), None)
        table.add_row(f"paths.{name}", "[green]ok[/]" if parent else "[yellow]?[/]", str(path))
    state_free = shutil.disk_usage(
        next(p for p in [settings.paths.state_dir, *settings.paths.state_dir.parents] if p.exists())
    ).free
    table.add_row(
        "free space (state)",
        "[green]ok[/]" if state_free > 200e6 else "[yellow]low[/]",
        _size(state_free),
    )
    names = _names(settings)
    table.add_row("known player names", "[green]ok[/]", str(len(names)))
    for s in settings.sources:
        latest = manifest.latest(_manifest_dir(settings), s.id)
        table.add_row(
            f"manifest {s.id}",
            "[green]ok[/]" if latest else "[yellow]none[/]",
            latest.name if latest else "run `mcatlas snapshot` before the first analysis",
        )
    table.add_row("timezone", "[green]ok[/]", settings.analysis.timezone)
    if settings.paths.render_dir is not None:
        r = settings.render
        java = str(r.java) if r.java else shutil.which("java")
        for label, value in (("java", java), ("jar", r.jar), ("client_jar", r.client_jar)):
            present = value is not None and Path(value).is_file()
            status = "[green]ok[/]" if present else "[yellow]missing[/]"
            detail = str(value)
            if label == "client_jar" and value is None:
                status = "[green]ok[/]" if r.accept_download else "[yellow]none[/]"
                detail = (
                    "BlueMap downloads it (EULA accepted)"
                    if r.accept_download
                    else "set render.client_jar (or accept_download) before `mcatlas render`"
                )
            table.add_row(f"render.{label}", status, detail)
    console.print(table)
    if not ok:
        raise typer.Exit(1)


@app.command()
def snapshot(
    quick: Annotated[bool, typer.Option(help="Record size+mtime only, no content hashes")] = False,
) -> None:
    """Record a manifest of every source (the baseline for `verify`)."""
    settings = _settings()
    for s in settings.sources:
        console.print(
            f"Snapshot of [bold]{s.id}[/] ({s.path}) {'without' if quick else 'with'} hashes …"
        )

        def progress(done: int, total: int) -> None:
            if done % 200 == 0 or done == total:
                console.print(f"  hashed {done}/{total}", highlight=False)

        m = manifest.take(
            s.id,
            s.path,
            hashed=not quick,
            jobs=settings.analysis.jobs,
            io_threads=settings.analysis.io_threads,
            progress=progress,
        )
        path = manifest.save(m, _manifest_dir(settings))
        info = manifest.summary(m)
        console.print(f"  {info['files']} files, {_size(info['bytes'])} → {path}")


@app.command()
def verify(
    full: Annotated[
        bool, typer.Option(help="Re-hash contents (slow) instead of size+mtime")
    ] = False,
) -> None:
    """Prove that no source changed since the last snapshot."""
    settings = _settings()
    clean = True
    for s in settings.sources:
        latest = manifest.latest(_manifest_dir(settings), s.id)
        if latest is None:
            err.print(f"[yellow]{s.id}: no snapshot yet; run `mcatlas snapshot` first[/]")
            clean = False
            continue
        old = manifest.load(latest)
        new = manifest.take(
            s.id,
            s.path,
            hashed=full and old.header.hashed,
            jobs=settings.analysis.jobs,
            io_threads=settings.analysis.io_threads,
        )
        diff = manifest.compare(old, new)
        if diff.clean:
            console.print(
                f"[green]{s.id}: unchanged[/] since {old.header.created_at:%Y-%m-%d %H:%M} "
                f"({manifest.summary(new)['files']} files{', contents re-hashed' if full else ''})"
            )
            continue
        clean = False
        console.print(f"[red]{s.id}: CHANGED since {old.header.created_at:%Y-%m-%d %H:%M}[/]")
        for label, paths in (
            ("added", diff.added),
            ("removed", diff.removed),
            ("changed", diff.changed),
        ):
            for p in paths[:50]:
                console.print(f"  {label}: {p}", highlight=False)
            if len(paths) > 50:
                console.print(f"  … and {len(paths) - 50} more {label}")
    if not clean:
        raise typer.Exit(1)


@app.command()
def inventory() -> None:
    """List every world found in the sources, without analyzing them."""
    settings = _settings()
    table = Table("folder", "format", "dimensions", "files", "size", "id")
    count = 0
    for source in _sources(settings):
        for listing in source.scan():
            layout = classify(listing.files)
            dims = ", ".join(
                f"{d.key.removeprefix('minecraft:')}({len(d.region_files)})"
                for d in layout.dimensions
            )
            table.add_row(
                listing.relpath,
                layout.format.value,
                dims[:60],
                str(len(listing.files)),
                _size(listing.total_size),
                listing.world_id,
            )
            count += 1
    console.print(table)
    console.print(f"{count} entries")


@app.command()
def analyze(
    tier: Annotated[
        int,
        typer.Option(
            min=1, max=2, help="1: metadata and region headers; 2: also every chunk (blocks)"
        ),
    ] = 1,
    world: Annotated[
        str | None, typer.Option("--world", "-w", help="Glob on folder name/path")
    ] = None,
    force: Annotated[bool, typer.Option(help="Ignore the cache and re-analyze")] = False,
    jobs: Annotated[int | None, typer.Option(min=1, max=64)] = None,
) -> None:
    """Analyze worlds (incremental: unchanged worlds are skipped)."""
    settings = _settings()
    store = _store(settings)
    try:
        options = AnalyzeOptions(
            tier=tier, world_glob=world, force=force, jobs=jobs or settings.analysis.jobs
        )
        processes = settings.analysis.processes
        with (
            process_mapper(processes)
            if tier >= 2 and processes > 1
            else nullcontext(serial_map) as mapper
        ):
            report = analyze_sources(
                _sources(settings),
                store,
                options,
                progress=lambda m: console.print(m, highlight=False),
                mapper=mapper,
            )
    finally:
        store.close()
    summary = f"[bold]{report.worlds}[/] worlds: {report.analyzed} analyzed"
    summary += f", {report.up_to_date} up to date"
    if report.forgotten:
        summary += f", {report.forgotten} no longer present"
    console.print(summary)
    for folder, analyzer, error in report.failures:
        console.print(f"  [yellow]{folder}[/] {analyzer}: {error}", highlight=False)


@app.command("build-site")
def build_site(
    open_browser: Annotated[bool, typer.Option("--open", help="Open the site afterwards")] = False,
) -> None:
    """Generate the static catalog site from the analysis results."""
    settings = _settings()
    store = _store(settings)
    try:
        catalog, location, problems = publish_site(
            store,
            StaticSiteWriter(settings.paths.site_dir, language=settings.language),
            _names(settings),
            settings.analysis.zone(),
            ignore_file_days=settings.analysis.ignore_file_days,
            notes=_notes(settings),
            renderer=_renderer(settings),
        )
    finally:
        store.close()
    console.print(
        f"{len(catalog.worlds)} worlds, {len(catalog.annotations)} notes, "
        f"{sum(len(m) for m in catalog.renders.values())} 3D maps → {location}"
    )
    _report_note_problems(problems)
    if open_browser:
        webbrowser.open(Path(location).as_uri())


@app.command()
def serve(
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
    host: Annotated[
        str, typer.Option(help="Bind address; keep 127.0.0.1 unless you mean it")
    ] = "127.0.0.1",
    allow_host: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-host",
            help="Also accept notes for this Host header, e.g. the name a reverse proxy "
            "serves the site under (repeatable; adds to [serve] allowed_hosts)",
        ),
    ] = None,
) -> None:
    """Serve the generated site on http://HOST:PORT; notes can be edited on the site."""
    settings = _settings()
    notes = _notes(settings)
    by_id = {e.world_id: e for e in _load(settings).worlds}
    site = StaticSiteWriter(settings.paths.site_dir, language=settings.language)

    def on_note(world_id: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        entry = by_id[WorldId(world_id)]
        annotation, where = save_note(
            notes, entry, change_from_form(payload), datetime.now().astimezone(), site
        )
        console.print(f"note saved: {entry.folder_name} → {where}", highlight=False)
        return {"annotation": annotation.model_dump(mode="json"), "stored": where}

    can_write = settings.paths.annotations() is not None
    render_dir = settings.paths.render_dir
    web_3d = render_dir / "web" if render_dir is not None else None
    atlas_dir = settings.paths.atlas_dir
    # Read-only extra folders; the site links to them when they answer.
    extra: dict[str, Path] = {}
    if web_3d is not None:
        extra["3d"] = web_3d
    if atlas_dir is not None and (atlas_dir / "index.html").is_file():
        extra["atlas"] = atlas_dir
    server = make_server(
        settings.paths.site_dir,
        host,
        port,
        on_note=on_note if can_write else None,
        extra=extra,
        allowed_hosts=[*settings.serve.allowed_hosts, *(allow_host or [])],
    )
    console.print(f"Serving {settings.paths.site_dir} on http://{host}:{port}  (Ctrl-C to stop)")
    if web_3d is not None:
        console.print(f"3D maps (BlueMap) on http://{host}:{port}/3d/ from {web_3d}")
    if "atlas" in extra:
        console.print(f"Atlas on http://{host}:{port}/atlas/ from {atlas_dir}")
    if can_write:
        console.print(f"Notes are saved in {settings.paths.annotations()}")
        names = sorted(h for h in server.allowed_hosts if not h.endswith(f":{port}"))
        if names:
            console.print(f"Notes are also accepted via: {', '.join(names)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


@app.command()
def render(
    world: Annotated[
        str | None, typer.Option("--world", "-w", help="Glob on folder name/path")
    ] = None,
    force: Annotated[bool, typer.Option(help="Render again, also unchanged maps")] = False,
    check: Annotated[
        bool, typer.Option(help="Verify afterwards that the archive is unchanged")
    ] = True,
) -> None:
    """Render 3D maps (BlueMap) of the build sites; BlueMap only ever reads copies."""
    settings = _settings()
    renderer = _renderer(settings)
    if renderer is None:
        err.print("[red]Set paths.render_dir first[/] (a folder outside the archive).")
        raise typer.Exit(2)
    catalog = _load(settings)
    r = settings.render
    options = RenderOptions(
        world_glob=world,
        force=force,
        pad=r.pad,
        spawn_radius=r.spawn_radius,
        max_side=r.max_side,
        language=settings.language,
    )
    try:
        report = render_worlds(
            _sources(settings),
            catalog.worlds,
            renderer,
            options,
            progress=lambda m: console.print(m, highlight=False, markup=False, soft_wrap=True),
        )
    except RenderError as e:
        err.print(f"[red]Render failed:[/] {e}", highlight=False)
        raise typer.Exit(1) from e
    console.print(
        f"[bold]{report.maps}[/] maps: {report.rendered} rendered, {report.up_to_date} up to "
        f"date; copied {report.copied_files} files ({_size(report.copied_bytes)}), "
        f"{report.images} flat images"
    )
    for name, reason in report.skipped:
        console.print(f"  [dim]{name}: {reason}[/]", highlight=False)
    if report.rendered:
        store = _store(settings)
        try:
            _, location, _ = publish_site(
                store,
                StaticSiteWriter(settings.paths.site_dir, language=settings.language),
                _names(settings),
                settings.analysis.zone(),
                ignore_file_days=settings.analysis.ignore_file_days,
                notes=_notes(settings),
                renderer=renderer,
            )
        finally:
            store.close()
        console.print(f"site updated → {location}")
    if check:
        verify(full=False)


@app.command("export-atlas")
def export_atlas_command(
    check: Annotated[
        bool, typer.Option(help="Verify afterwards that the archive is unchanged")
    ] = False,
) -> None:
    """Write the durable atlas (Markdown, HTML, TOML, CSV, PNG) to paths.atlas_dir."""
    settings = _settings()
    atlas_dir = settings.paths.atlas_dir
    if atlas_dir is None:
        err.print("[red]Set paths.atlas_dir first[/] (a folder next to the archive).")
        raise typer.Exit(2)
    store = _store(settings)
    try:
        report = export_atlas(
            store,
            AtlasFolderWriter(atlas_dir, notes_dir=settings.paths.annotations()),
            _names(settings),
            settings.analysis.zone(),
            today=datetime.now(settings.analysis.zone()).date(),
            tool=f"mcatlas {package_version('mcatlas')}",
            ignore_file_days=settings.analysis.ignore_file_days,
            notes=_notes(settings),
            renderer=_renderer(settings),
            language=settings.language,
        )
    finally:
        store.close()
    w = report.written
    console.print(
        f"{report.worlds} worlds, {report.files} files ({report.images} images): "
        f"{w.written} written, {w.unchanged} unchanged, {w.removed} removed → {w.location}"
    )
    for problem in report.problems:
        err.print(f"[yellow]skipped[/] {problem}", highlight=False)
    if check:
        verify(full=False)


def _notes(settings: Settings) -> MarkdownAnnotations:
    return MarkdownAnnotations(settings.paths.annotations(), language=settings.language)


def _report_note_problems(problems: list[str]) -> None:
    for problem in problems:
        err.print(f"[yellow]note skipped[/] {problem}", highlight=False)


def _load(settings: Settings) -> Catalog:
    store = _store(settings)
    try:
        catalog, problems = load_catalog(
            store,
            _names(settings),
            settings.analysis.zone(),
            ignore_file_days=settings.analysis.ignore_file_days,
            notes=_notes(settings),
            renderer=_renderer(settings),
        )
    finally:
        store.close()
    _report_note_problems(problems)
    return catalog


def _load_entries(settings: Settings) -> list[WorldEntry]:
    return _load(settings).worlds


def _matches(entry: WorldEntry, text: str) -> bool:
    needle = fold(text)
    hay = [
        entry.name,
        entry.folder_name,
        entry.relpath,
        entry.world_id,
        *(p.name or "" for p in entry.players),
    ]
    if entry.annotation is not None:
        hay += [entry.annotation.title, entry.annotation.note, *entry.annotation.tags]
    return any(needle in fold(h) for h in hay if h)


@app.command()
def search(text: str) -> None:
    """Find worlds by (folder) name, path, player name, or text on signs, in books and names."""
    settings = _settings()
    catalog = _load(settings)
    needle = fold(text)
    table = Table("score", "name", "folder", "days", "period", "play h")
    hits: list[tuple[WorldEntry, list[TextEntry]]] = []
    for e in catalog.worlds:
        texts = [t for t in catalog.texts.get(e.world_id, []) if needle in t.text.casefold()]
        if texts:
            hits.append((e, texts))
        if _matches(e, text) or texts:
            a = e.activity
            period = f"{a.first_day} … {a.last_day}" if a.first_day else "–"
            table.add_row(
                f"{e.importance.score:.1f}",
                e.name,
                e.folder_name,
                str(a.distinct_days),
                period,
                f"{e.play_hours:.1f}",
            )
    console.print(table)
    for e, texts in hits:
        console.print(f"[bold]{e.name}[/] ({e.folder_name}): {len(texts)} text(s)", highlight=False)
        for t in texts[:SEARCH_TEXTS_SHOWN]:
            where = f"{t.x} {t.y} {t.z}" if t.x is not None else "-"
            flat = " ".join(t.text.split())
            console.print(f"  {t.kind:7} {t.holder:14} {where:18} {flat[:100]}", highlight=False)
        if len(texts) > SEARCH_TEXTS_SHOWN:
            console.print(f"  … {len(texts) - SEARCH_TEXTS_SHOWN} more", highlight=False)


@app.command()
def show(world: str) -> None:
    """Show everything known about one world (id, folder name or part of it)."""
    settings = _settings()
    matches = [e for e in _load_entries(settings) if _matches(e, world)]
    exact = [e for e in matches if fold(world) in (fold(e.world_id), fold(e.folder_name))]
    chosen = exact or matches
    if len(chosen) != 1:
        err.print(
            f"{len(chosen)} worlds match {world!r}: "
            + ", ".join(e.folder_name for e in chosen[:20])
        )
        raise typer.Exit(1)
    console.print_json(chosen[0].model_dump_json(exclude={"activity": {"days"}}))


@app.command()
def note(
    world: Annotated[str, typer.Argument(help="World id, folder name, name or part of it")],
    text: Annotated[
        str | None, typer.Argument(help="Text added as a new paragraph to the note")
    ] = None,
    title: Annotated[str | None, typer.Option(help="Short title for the world")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Add a tag")] = None,
    untag: Annotated[list[str] | None, typer.Option(help="Remove a tag")] = None,
    rating: Annotated[int | None, typer.Option(min=1, max=5, help="1 to 5 stars")] = None,
    replace: Annotated[bool, typer.Option(help="Replace the note text instead of adding")] = False,
) -> None:
    """Write a note about a world (stored as Markdown next to the archive).

    Example: mcatlas note "trein statjon" "Sams treinstation, gevonden via de bordjes" -t gevonden
    """
    settings = _settings()
    entries = _load_entries(settings)
    chosen = find_world(entries, world)
    if len(chosen) != 1:
        err.print(
            f"{len(chosen)} worlds match {world!r}: "
            + ", ".join(e.folder_name for e in chosen[:20])
        )
        raise typer.Exit(1)
    entry = chosen[0]
    change = NoteChange(
        title=title,
        note=text if replace else None,
        append=None if replace else text,
        add_tags=tag or [],
        remove_tags=untag or [],
        rating=rating,
    )
    try:
        annotation, where = save_note(
            _notes(settings),
            entry,
            change,
            datetime.now().astimezone(),
            StaticSiteWriter(settings.paths.site_dir, language=settings.language),
        )
    except (AnnotationStoreError, ValueError) as e:
        err.print(f"[red]{e}[/]")
        raise typer.Exit(1) from e
    console.print(f"[bold]{entry.name}[/] ({entry.folder_name}) → {where}", highlight=False)
    if annotation.title:
        console.print(f"  titel: {annotation.title}", highlight=False)
    if annotation.tags:
        console.print(f"  tags:  {', '.join(annotation.tags)}", highlight=False)
    if annotation.note:
        console.print(annotation.note, highlight=False)


@app.command()
def notes() -> None:
    """List all notes."""
    settings = _settings()
    catalog = _load(settings)
    names = {e.world_id: e for e in catalog.worlds}
    table = Table("world", "title", "tags", "rating", "updated", "note")
    for a in sorted(catalog.annotations.values(), key=lambda a: a.updated or datetime.min):
        entry = names.get(a.world)
        world = entry.name if entry else f"{a.folder or a.world} (not in archive)"
        first = a.note.splitlines()[0] if a.note else ""
        table.add_row(
            world,
            a.title,
            ", ".join(a.tags),
            "★" * (a.rating or 0),
            a.updated.strftime("%Y-%m-%d") if a.updated else "",
            first[:60],
        )
    console.print(table)
    console.print(f"{len(catalog.annotations)} notes in {settings.paths.annotations()}")


def main() -> None:
    if sys.platform == "win32":  # pragma: no cover
        err.print("mcatlas is developed for macOS/Linux; Windows is untested.")
    app()
