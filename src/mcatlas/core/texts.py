"""Find the words players left behind: signs, books, names and commands.

Texts are found by walking block entities, entities and player inventories recursively, so a
book inside a shulker box inside a chest is found too. Both item formats are understood:
`tag` (before 1.20.5) and `components` (1.20.5+), and text as JSON strings (before 1.21.5) or
as NBT compounds (1.21.5+).
"""

import json
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast

import numpy as np

from mcatlas.core import nbt

MAX_TEXT: Final = 4000
"""Characters kept per text (a long book is truncated)."""
_SIGN_IDS: Final = ("sign", "hanging_sign")


class TextKind(StrEnum):
    SIGN = "sign"
    BOOK = "book"
    NAME = "name"
    COMMAND = "command"


@dataclass(frozen=True, slots=True)
class FoundText:
    kind: TextKind
    text: str
    holder: str
    """What holds it: block entity or entity id (chest, oak_sign, wolf, player, ...)."""
    x: int | None = None
    y: int | None = None
    z: int | None = None


def _plain(value: object) -> str:
    """Flatten a text component (already parsed JSON or NBT) to plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain(v) for v in cast("list[object]", value))
    if isinstance(value, dict):
        d = cast("dict[str, object]", value)
        own = d.get("text", d.get("", ""))
        return _plain(own) + _plain(d.get("extra", []))
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return ""


def component_text(value: nbt.NbtValue | None) -> str:
    """Plain text of a text component stored as JSON string, raw string or NBT."""
    if value is None or isinstance(value, np.ndarray):
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in {"{", "[", '"'}:
            try:
                return _plain(cast("object", json.loads(stripped))).strip()
            except json.JSONDecodeError:
                return stripped
        return stripped
    return _plain(value).strip()


def _short_id(value: nbt.NbtValue | None) -> str:
    return value.removeprefix("minecraft:") if isinstance(value, str) else "?"


def _raw(value: nbt.NbtValue | None) -> nbt.NbtValue | None:
    """Book pages and titles in 1.20.5+ are {raw: ..., filtered: ...}."""
    if isinstance(value, dict) and "raw" in value:
        return value["raw"]
    return value


def _book(content: nbt.NbtCompound, *, written: bool) -> str:
    pages = content.get("pages")
    texts: list[str] = []
    if isinstance(pages, list):
        for page in pages:
            raw = _raw(page)
            texts.append(component_text(raw) if written else (raw if isinstance(raw, str) else ""))
    title = component_text(_raw(content.get("title")))
    author = component_text(content.get("author"))
    head = " — ".join(p for p in (title, f"door {author}" if author else "") if p)
    body = "\n".join(t for t in texts if t)
    return "\n".join(p for p in (head, body) if p)[:MAX_TEXT]


def _texts_in(value: nbt.NbtValue, holder: str, depth: int = 0) -> Iterator[tuple[TextKind, str]]:
    """Recursively yield texts found anywhere below one block entity / entity / inventory."""
    if depth > 64:
        return
    if isinstance(value, list):
        for v in value:
            yield from _texts_in(v, holder, depth + 1)
        return
    if not isinstance(value, dict):
        return
    yield from _own_texts(value)
    for key, child in value.items():
        if key not in {"display", "CustomName", "minecraft:custom_name", "pages"} and isinstance(
            child, dict | list
        ):
            yield from _texts_in(child, holder, depth + 1)


def _own_texts(value: nbt.NbtCompound) -> Iterator[tuple[TextKind, str]]:
    """Texts stored directly on one compound (not in its children)."""
    # Books: old format keeps pages in the item's tag, new format in a component.
    written = value.get("minecraft:written_book_content")
    writable = value.get("minecraft:writable_book_content")
    if isinstance(written, dict):
        yield TextKind.BOOK, _book(written, written=True)
    elif isinstance(writable, dict):
        yield TextKind.BOOK, _book(writable, written=False)
    elif isinstance(value.get("pages"), list):
        yield TextKind.BOOK, _book(value, written="title" in value or "author" in value)
    # Names: entities and block entities, old item display names, new item components.
    display = value.get("display")
    names = [value.get("CustomName"), value.get("minecraft:custom_name")]
    if isinstance(display, dict):
        names.append(display.get("Name"))
    for raw in names:
        name = component_text(raw)
        if name:
            yield TextKind.NAME, name
    command = value.get("Command")
    if isinstance(command, str) and command.strip():
        yield TextKind.COMMAND, command.strip()[:MAX_TEXT]
    if _short_id(value.get("id")).endswith(_SIGN_IDS):
        lines = _sign_lines(value)
        if lines:
            yield TextKind.SIGN, lines


def _sign_lines(sign: nbt.NbtCompound) -> str:
    lines: list[str] = []
    for side in ("front_text", "back_text"):
        text = sign.get(side)
        if isinstance(text, dict):
            messages = text.get("messages")
            if isinstance(messages, list):
                lines.extend(component_text(m) for m in messages)
    lines.extend(component_text(sign.get(key)) for key in ("Text1", "Text2", "Text3", "Text4"))
    return " / ".join(line for line in lines if line)[:MAX_TEXT]


def _position(value: nbt.NbtCompound) -> tuple[int | None, int | None, int | None]:
    x, y, z = value.get("x"), value.get("y"), value.get("z")
    if isinstance(x, int) and isinstance(y, int) and isinstance(z, int):
        return x, y, z
    pos = value.get("Pos")
    if isinstance(pos, list) and len(pos) == 3:
        coords = [math.floor(p) for p in pos if isinstance(p, int | float)]
        if len(coords) == 3:
            return coords[0], coords[1], coords[2]
    return None, None, None


def texts_of(holder: nbt.NbtCompound, *, holder_name: str | None = None) -> list[FoundText]:
    """All texts in one block entity, entity or player compound, located at its position."""
    name = holder_name or _short_id(holder.get("id"))
    x, y, z = _position(holder)
    seen: set[tuple[TextKind, str]] = set()
    found: list[FoundText] = []
    for kind, text in _texts_in(holder, name):
        if text and (kind, text) not in seen:
            seen.add((kind, text))
            found.append(FoundText(kind, text, name, x, y, z))
    return found


_FORMATTING: Final = re.compile("§.")
DEFAULT_NAMES: Final = frozenset({"@"})
"""Names the game gives by itself (command blocks are called "@")."""


def clean(text: str) -> str:
    """Drop § colour codes and surrounding whitespace."""
    return _FORMATTING.sub("", text).strip()


def worth_keeping(kind: str, text: str) -> bool:
    """Skip default names and single-letter names (letters on banners spelling a word)."""
    return not (kind == TextKind.NAME and (text in DEFAULT_NAMES or len(text) < 2)) and bool(text)
