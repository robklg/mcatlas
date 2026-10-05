"""Change the note of one world: merge the requested changes into what is already stored."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from mcatlas.core.annotations import Annotation
from mcatlas.core.catalog import WorldEntry
from mcatlas.core.model import WorldId
from mcatlas.ports import AnnotationStore, SiteWriter


class NoteSubject(Protocol):
    """All a note needs of its world, so a stored world will do and no catalog is built."""

    @property
    def world_id(self) -> WorldId: ...

    @property
    def relpath(self) -> str: ...


@dataclass(frozen=True, slots=True)
class NoteChange:
    """Fields left None are kept as they are."""

    title: str | None = None
    note: str | None = None
    append: str | None = None
    """Added as a new paragraph below the existing note."""
    tags: Sequence[str] | None = None
    add_tags: Sequence[str] = ()
    remove_tags: Sequence[str] = ()
    rating: int | None = None
    clear_rating: bool = False


def apply_change(
    current: Annotation | None, entry: NoteSubject, change: NoteChange, now: datetime
) -> Annotation:
    base = current or Annotation(world=entry.world_id)
    note = base.note if change.note is None else change.note
    if change.append:
        note = f"{note.rstrip()}\n\n{change.append}" if note.strip() else change.append
    tags = list(base.tags if change.tags is None else change.tags)
    tags += [t for t in change.add_tags if t not in tags]
    removed = {t.lower() for t in change.remove_tags}
    tags = [t for t in tags if t.lower() not in removed]
    rating = None if change.clear_rating else (change.rating or base.rating)
    return Annotation(
        world=entry.world_id,
        folder=entry.relpath,
        title=base.title if change.title is None else change.title,
        tags=tags,
        rating=rating,
        updated=now,
        note=note,
    )


def save_note(
    notes: AnnotationStore,
    entry: NoteSubject,
    change: NoteChange,
    now: datetime,
    site: SiteWriter | None = None,
) -> tuple[Annotation, str]:
    """Store the changed note; refresh the site's notes file when a site writer is given."""
    current, _ = notes.load()
    updated = apply_change(current.get(entry.world_id), entry, change, now)
    where = notes.save(updated)
    if site is not None:
        refreshed, _ = notes.load()
        site.write_annotations(refreshed)
    return updated, where


def find_world(entries: Sequence[WorldEntry], query: str) -> list[WorldEntry]:
    """Worlds matching an id, folder, path or name; exact matches win over partial ones."""
    q = query.casefold()
    exact = [
        e
        for e in entries
        if q
        in {
            e.world_id.casefold(),
            e.folder_name.casefold(),
            e.relpath.casefold(),
            e.name.casefold(),
        }
    ]
    if exact:
        return exact
    return [e for e in entries if any(q in s.casefold() for s in (e.world_id, e.relpath, e.name))]


def note_index(annotations: Mapping[str, Annotation]) -> list[Annotation]:
    return sorted(annotations.values(), key=lambda a: a.updated or datetime.min.astimezone())


class NoteForm(BaseModel):
    """What the site's note editor sends: the complete new state of the note."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list[str])
    rating: int | None = Field(default=None, ge=1, le=5)


def change_from_form(payload: Mapping[str, object]) -> NoteChange:
    """Validate a posted note (raises ValueError) and turn it into a full replacement."""
    form = NoteForm.model_validate(payload)
    return NoteChange(
        title=form.title,
        note=form.note,
        tags=form.tags,
        rating=form.rating,
        clear_rating=form.rating is None,
    )
