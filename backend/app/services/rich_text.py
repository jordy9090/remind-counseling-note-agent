"""Parse the formatted text sent by the final document editor into a small, safe model.

The editor sends a limited HTML fragment (bold, italic, underline, text color, highlight,
alignment, lists). Nothing from that fragment is passed through to an exported file: it is parsed
into paragraphs and runs here, and each exporter renders the model with its own escaping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser

MAX_PARAGRAPHS = 2000

_BLOCK_TAGS = {"div", "p", "li", "ul", "ol"}
_SKIPPED_TAGS = {"script", "style", "template", "noscript", "iframe", "object", "embed", "head", "title", "svg", "math"}
_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "wbr", "area", "base", "col", "source", "track"}
_ALIGNMENTS = {"left", "center", "right"}
_HEX_COLOR = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
_RGB_COLOR = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RichRun:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str | None = None  # "RRGGBB"
    highlight: str | None = None  # "RRGGBB"


@dataclass
class RichParagraph:
    runs: list[RichRun] = field(default_factory=list)
    align: str = "left"
    list_kind: str | None = None  # "bullet" | "number"
    number: int | None = None

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


def parse_color(value: str | None) -> str | None:
    """Return "RRGGBB" for a hex or rgb()/rgba() color, or None for anything else."""
    text = (value or "").strip()
    match = _HEX_COLOR.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        return digits.upper()
    match = _RGB_COLOR.match(text)
    if not match:
        return None
    red, green, blue = (int(match.group(index)) for index in (1, 2, 3))
    if max(red, green, blue) > 255:
        return None
    alpha = match.group(4)
    if alpha is not None:
        try:
            if float(alpha) == 0:
                return None
        except ValueError:
            return None
    return f"{red:02X}{green:02X}{blue:02X}"


def _style_declarations(value: str | None) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for part in (value or "").split(";"):
        name, separator, raw = part.partition(":")
        if separator:
            declarations[name.strip().lower()] = raw.strip().lower()
    return declarations


def _alignment(tag_attrs: dict[str, str], declarations: dict[str, str]) -> str | None:
    for candidate in (declarations.get("text-align"), (tag_attrs.get("align") or "").strip().lower()):
        if candidate in _ALIGNMENTS:
            return candidate
    return None


class _RichTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[RichParagraph] = []
        self._runs: list[RichRun] = []
        # Each open element: (tag, inline style, alignment or None, list context or None).
        self._stack: list[tuple[str, RichRun, str | None, list | None]] = []
        self._skip_depth = 0
        self._list_item: tuple[str, int] | None = None

    # --- state helpers -------------------------------------------------
    def _style(self) -> RichRun:
        return self._stack[-1][1] if self._stack else RichRun(text="")

    def _align(self) -> str:
        for _tag, _style, align, _list in reversed(self._stack):
            if align:
                return align
        return "left"

    def _flush(self, force: bool = False) -> None:
        if not self._runs and not force:
            return
        if len(self.paragraphs) < MAX_PARAGRAPHS:
            kind, number = self._list_item or (None, None)
            self.paragraphs.append(RichParagraph(runs=self._runs, align=self._align(), list_kind=kind, number=number))
        self._runs = []

    # --- HTMLParser callbacks ------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            if tag in _SKIPPED_TAGS:
                self._skip_depth += 1
            return
        if tag in _SKIPPED_TAGS:
            self._skip_depth = 1
            return
        if tag == "br":
            self._flush(force=True)
            return
        if tag in _VOID_TAGS:
            return

        tag_attrs = {name.lower(): (value or "") for name, value in attrs}
        declarations = _style_declarations(tag_attrs.get("style"))
        style = self._style()
        if tag in {"b", "strong"}:
            style = replace(style, bold=True)
        elif tag in {"i", "em"}:
            style = replace(style, italic=True)
        elif tag == "u":
            style = replace(style, underline=True)
        elif tag == "font":
            style = replace(style, color=parse_color(tag_attrs.get("color")) or style.color)

        weight = declarations.get("font-weight", "")
        if weight in {"bold", "bolder"} or (weight.isdigit() and int(weight) >= 600):
            style = replace(style, bold=True)
        if declarations.get("font-style") in {"italic", "oblique"}:
            style = replace(style, italic=True)
        if "underline" in declarations.get("text-decoration", "") or "underline" in declarations.get("text-decoration-line", ""):
            style = replace(style, underline=True)
        if "color" in declarations:
            style = replace(style, color=parse_color(declarations["color"]) or style.color)
        if "background-color" in declarations:
            style = replace(style, highlight=parse_color(declarations["background-color"]))

        list_context: list | None = None
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in {"ul", "ol"}:
            list_context = ["bullet" if tag == "ul" else "number", 0]
        elif tag == "li":
            parent = next((entry[3] for entry in reversed(self._stack) if entry[3] is not None), None)
            if parent is None:
                self._list_item = ("bullet", 0)
            else:
                parent[1] += 1
                self._list_item = (parent[0], parent[1])
        align = _alignment(tag_attrs, declarations) if tag in _BLOCK_TAGS else None
        self._stack.append((tag, style, align, list_context))

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag in _SKIPPED_TAGS:
                self._skip_depth -= 1
            return
        if tag in _VOID_TAGS or not any(entry[0] == tag for entry in self._stack):
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        while self._stack:
            closed = self._stack.pop()
            if closed[0] == tag:
                break
        if tag == "li":
            self._list_item = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        text = re.sub(r"[\r\n]+", " ", data).replace("\xa0", " ")
        if not text:
            return
        style = replace(self._style(), text=text)
        last = self._runs[-1] if self._runs else None
        if last is not None and replace(last, text="") == replace(style, text=""):
            self._runs[-1] = replace(last, text=last.text + text)
        else:
            self._runs.append(style)

    def close(self) -> None:
        super().close()
        self._flush()


def parse_rich_text(markup: str | None) -> list[RichParagraph]:
    """Parse editor markup into paragraphs. Unknown tags keep their text; scripts and styles are dropped."""
    if not markup or not markup.strip():
        return []
    parser = _RichTextParser()
    parser.feed(markup)
    parser.close()
    paragraphs = parser.paragraphs
    while paragraphs and not paragraphs[-1].text.strip():
        paragraphs.pop()
    return paragraphs


def rich_plain_text(paragraphs: list[RichParagraph]) -> str:
    return "\n".join(paragraph.text for paragraph in paragraphs)
