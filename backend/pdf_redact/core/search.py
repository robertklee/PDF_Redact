"""Text search over extracted page text, mapped back to character boxes.

Searching works on a normalised copy of each page's text: compatibility forms are decomposed
(ligatures such as "ﬁ" become "fi"), typographic quotes and dashes are folded to ASCII, runs of
whitespace collapse to one space and lines are joined with a space. Words hyphenated across a line
break are searched both with and without the hyphen. Every normalised character remembers which
source character it came from, so a match maps back to exact character boxes.

The geometry of a match mirrors the UI's text selection (``selectionFromRanges`` in
``frontend/src/lib/textSelection.ts``) so that search marks behave exactly like selected text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache

Rect = tuple[float, float, float, float]

_FOLD = (
    {ord(c): "'" for c in "\u2018\u2019\u201a\u201b\u2032"}
    | {ord(c): '"' for c in "\u201c\u201d\u201e\u201f\u2033"}
    | {ord(c): "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"}
    | {0x00AD: None}  # soft hyphen
)
_LETTER = re.compile(r"[^\W\d_]")
CONTEXT_CHARS = 40


def normalize(text: str) -> str:
    """The normalisation applied to page text, for use on queries."""
    return unicodedata.normalize("NFKC", text).translate(_FOLD)


def _is_space(c: str) -> bool:
    return c.strip() == ""


@lru_cache(maxsize=4096)
def _normalized_char(c: str) -> tuple[tuple[str, bool], ...]:
    """A page character's normalised form, each part with whether it is whitespace."""
    return tuple((n, _is_space(n)) for n in normalize(c))


def _is_hyphen(c: str) -> bool:
    return c == "\u00ad" or normalize(c) == "-"


def direction_angle(direction: Iterable[float]) -> int | None:
    dx, dy = direction
    if dx > 0.999:
        return 0
    if dy < -0.999:
        return 90
    if dx < -0.999:
        return 180
    if dy > 0.999:
        return 270
    return None


def _union(rects: list[Rect]) -> Rect:
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


@dataclass
class Selection:
    rects: list[Rect]
    text: str
    angle: int | None


def selection_from_ranges(
    lines: list[dict], ranges: list[tuple[int, int, int]]
) -> Selection | None:
    """One rectangle per line (whitespace trimmed); per-character boxes for slanted text."""
    rects: list[Rect] = []
    parts: list[str] = []
    votes: dict[int | None, int] = {}
    for li, start, end in ranges:
        line = lines[li]
        chars, boxes = line["chars"], line["boxes"]
        while start < end and _is_space(chars[start]):
            start += 1
        while end > start and _is_space(chars[end - 1]):
            end -= 1
        if end <= start:
            continue
        angle = direction_angle(line["dir"])
        if angle is None:
            rects += [tuple(boxes[k]) for k in range(start, end) if not _is_space(chars[k])]
        else:
            rects.append(_union([tuple(b) for b in boxes[start:end]]))
        parts.append("".join(chars[start:end]))
        votes[angle] = votes.get(angle, 0) + end - start
    if not rects:
        return None
    angle = max(votes.items(), key=lambda kv: kv[1])[0]
    return Selection([tuple(round(v, 2) for v in r) for r in rects], " ".join(parts), angle)


@dataclass
class PageIndex:
    """Normalised page text and, for every character, its source character (or None)."""

    lines: list[dict]
    text: str
    source: list[int | None]
    # (line, char) of every source character, in reading order
    chars: list[tuple[int, int]] = field(repr=False)

    def ranges(self, start: int, end: int) -> list[tuple[int, int, int]]:
        """Source character ranges (line, start, end) covered by normalised text [start, end)."""
        hits = [g for g in self.source[start:end] if g is not None]
        if not hits:
            return []
        out: list[tuple[int, int, int]] = []
        for g in range(min(hits), max(hits) + 1):
            li, ci = self.chars[g]
            if out and out[-1][0] == li:
                out[-1] = (li, out[-1][1], ci + 1)
            else:
                out.append((li, ci, ci + 1))
        return out


def _hyphen_joins(lines: list[dict]) -> dict[int, int]:
    """Lines ending in a hyphenated word that continues on the next line → index of the hyphen."""
    joins: dict[int, int] = {}
    for li in range(len(lines) - 1):
        chars = lines[li]["chars"]
        end = len(chars)
        while end and _is_space(chars[end - 1]):
            end -= 1
        nxt = [c for c in lines[li + 1]["chars"] if not _is_space(c)]
        if (
            end >= 2
            and _is_hyphen(chars[end - 1])
            and _LETTER.match(normalize(chars[end - 2]) or " ")
            and nxt
            and _LETTER.match(normalize(nxt[0]) or " ")
        ):
            joins[li] = end - 1
    return joins


def build_index(lines: list[dict], keep_hyphens: bool = False) -> PageIndex:
    joins = _hyphen_joins(lines)
    text: list[str] = []
    source: list[int | None] = []
    chars: list[tuple[int, int]] = []
    space = True  # suppress leading whitespace

    for li, line in enumerate(lines):
        hyphen = joins.get(li)
        for ci, c in enumerate(line["chars"]):
            g = len(chars)
            chars.append((li, ci))
            if hyphen is not None and (ci > hyphen or (ci == hyphen and not keep_hyphens)):
                continue
            for n, blank in _normalized_char(c):
                if blank:
                    if space:
                        continue
                    n, space = " ", True
                else:
                    space = False
                text.append(n)
                source.append(g)
        if hyphen is None and not space:
            text.append(" ")
            source.append(None)
            space = True
    while text and text[-1] == " ":
        text.pop()
        source.pop()
    return PageIndex(lines, "".join(text), source, chars)


def page_indexes(lines: list[dict]) -> list[PageIndex]:
    """Indexes to search: one, plus one keeping hyphens if any word is hyphenated across lines."""
    indexes = [build_index(lines)]
    if _hyphen_joins(lines):
        indexes.append(build_index(lines, keep_hyphens=True))
    return indexes


@dataclass
class Match:
    page: int
    rects: list[Rect]
    text: str
    angle: int | None
    before: str
    after: str
    category: str | None = None
    # first and last source character, for ordering and de-duplication
    span: tuple[int, int] = (0, 0)


def _context(index: PageIndex, start: int, end: int) -> tuple[str, str]:
    before = index.text[max(0, start - CONTEXT_CHARS) : start]
    after = index.text[end : end + CONTEXT_CHARS]
    if start > CONTEXT_CHARS and " " in before:
        before = "…" + before[before.index(" ") + 1 :]
    if end + CONTEXT_CHARS < len(index.text) and " " in after:
        after = after[: after.rindex(" ")] + "…"
    return before, after


def match_at(
    page: int, index: PageIndex, start: int, end: int, category: str | None = None
) -> Match | None:
    ranges = index.ranges(start, end)
    sel = selection_from_ranges(index.lines, ranges)
    if sel is None:
        return None
    before, after = _context(index, start, end)
    hits = [g for g in index.source[start:end] if g is not None]
    return Match(
        page, sel.rects, sel.text, sel.angle, before, after, category, (min(hits), max(hits))
    )


def compile_query(query: str, mode: str, case_sensitive: bool) -> re.Pattern[str]:
    """Raises ``re.error`` for an invalid regular expression."""
    flags = 0 if case_sensitive else re.IGNORECASE
    if mode == "regex":
        return re.compile(normalize(query), flags)
    words = normalize(query).split()
    if not words:
        raise re.error("empty search")
    pattern = r"\s+".join(re.escape(w) for w in words)
    if mode == "word":
        pattern = rf"(?<!\w){pattern}(?!\w)"
    return re.compile(pattern, flags)


def find(
    page: int, lines: list[dict], pattern: re.Pattern[str], category: str | None = None
) -> Iterator[Match]:
    """Non-empty matches of `pattern` on one page, in reading order, without duplicates."""
    seen: set[tuple[int, int]] = set()
    found: list[Match] = []
    for index in page_indexes(lines):
        for m in pattern.finditer(index.text):
            if m.end() <= m.start():
                continue
            match = match_at(page, index, m.start(), m.end(), category)
            if match and match.span not in seen:
                seen.add(match.span)
                found.append(match)
    found.sort(key=lambda m: m.span)
    yield from found
