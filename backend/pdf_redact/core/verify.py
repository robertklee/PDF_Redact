"""Post-apply verification: re-open the *saved output* and prove the marked content is gone."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import pymupdf

from .geometry import (
    contains_point,
    inset,
    overlaps,
    page_area,
    segment_intersects_rect,
    to_unrotated,
    touches,
)
from .objects import page_has_text_properties
from .overlay import drawable
from .redact import Mark, RedactOptions, mark_regions, open_pdf
from .search import normalize, page_indexes
from .text import extract_lines, line_texts

Status = Literal["pass", "warn", "fail"]
_SEVERITY = {"pass": 0, "warn": 1, "fail": 2}
_LINE_HYPHEN = re.compile(r"(?<=\w)-\s+(?=\w)")
MAX_RESIDUAL_CHECKS = 50


@dataclass
class Check:
    name: str
    status: Status
    message: str
    page: int | None = None
    mark_id: str | None = None


@dataclass
class Verification:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    def counts(self) -> dict[str, int]:
        result = {"pass": 0, "warn": 0, "fail": 0}
        for c in self.checks:
            result[c.status] += 1
        return result


def _squash(text: str) -> str:
    return "".join(text.split())


def _fold(text: str) -> str:
    """Text as compared by the residual check: normalised, without whitespace, case-folded."""
    return _squash(normalize(text)).casefold()


def _quote(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return f"“{text if len(text) <= limit else text[: limit - 1] + '…'}”"


def _pages(numbers: list[int]) -> str:
    shown = [str(n + 1) for n in numbers[:10]]
    if len(numbers) > 10:
        return f"pages {', '.join(shown)} and {len(numbers) - 10} more"
    if len(shown) == 1:
        return f"page {shown[0]}"
    return f"pages {', '.join(shown[:-1])} and {shown[-1]}"


def _segments(item: tuple) -> list[tuple[pymupdf.Point, pymupdf.Point]]:
    kind = item[0]
    if kind == "l":
        return [(item[1], item[2])]
    if kind == "re":
        q = pymupdf.Rect(item[1]).quad
    elif kind == "qu":
        q = item[1]
    else:
        return []
    return [(q.ul, q.ur), (q.ur, q.lr), (q.lr, q.ll), (q.ll, q.ul)]


def _path_crosses(drawing: dict, region: pymupdf.Rect) -> bool:
    for item in drawing["items"]:
        if item[0] == "c":
            pts = item[1:5]
            box = pymupdf.Rect(
                min(p.x for p in pts),
                min(p.y for p in pts),
                max(p.x for p in pts),
                max(p.y for p in pts),
            )
            if touches(box, region):
                return True
        elif any(segment_intersects_rect(p, q, region) for p, q in _segments(item)):
            return True
    return False


def _near(a: pymupdf.Rect, b: pymupdf.Rect, tol: float = 1.0) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


class _PageVerifier:
    def __init__(
        self, doc: pymupdf.Document, page: pymupdf.Page, marks: list[Mark], options: RedactOptions
    ):
        self.doc, self.page, self.marks, self.options = doc, page, marks, options
        self.chars = [ch for line in extract_lines(page) for ch in line]
        self.overlays = sorted(
            {
                _squash(drawable(m.appearance.overlay_text))
                for m in marks
                if drawable(m.appearance.overlay_text)
            },
            key=len,
            reverse=True,
        )
        self.images = page.get_image_info(xrefs=True)
        self.drawings = page.get_drawings()
        self.annots = [
            a.rect
            for a in page.annots()
            if a.type[0] not in (pymupdf.PDF_ANNOT_REDACT, pymupdf.PDF_ANNOT_POPUP)
        ]
        self.widgets = [w.rect for w in page.widgets()]
        self.links = [to_unrotated(page, link["from"]) for link in page.get_links()]
        self.own_boxes = [
            r for m in marks if m.appearance.fill is not None for r in mark_regions(page, m)
        ]
        self._pixmaps: dict[int, pymupdf.Pixmap | None] = {}

    def verify(self, mark: Mark) -> Check:
        problems: list[tuple[Status, str]] = []
        for region in mark_regions(self.page, mark):
            problems += self._text(region)
            problems += self._images(region)
            problems += self._vectors(region)
            problems += self._annotations(region)
        if mark.kind == "page":
            problems += self._off_page_text()
        if not problems:
            return Check("mark", "pass", "Content removed", self.page.number, mark.id)
        status = max((s for s, _ in problems), key=_SEVERITY.__getitem__)
        message = "; ".join(dict.fromkeys(msg for _, msg in problems))
        return Check("mark", status, message, self.page.number, mark.id)

    def _text(self, region: pymupdf.Rect) -> list[tuple[Status, str]]:
        probe = inset(region, 0.25)
        leftover = _squash("".join(ch.c for ch in self.chars if contains_point(probe, ch.center)))
        for overlay in self.overlays:
            leftover = leftover.replace(overlay, "")
        if leftover:
            return [("fail", f"{len(leftover)} text character(s) remain under the mark")]
        return []

    def _pixmap(self, xref: int) -> pymupdf.Pixmap | None:
        if xref not in self._pixmaps:
            try:
                self._pixmaps[xref] = pymupdf.Pixmap(self.doc, xref)
            except Exception:  # undecodable image formats
                self._pixmaps[xref] = None
        return self._pixmaps[xref]

    def _images(self, region: pymupdf.Rect) -> list[tuple[Status, str]]:
        if self.options.images == "none":
            if any(overlaps(pymupdf.Rect(i["bbox"]), region) for i in self.images):
                return [("warn", "image under the mark kept (image redaction disabled)")]
            return []
        problems: list[tuple[Status, str]] = []
        for info in self.images:
            bbox = pymupdf.Rect(info["bbox"])
            area = bbox & region
            if not overlaps(bbox, region) or area.width < 1 or area.height < 1:
                continue
            pix = self._pixmap(info.get("xref", 0)) if info.get("xref") else None
            if pix is None:
                problems.append(("warn", "an image under the mark could not be inspected"))
                continue
            inverse = ~pymupdf.Matrix(info["transform"])
            pts = [p * inverse for p in (area.tl, area.tr, area.bl, area.br)]
            # Skip one boundary pixel on each side: partially covered pixels may legitimately stay.
            x0 = max(0, math.floor(min(p.x for p in pts) * pix.width) + 1)
            x1 = min(pix.width, math.ceil(max(p.x for p in pts) * pix.width) - 1)
            y0 = max(0, math.floor(min(p.y for p in pts) * pix.height) + 1)
            y1 = min(pix.height, math.ceil(max(p.y for p in pts) * pix.height) - 1)
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            if pix.color_count(clip=pymupdf.IRect(x0, y0, x1, y1)) > 1:
                problems.append(("fail", "image pixels under the mark were not blanked"))
        return problems

    def _vectors(self, region: pymupdf.Rect) -> list[tuple[Status, str]]:
        probe = inset(region, 0.5)
        kept = 0
        for d in self.drawings:
            if not touches(d["rect"], probe):
                continue
            if d.get("fill") is not None and any(_near(d["rect"], b) for b in self.own_boxes):
                continue
            if _path_crosses(d, probe):
                kept += 1
        if kept:
            return [("warn", f"{kept} vector path(s) pass under the mark and were kept")]
        return []

    def _off_page_text(self) -> list[tuple[Status, str]]:
        area = page_area(self.page)
        outside = "".join(
            ch[0] if isinstance(ch[0], str) else chr(ch[0])
            for span in self.page.get_texttrace()
            for ch in span["chars"]
            if not touches(pymupdf.Rect(ch[3]), area)
        )
        if _squash(outside):
            return [("fail", f"{len(_squash(outside))} text character(s) remain off the page")]
        return []

    def _annotations(self, region: pymupdf.Rect) -> list[tuple[Status, str]]:
        problems: list[tuple[Status, str]] = []
        for rects, what in (
            (self.annots, "annotation"),
            (self.widgets, "form field"),
            (self.links, "link"),
        ):
            hits = sum(overlaps(r, region) for r in rects)
            if hits:
                problems.append(("fail", f"{hits} {what}(s) overlap the mark"))
        return problems


def residual_checks(
    doc: pymupdf.Document, terms: Iterable[str], overlays: Iterable[str]
) -> list[Check]:
    """Search the whole output for strings that were marked from search or detection results.

    A remaining occurrence is a warning rather than a failure: the user may have chosen to keep it.
    Words hyphenated across lines in either the term or the page are also compared joined up.
    Overlay texts written by the redaction are ignored.
    """
    variants: dict[str, set[str]] = {}
    for term in terms:
        forms = {_fold(term), _fold(_LINE_HYPHEN.sub("", normalize(term)))} - {""}
        if forms:
            variants.setdefault(" ".join(term.split()), set()).update(forms)
    if not variants:
        return []
    masks = sorted({_fold(o) for o in overlays} - {""}, key=len, reverse=True)
    texts: list[str] = []
    for page in doc:
        payload = [{"chars": list(line)} for line in line_texts(page)]
        parts = []
        for index in page_indexes(payload):
            text = _fold(index.text)
            for mask in masks:
                text = text.replace(mask, "\0")
            parts.append(text)
        texts.append("\0".join(parts))

    found = [
        (term, [n for n, text in enumerate(texts) if any(f in text for f in forms)])
        for term, forms in variants.items()
    ]
    found = [(term, where) for term, where in found if where]
    if not found:
        count = f"{len(variants)} text{'s' if len(variants) != 1 else ''} checked"
        return [
            Check(
                "residual-text",
                "pass",
                f"Marked search results appear nowhere else in the file ({count})",
            )
        ]
    checks = [
        Check(
            "residual-text",
            "warn",
            f"Marked search result {_quote(term)} still appears on {_pages(where)}",
            where[0] if len(where) == 1 else None,
        )
        for term, where in found[:MAX_RESIDUAL_CHECKS]
    ]
    if len(found) > MAX_RESIDUAL_CHECKS:
        rest = len(found) - MAX_RESIDUAL_CHECKS
        checks.append(
            Check("residual-text", "warn", f"{rest} more marked search result texts still appear")
        )
    return checks


def replacement_text_check(doc: pymupdf.Document, pages: list[int]) -> Check:
    found = [pno for pno in pages if page_has_text_properties(doc, doc[pno]) is not False]
    if found:
        return Check(
            "replacement-text",
            "fail",
            f"Replacement text (/ActualText) that may repeat redacted words remains on "
            f"{_pages(found)}",
            found[0] if len(found) == 1 else None,
        )
    return Check(
        "replacement-text", "pass", "No replacement text (/ActualText) left on redacted pages"
    )


def verify_bytes(
    data: bytes,
    marks: Iterable[Mark],
    options: RedactOptions | None = None,
    password: str | None = None,
    search_terms: Iterable[str] = (),
) -> Verification:
    """Verify a redacted file. `search_terms` are texts marked from search results, which must
    not appear anywhere else in the file."""
    options = options or RedactOptions()
    marks = list(marks)
    search_terms = list(search_terms)
    result = Verification()
    revisions = data.count(b"startxref")
    result.checks.append(
        Check(
            "single-revision",
            "pass" if revisions == 1 else "fail",
            "File fully rewritten (no earlier revisions)"
            if revisions == 1
            else f"File contains {revisions} revisions; earlier versions may hold removed content",
        )
    )
    by_page: dict[int, list[Mark]] = defaultdict(list)
    for mark in marks:
        by_page[mark.page].append(mark)
    with open_pdf(data, password) as doc:
        for pno in sorted(by_page):
            verifier = _PageVerifier(doc, doc[pno], by_page[pno], options)
            result.checks += [verifier.verify(m) for m in by_page[pno]]
        if by_page:
            result.checks.append(replacement_text_check(doc, sorted(by_page)))
        if search_terms:
            overlays = [drawable(m.appearance.overlay_text) for m in marks]
            result.checks += residual_checks(doc, search_terms, overlays)
    return result
