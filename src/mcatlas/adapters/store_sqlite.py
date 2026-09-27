"""SQLite-backed fact store. Lives in the local state directory, never next to the worlds."""

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from mcatlas.adapters.guard import check_output_path
from mcatlas.core.catalog import StoredWorld
from mcatlas.core.model import WorldFormat, WorldId, WorldLayout, WorldListing

_MIGRATIONS: Final = (
    """
    CREATE TABLE worlds (
        world_id    TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL,
        relpath     TEXT NOT NULL,
        folder_name TEXT NOT NULL,
        format      TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        total_size  INTEGER NOT NULL,
        files       INTEGER NOT NULL,
        seen_at     TEXT NOT NULL
    );
    CREATE TABLE facts (
        world_id    TEXT NOT NULL REFERENCES worlds ON DELETE CASCADE,
        analyzer    TEXT NOT NULL,
        version     INTEGER NOT NULL,
        fingerprint TEXT NOT NULL,
        payload     TEXT,
        error       TEXT,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (world_id, analyzer)
    );
    CREATE TABLE assets (
        world_id    TEXT NOT NULL REFERENCES worlds ON DELETE CASCADE,
        name        TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        data        BLOB NOT NULL,
        PRIMARY KEY (world_id, name)
    );
    """,
)

type _Row = tuple[str | int | bytes | None, ...]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SqliteFactStore:
    def __init__(self, path: Path) -> None:
        real = check_output_path(path)
        real.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(real)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        (current,) = cast("tuple[int]", self._db.execute("PRAGMA user_version").fetchone())
        for version, script in enumerate(_MIGRATIONS[current:], start=current + 1):
            with self._db:
                self._db.executescript(script)
                self._db.execute(f"PRAGMA user_version = {version}")

    def _rows(self, sql: str, params: Sequence[object] = ()) -> list[_Row]:
        return cast("list[_Row]", self._db.execute(sql, params).fetchall())

    def record_world(self, listing: WorldListing, layout: WorldLayout) -> None:
        with self._db:
            self._db.execute(
                """
                INSERT INTO worlds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (world_id) DO UPDATE SET
                    format = excluded.format, fingerprint = excluded.fingerprint,
                    total_size = excluded.total_size, files = excluded.files,
                    seen_at = excluded.seen_at
                """,
                (
                    listing.world_id,
                    listing.source_id,
                    listing.relpath,
                    listing.folder_name,
                    layout.format.value,
                    listing.fingerprint(),
                    listing.total_size,
                    len(listing.files),
                    _now(),
                ),
            )

    def forget_missing(self, source_id: str, present: set[WorldId]) -> int:
        known = {
            str(r[0])
            for r in self._rows("SELECT world_id FROM worlds WHERE source_id = ?", (source_id,))
        }
        gone = sorted(known - present)
        with self._db:
            self._db.executemany("DELETE FROM worlds WHERE world_id = ?", [(g,) for g in gone])
        return len(gone)

    def is_current(self, world_id: WorldId, analyzer: str, version: int, fingerprint: str) -> bool:
        rows = self._rows(
            "SELECT 1 FROM facts"
            " WHERE world_id = ? AND analyzer = ? AND version = ? AND fingerprint = ?",
            (world_id, analyzer, version, fingerprint),
        )
        return bool(rows)

    def save_facts(
        self,
        world_id: WorldId,
        analyzer: str,
        version: int,
        fingerprint: str,
        *,
        payload: str | None,
        error: str | None,
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (world_id, analyzer, version, fingerprint, payload, error, _now()),
            )

    def has_asset(self, world_id: WorldId, name: str, fingerprint: str) -> bool:
        rows = self._rows(
            "SELECT 1 FROM assets WHERE world_id = ? AND name = ? AND fingerprint = ?",
            (world_id, name, fingerprint),
        )
        return bool(rows)

    def save_asset(self, world_id: WorldId, name: str, fingerprint: str, data: bytes) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO assets VALUES (?, ?, ?, ?)",
                (world_id, name, fingerprint, data),
            )

    def assets(self, name: str) -> Mapping[WorldId, bytes]:
        rows = self._rows("SELECT world_id, data FROM assets WHERE name = ?", (name,))
        return {WorldId(str(r[0])): cast("bytes", r[1]) for r in rows}

    def replace_assets(
        self, world_id: WorldId, prefix: str, fingerprint: str, data: Mapping[str, bytes]
    ) -> None:
        with self._db:
            self._db.execute(
                "DELETE FROM assets WHERE world_id = ? AND substr(name, 1, ?) = ?",
                (world_id, len(prefix), prefix),
            )
            self._db.executemany(
                "INSERT INTO assets VALUES (?, ?, ?, ?)",
                [(world_id, prefix + name, fingerprint, blob) for name, blob in data.items()],
            )

    def asset_group(self, prefix: str) -> Mapping[WorldId, Mapping[str, bytes]]:
        found: dict[WorldId, dict[str, bytes]] = {}
        for world_id, name, blob in self._rows(
            "SELECT world_id, name, data FROM assets WHERE substr(name, 1, ?) = ? ORDER BY name",
            (len(prefix), prefix),
        ):
            found.setdefault(WorldId(str(world_id)), {})[str(name)[len(prefix) :]] = cast(
                "bytes", blob
            )
        return found

    def worlds(self) -> Sequence[StoredWorld]:
        facts: dict[str, dict[str, str]] = {}
        errors: dict[str, dict[str, str]] = {}
        for world_id, analyzer, payload, error in self._rows(
            "SELECT world_id, analyzer, payload, error FROM facts"
        ):
            if payload is not None:
                facts.setdefault(str(world_id), {})[str(analyzer)] = str(payload)
            if error is not None:
                errors.setdefault(str(world_id), {})[str(analyzer)] = str(error)
        icons = {
            str(r[0]) for r in self._rows("SELECT world_id FROM assets WHERE name = 'icon.png'")
        }
        return [
            StoredWorld(
                world_id=WorldId(str(wid)),
                source_id=str(source_id),
                relpath=str(relpath),
                folder_name=str(folder),
                format=WorldFormat(str(fmt)),
                fingerprint=str(fingerprint),
                total_size=int(cast("int", size)),
                facts=facts.get(str(wid), {}),
                errors=errors.get(str(wid), {}),
                has_icon_asset=str(wid) in icons,
            )
            for wid, source_id, relpath, folder, fmt, fingerprint, size in self._rows(
                "SELECT world_id, source_id, relpath, folder_name, format, fingerprint, total_size "
                "FROM worlds ORDER BY folder_name"
            )
        ]
