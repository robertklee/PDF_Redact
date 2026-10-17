"""Coordinate conventions.

* **Display space** (used by the UI and the API): points, top-left origin, *after* applying the
  page's /Rotate, relative to the CropBox. It equals the PDF.js viewport at scale 1, so the UI only
  ever multiplies by its zoom factor.
* **Unrotated space** (used by PyMuPDF for text extraction and annotations): points, top-left
  origin, relative to the CropBox, *ignoring* /Rotate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pymupdf

RectLike = Sequence[float] | pymupdf.Rect


def to_display(page: pymupdf.Page, rect: RectLike) -> pymupdf.Rect:
    return pymupdf.Rect(rect) * page.rotation_matrix


def to_unrotated(page: pymupdf.Page, rect: RectLike) -> pymupdf.Rect:
    return pymupdf.Rect(rect) * page.derotation_matrix


def page_area(page: pymupdf.Page) -> pymupdf.Rect:
    """The visible page area in unrotated space."""
    return to_unrotated(page, page.rect)


# How far past the page edges "the whole page" reaches, to include content placed off the page.
OFF_PAGE = 100_000


def full_extent(page: pymupdf.Page) -> pymupdf.Rect:
    """Everything the page could draw, including content placed outside the MediaBox."""
    return pymupdf.Rect(page_area(page)) + (-OFF_PAGE, -OFF_PAGE, OFF_PAGE, OFF_PAGE)


def outside(area: pymupdf.Rect, extent: pymupdf.Rect) -> list[pymupdf.Rect]:
    """Overlapping strips covering `extent` minus `area` (above, below, left, right).

    Anything entirely outside `area` lies entirely within one of them.
    """
    strips = [
        pymupdf.Rect(extent.x0, extent.y0, extent.x1, area.y0),
        pymupdf.Rect(extent.x0, area.y1, extent.x1, extent.y1),
        pymupdf.Rect(extent.x0, extent.y0, area.x0, extent.y1),
        pymupdf.Rect(area.x1, extent.y0, extent.x1, extent.y1),
    ]
    return [r for r in strips if not r.is_empty]


def rect_list(rect: pymupdf.Rect, ndigits: int = 2) -> list[float]:
    return [
        round(rect.x0, ndigits),
        round(rect.y0, ndigits),
        round(rect.x1, ndigits),
        round(rect.y1, ndigits),
    ]


def union(rects: Iterable[RectLike]) -> pymupdf.Rect:
    rs = [pymupdf.Rect(r) for r in rects]
    if not rs:
        return pymupdf.Rect()
    return pymupdf.Rect(
        min(r.x0 for r in rs), min(r.y0 for r in rs), max(r.x1 for r in rs), max(r.y1 for r in rs)
    )


def contains_point(rect: pymupdf.Rect, point: pymupdf.Point, tolerance: float = 0.0) -> bool:
    return (
        rect.x0 - tolerance <= point.x <= rect.x1 + tolerance
        and rect.y0 - tolerance <= point.y <= rect.y1 + tolerance
    )


def inset(rect: pymupdf.Rect, amount: float) -> pymupdf.Rect:
    """Shrink a rect on every side, never inverting it."""
    dx = min(amount, rect.width / 2)
    dy = min(amount, rect.height / 2)
    return pymupdf.Rect(rect.x0 + dx, rect.y0 + dy, rect.x1 - dx, rect.y1 - dy)


def overlaps(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    """True if the rects share a region of positive area."""
    return min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0)


def touches(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    """Like `overlaps`, but also true for degenerate rects (e.g. the bbox of a straight line)."""
    return min(a.x1, b.x1) >= max(a.x0, b.x0) and min(a.y1, b.y1) >= max(a.y0, b.y0)


def segment_intersects_rect(p: pymupdf.Point, q: pymupdf.Point, rect: pymupdf.Rect) -> bool:
    """Liang–Barsky test: does the segment p→q pass through the rect?"""
    dx, dy = q.x - p.x, q.y - p.y
    t0, t1 = 0.0, 1.0
    for edge_p, edge_q in (
        (-dx, p.x - rect.x0),
        (dx, rect.x1 - p.x),
        (-dy, p.y - rect.y0),
        (dy, rect.y1 - p.y),
    ):
        if edge_p == 0:
            if edge_q < 0:
                return False
            continue
        t = edge_q / edge_p
        if edge_p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True
