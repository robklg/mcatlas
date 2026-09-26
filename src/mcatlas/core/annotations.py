"""Notes people keep about worlds, as plain Markdown files with TOML front matter.

One file per world, readable and editable without mcatlas::

    +++
    world = "trein-statjon-faa7dc"
    folder = "trein statjon"
    title = "Sams treinstation"
    tags = ["gevonden", "trein"]
    rating = 5
    updated = 2026-09-26T18:00:00+02:00
    +++

    Gevonden via de bordjes op de perrons.

`world` ties the file to a world, so files may be renamed freely; `folder` is there for people.
"""

import json
import re
import tomllib
from datetime import datetime
from typing import Final, cast

from pydantic import Field, field_validator

from mcatlas.core.facts import Facts
from mcatlas.core.model import WorldId

FENCE: Final = "+++"
MAX_NOTE: Final = 100_000
_TAG: Final = re.compile(r"^[\w][\w -]{0,39}$")


class AnnotationError(ValueError):
    """A file that is not a valid annotation."""


class Annotation(Facts):
    world: WorldId
    folder: str = ""
    title: str = ""
    tags: list[str] = Field(default_factory=list[str])
    rating: int | None = Field(default=None, ge=1, le=5)
    updated: datetime | None = None
    note: str = Field(default="", max_length=MAX_NOTE)
    """Free Markdown text."""

    @field_validator("title", "folder")
    @classmethod
    def _one_line(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(" ".join(t.split()).lower() for t in v if t.strip()))
        bad = [t for t in cleaned if not _TAG.match(t)]
        if bad:
            raise ValueError(f"tags may hold letters, digits, spaces and dashes only: {bad}")
        return cleaned

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return v.replace("\r\n", "\n").strip("\n")

    @property
    def is_empty(self) -> bool:
        return not (self.title or self.tags or self.rating or self.note.strip())


def _toml_string(value: str) -> str:
    # A JSON string literal is a valid TOML basic string, once DEL is escaped too.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def format_annotation(a: Annotation) -> str:
    lines = [FENCE, f"world = {_toml_string(a.world)}"]
    if a.folder:
        lines.append(f"folder = {_toml_string(a.folder)}")
    if a.title:
        lines.append(f"title = {_toml_string(a.title)}")
    if a.tags:
        lines.append(f"tags = [{', '.join(_toml_string(t) for t in a.tags)}]")
    if a.rating is not None:
        lines.append(f"rating = {a.rating}")
    if a.updated is not None:
        lines.append(f"updated = {a.updated.isoformat(timespec='seconds')}")
    lines.append(FENCE)
    body = a.note.strip("\n")
    return "\n".join(lines) + "\n" + (f"\n{body}\n" if body else "")


def parse_annotation(text: str) -> Annotation:
    text = text.removeprefix("﻿").replace("\r\n", "\n")
    if not text.startswith(FENCE + "\n"):
        raise AnnotationError(f"must start with a {FENCE} line")
    end = text.find(f"\n{FENCE}", len(FENCE))
    if end < 0:
        raise AnnotationError(f"closing {FENCE} line not found")
    front = text[len(FENCE) + 1 : end + 1]
    rest = text[end + len(FENCE) + 1 :]
    if rest and not rest.startswith("\n"):
        raise AnnotationError(f"text after the closing {FENCE} must start on a new line")
    try:
        fields = cast("dict[str, object]", tomllib.loads(front))
    except tomllib.TOMLDecodeError as e:
        raise AnnotationError(f"front matter: {e}") from e
    unknown = set(fields) - {"world", "folder", "title", "tags", "rating", "updated"}
    if unknown:
        raise AnnotationError(f"unknown fields: {sorted(unknown)}")
    try:
        return Annotation.model_validate({**fields, "note": rest.strip("\n")})
    except ValueError as e:
        raise AnnotationError(str(e)) from e
