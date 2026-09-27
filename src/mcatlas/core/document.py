"""A tiny document model rendered to both Markdown and plain HTML.

The atlas writes every page twice: Markdown for reading as text, HTML (no scripts, one inline
style sheet) for reading in a browser. Building both from one model keeps them identical in
content. Only what the atlas needs is supported: headings, paragraphs, lists, tables, images,
preformatted text and Markdown written by people (notes).
"""

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Link:
    text: str
    md: str
    """Target in the Markdown version (relative path)."""
    html: str
    """Target in the HTML version; differs from `md` for links to other pages."""


def link(text: str, href: str) -> Link:
    """A link to a file that both versions share (an image, CSV or TOML file)."""
    return Link(text, href, href)


def page(text: str, base: str, *, md: str = "README.md", html: str = "index.html") -> Link:
    """A link to another page, e.g. `page("x", "../other/")`."""
    return Link(text, base + md, base + html)


@dataclass(frozen=True, slots=True)
class Code:
    """Inline code: coordinates, commands, folder names."""

    text: str


type Inline = str | Link | Code
type Text = Inline | Sequence[Inline]


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    text: str


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: Text


@dataclass(frozen=True, slots=True)
class Items:
    items: Sequence[Text]


@dataclass(frozen=True, slots=True)
class Table:
    header: Sequence[str]
    rows: Sequence[Sequence[Text]]
    numeric: Sequence[int] = ()
    """Columns (by index) aligned to the right."""


@dataclass(frozen=True, slots=True)
class Image:
    src: str
    alt: str
    caption: str = ""


@dataclass(frozen=True, slots=True)
class Pre:
    """Text shown exactly as it is: book pages, long sign texts."""

    text: str


@dataclass(frozen=True, slots=True)
class Markdown:
    """Markdown written by people (a note): kept as is in Markdown, as plain text in HTML."""

    text: str


type Block = Heading | Paragraph | Items | Table | Image | Pre | Markdown


@dataclass(frozen=True, slots=True)
class Document:
    title: str
    blocks: Sequence[Block]


# ---------- Markdown ----------

_MD_SPECIAL: Final = re.compile(r"([\\`*\[\]<>|]|(?<!\w)_|_(?!\w))")
"""Characters with a meaning in Markdown; `_` inside a word (oak_planks) has none."""
_MD_LINE_START: Final = re.compile(r"^([#+-]|\d+[.)])(?=\s|$)")
"""What would start a heading or list when it opens a paragraph or list item."""


_WHITESPACE: Final = re.compile(r"\s+")


def _md_escape(text: str, *, line_start: bool = False) -> str:
    escaped = _MD_SPECIAL.sub(r"\\\1", _WHITESPACE.sub(" ", text))
    return _MD_LINE_START.sub(r"\\\1", escaped) if line_start else escaped


def _md_code(text: str) -> str:
    one_line = " ".join(text.split())
    fence = "`"
    while fence in one_line:
        fence += "`"
    pad = " " if one_line.startswith("`") or one_line.endswith("`") else ""
    return f"{fence}{pad}{one_line}{pad}{fence}"


def _md_href(href: str) -> str:
    return "<" + href.replace("<", "%3C").replace(">", "%3E") + ">" if " " in href else href


def _parts(text: Text) -> Sequence[Inline]:
    return [text] if isinstance(text, str | Link | Code) else text


def _md_inline(text: Text, *, line_start: bool = False) -> str:
    out: list[str] = []
    for part in _parts(text):
        if isinstance(part, Link):
            out.append(f"[{_md_escape(part.text)}]({_md_href(part.md)})")
        elif isinstance(part, Code):
            out.append(_md_code(part.text))
        else:
            out.append(_md_escape(part, line_start=line_start and not out))
    return "".join(out)


def _md_block(block: Block) -> str:  # noqa: PLR0911 - one arm per block type
    match block:
        case Heading(level, text):
            return f"{'#' * level} {_md_escape(text)}"
        case Paragraph(text):
            return _md_inline(text, line_start=True)
        case Items(items):
            return "\n".join(f"- {_md_inline(i, line_start=True)}" for i in items)
        case Table(header, rows, numeric):
            lines = [
                "| " + " | ".join(_md_escape(h) for h in header) + " |",
                "| "
                + " | ".join("---:" if i in numeric else "---" for i in range(len(header)))
                + " |",
            ]
            lines += ["| " + " | ".join(_md_inline(c) for c in row) + " |" for row in rows]
            return "\n".join(lines)
        case Image(src, alt, caption):
            image = f"![{_md_escape(alt)}]({_md_href(src)})"
            return f"{image}\n\n*{_md_escape(caption)}*" if caption else image
        case Pre(text):
            fence = "```"
            while fence in text:
                fence += "`"
            return f"{fence}text\n{text}\n{fence}"
        case Markdown(text):
            return text.strip("\n")


def to_markdown(doc: Document) -> str:
    return "\n\n".join([f"# {_md_escape(doc.title)}", *(_md_block(b) for b in doc.blocks)]) + "\n"


# ---------- HTML ----------

STYLE: Final = """
body { font: 16px/1.5 system-ui, sans-serif; max-width: 70rem; margin: 0 auto; padding: 1rem;
  color: #1d1d1f; background: #fff; }
table { border-collapse: collapse; margin: 0.5rem 0 1rem; }
th, td { border-bottom: 1px solid #ddd; padding: 0.25rem 0.6rem; text-align: left;
  vertical-align: top; }
th { background: #f3f3f3; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
img { max-width: 100%; image-rendering: pixelated; border: 1px solid #ddd; }
figure { margin: 0.5rem 0 1rem; }
figcaption { color: #555; font-size: 0.9rem; }
pre, .note { white-space: pre-wrap; background: #f6f6f6; padding: 0.6rem; border-radius: 4px; }
code { background: #f1f1f1; padding: 0 0.2rem; border-radius: 3px; }
@media (prefers-color-scheme: dark) {
  body { color: #e8e8e8; background: #161616; }
  th { background: #262626; } th, td { border-color: #333; } img { border-color: #333; }
  pre, .note, code { background: #222; } figcaption { color: #aaa; } a { color: #8ab4ff; }
}
""".strip()


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _html_inline(text: Text) -> str:
    out: list[str] = []
    for part in _parts(text):
        if isinstance(part, Link):
            out.append(f'<a href="{_esc(part.html)}">{_esc(part.text)}</a>')
        elif isinstance(part, Code):
            out.append(f"<code>{_esc(part.text)}</code>")
        else:
            out.append(_esc(part))
    return "".join(out)


def _cell(tag: str, content: str, column: int, numeric: Sequence[int]) -> str:
    cls = ' class="n"' if column in numeric else ""
    return f"<{tag}{cls}>{content}</{tag}>"


def _html_block(block: Block) -> str:  # noqa: PLR0911 - one arm per block type
    match block:
        case Heading(level, text):
            return f"<h{level}>{_esc(text)}</h{level}>"
        case Paragraph(text):
            return f"<p>{_html_inline(text)}</p>"
        case Items(items):
            return "<ul>\n" + "\n".join(f"<li>{_html_inline(i)}</li>" for i in items) + "\n</ul>"
        case Table(header, rows, numeric):
            head = "".join(_cell("th", _esc(h), i, numeric) for i, h in enumerate(header))
            body = "\n".join(
                "<tr>"
                + "".join(_cell("td", _html_inline(c), i, numeric) for i, c in enumerate(row))
                + "</tr>"
                for row in rows
            )
            thead = f"<thead><tr>{head}</tr></thead>\n" if any(header) else ""
            return f"<table>\n{thead}<tbody>\n{body}\n</tbody>\n</table>"
        case Image(src, alt, caption):
            img = f'<img src="{_esc(src)}" alt="{_esc(alt)}" loading="lazy">'
            cap = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
            return f"<figure>{img}{cap}</figure>"
        case Pre(text):
            return f"<pre>{_esc(text)}</pre>"
        case Markdown(text):
            return f'<div class="note">{_esc(text.strip())}</div>'


def to_html(doc: Document, *, lang: str = "nl") -> str:
    body = "\n".join(_html_block(b) for b in doc.blocks)
    return (
        "<!doctype html>\n"
        f'<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(doc.title)}</title>\n<style>\n{STYLE}\n</style>\n</head>\n<body>\n"
        f"<h1>{_esc(doc.title)}</h1>\n{body}\n</body>\n</html>\n"
    )
