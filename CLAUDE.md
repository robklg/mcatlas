# mcatlas: notes for Claude Code

A read-only catalog, 3D-map renderer and durable atlas for an archive of Minecraft Java worlds.
Read README.md for what it does; this file holds the rules for changing it.

## The one hard rule: the worlds are never modified

- Only `adapters/source_folder.py` and `adapters/source_zip.py` (via `adapters/readonly.py`)
  read world files. Never add another way in, and never give them a write method.
- `core` has no NBT or region *writer*, and no function or class with write, save, dump or
  encode in its name (`tests/test_architecture.py` enforces this).
- Every file mcatlas writes goes through `adapters/outputs.py` (`atomic_write`,
  `write_if_changed`, `remove`), which calls `guard.check_output_path`. The audit hook in
  `adapters/guard.py` is a safety net, not the mechanism.
- External programs (BlueMap) never get a path into a source: copy what they need through
  the read-only source into their own workspace first.
- No mount, remount or other OS-level code: the user mounts the share themselves.
- The atlas export never writes into the notes folder (`annotations/`); notes are only
  written on an explicit user action (`mcatlas note`, the site's note editor).
- After anything that touches the real archive, run `mcatlas verify`.

## Architecture

Light hexagonal, enforced by import-linter (`.importlinter`):
`cli > config > (app | adapters) > ports > core`.

- `core`: pure. No `os`, `pathlib`, `shutil`, `io`, `subprocess`, `sqlite3`, `rich`, ...
- `app`: one plain function per use case, talking to the outside only through `ports.py`.
- `adapters`: implementations of the ports. `cli.py` is the only composition root.
- No data paths in code: everything comes from configuration (`mcatlas.example.toml`).
- Pydantic models for persisted facts; frozen dataclasses and numpy in hot loops.

## Checks (all must pass before a commit)

```sh
uv run pytest            # typeguard on every call; includes the read-only pipeline test
uv run basedpyright      # strict, reportAny on: 0 errors
uv run ruff check && uv run ruff format --check
uv run lint-imports
```

Extend `tests/test_readonly_pipeline.py` when a command gains a new way to read sources or
write output: it runs everything against a `chmod`-read-only fixture and compares manifests.

## Conventions

- Code, comments, docs and commit messages in English. Text people see on the site and in the
  atlas is Dutch.
- Match the surrounding code: docstrings explain *why*, names are plain.
- Commit only when asked. The history is public: never rewrite it or force-push without asking.

## Privacy: this repository is public

Never put real personal data in code, tests, docs or commit messages: no real player names,
account names or UUIDs, no world or folder names from the real archive, no names of private
servers, no personal paths. Test fixtures use fictional players (Sam, Alex, Noor; accounts
SamCraft2024, AlexCraft2020) and obviously fake UUIDs (`a1e0a1e0-0000-4000-8000-...`).
Private context, if present, is in `CLAUDE.local.md`, which is git-ignored and must stay so.
