"""Content removal on top of MuPDF's redaction.

MuPDF removes a glyph when its font box touches a redaction rectangle. Font boxes of adjacent lines
overlap, so thin bands through the vertical middle of the wanted glyphs are used instead: they
touch exactly those glyphs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import pymupdf

from .text import Char

# Removal band through each glyph, as fractions of the font size above the baseline.
BAND_LOW, BAND_HIGH = 0.30, 0.45


def removal_bands(chars: Iterable[Char]) -> list[pymupdf.Rect]:
    """Thin rectangles that touch the font boxes of exactly the given glyphs."""
    runs: dict[tuple, list[Char]] = defaultdict(list)
    for ch in chars:
        dx, dy = ch.dir
        base = ch.origin.x * dy - ch.origin.y * dx  # baseline offset along the "up" vector
        runs[(ch.line, round(base, 1), round(ch.size, 1), ch.dir)].append(ch)

    bands: list[pymupdf.Rect] = []
    for (_, base, size, (dx, dy)), run in runs.items():
        if not (abs(dx) > 0.999 or abs(dy) > 0.999):
            # Diagonal text: an axis-aligned band would be too fat, so use a dot per glyph.
            for ch in run:
                h = max(0.1 * ch.size, 0.25)
                c = ch.center
                bands.append(pymupdf.Rect(c.x - h, c.y - h, c.x + h, c.y + h))
            continue
        up = (dy, -dx)
        along = [ch.center.x * dx + ch.center.y * dy for ch in run]
        a0, a1 = min(along), max(along)
        if a1 - a0 < 0.5:
            a0, a1 = a0 - 0.25, a1 + 0.25
        p0, p1 = base + BAND_LOW * size, base + BAND_HIGH * size
        corners = [(dx * a + up[0] * p, dy * a + up[1] * p) for a in (a0, a1) for p in (p0, p1)]
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        bands.append(pymupdf.Rect(min(xs), min(ys), max(xs), max(ys)))
    return bands


def remove_glyphs(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> None:
    """Remove the text touching the rects; images and graphics are left alone."""
    if not rects:
        return
    for r in rects:
        page.add_redact_annot(r, fill=None, cross_out=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )


Fill = tuple[float, float, float] | None
_PATHS = frozenset({"fill-path", "stroke-path"})


def _same(a: pymupdf.Rect, b: pymupdf.Rect, tol: float = 0.5) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def apply_regions(
    page: pymupdf.Page,
    regions: list[tuple[pymupdf.Rect, Fill]],
    images: int,
    graphics: int,
    text: int,
) -> None:
    """Redact the regions, drawing a box of the given fill colour (None = nothing) over each.

    MuPDF keeps a path that an earlier region only partly overlaps even when a later region covers
    it, so regions that still cover a path afterwards are applied once more on their own.
    """
    if not regions:
        return
    for region, fill in regions:
        page.add_redact_annot(region, fill=fill, cross_out=False)
    page.apply_redactions(images=images, graphics=graphics, text=text)
    if graphics != pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED or len(regions) < 2:
        return
    boxes = [pymupdf.Rect(r) for r, fill in regions if fill is not None]
    for region, fill in regions:
        paths = [pymupdf.Rect(b) for kind, b in page.get_bboxlog() if kind in _PATHS]
        if any(p in region and not any(_same(p, box) for box in boxes) for p in paths):
            page.add_redact_annot(region, fill=fill, cross_out=False)
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,
                graphics=graphics,
                text=pymupdf.PDF_REDACT_TEXT_NONE,
            )
