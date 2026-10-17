"""Detection of text that is in the file but cannot be seen.

A character is hidden when removing it does not change the rendered page: invisible text (render
mode 3, fully transparent, OCR fonts), text in the background colour, and text covered by images
or shapes. The page is rendered with and without its text and each character's box is compared.
"""

from __future__ import annotations

import math

import pymupdf

from .geometry import contains_point, full_extent
from .progress import report
from .text import Box, Char, RawChar, raw_lines

ZOOM = 2.0
# Largest per-channel difference that still counts as unchanged (about 5% contrast).
THRESHOLD = 12
# Pixel rounding as MuPDF's fz_round_rect does it.
_EPSILON = 0.001


def _rows_differ(a: bytes, b: bytes, starts: list[int], width: int) -> bool:
    for start in starts:
        ra, rb = a[start : start + width], b[start : start + width]
        if ra != rb and any(abs(p - q) > THRESHOLD for p, q in zip(ra, rb, strict=True)):
            return True
    return False


def _pixel_box(box: Box, m: pymupdf.Matrix, width: int, height: int) -> tuple[int, ...] | None:
    """The pixels covering `box` (unrotated page space), clipped to the pixmap."""
    a, b, c, d, e, f = m
    x0, y0, x1, y1 = box
    # The page rotation is a multiple of 90 degrees, so two opposite corners give the bounds.
    px, py = x0 * a + y0 * c + e, x0 * b + y0 * d + f
    qx, qy = x1 * a + y1 * c + e, x1 * b + y1 * d + f
    ix0 = max(math.floor(min(px, qx) + _EPSILON), 0)
    iy0 = max(math.floor(min(py, qy) + _EPSILON), 0)
    ix1 = min(math.ceil(max(px, qx) - _EPSILON), width)
    iy1 = min(math.ceil(max(py, qy) - _EPSILON), height)
    if ix1 <= ix0 or iy1 <= iy0:
        return None
    return ix0, iy0, ix1, iy1


def _unseen(page: pymupdf.Page, keep_ocr: bool) -> list[Char]:
    """The chars that do not change how `page` (a scratch copy, modified here) renders.

    Glyphs that a clip path hides entirely are included: they do not change the rendering either.
    """
    # Chars without a glyph (/ActualText beyond the glyph count) have zero-width boxes.
    chars: list[tuple[int, tuple[float, float], RawChar]] = [
        (n, direction, ch)
        for n, (direction, line) in enumerate(raw_lines(page, include_clipped=True))
        for ch in line
        if not ch[0].isspace() and ch[1][2] > ch[1][0] and ch[1][3] > ch[1][1]
    ]
    if keep_ocr and chars:
        images = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
        chars = [item for item in chars if not (item[2][5] and _over_image(item[2][2], images))]
    if not chars:
        return []
    mat = pymupdf.Matrix(ZOOM, ZOOM)
    before = page.get_pixmap(matrix=mat, alpha=False, annots=False)
    page.add_redact_annot(full_extent(page), fill=None, cross_out=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )
    after = page.get_pixmap(matrix=mat, alpha=False, annots=False)
    to_pixels = page.rotation_matrix * mat
    width, height, n, stride = before.width, before.height, before.n, before.stride
    sa, sb = before.samples, after.samples
    Rect, Point = pymupdf.Rect, pymupdf.Point
    hidden = []
    for line, direction, (c, bbox, box, origin, size, invisible) in chars:
        pixels = _pixel_box(box, to_pixels, width, height)
        if pixels is not None:
            x0, y0, x1, y1 = pixels
            # Middle rows first: they cross most glyphs.
            mid = (y0 + y1) // 2
            starts = [y * stride + x0 * n for y in (*range(mid, y1), *range(y0, mid))]
            if _rows_differ(sa, sb, starts, (x1 - x0) * n):
                continue
        hidden.append(
            Char(c, Rect(bbox), Rect(box), Point(origin), size, line, direction, invisible)
        )
    return hidden


def _over_image(box: Box, images: list[pymupdf.Rect]) -> bool:
    """For invisible text: whether it is the searchable text layer of a scanned page."""
    center = pymupdf.Point((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    return any(contains_point(img, center) for img in images)


def hidden_text(doc: pymupdf.Document, keep_ocr: bool = True) -> dict[int, list[Char]]:
    """Hidden characters inside the page area, per page number."""
    found: dict[int, list[Char]] = {}
    if not any(page.get_texttrace() for page in doc):
        return found
    # Annotations and form fields are left out: their text is not page content. The copy has no
    # /OCProperties, so text in layers that are switched off counts as seen; removing layers
    # takes care of it.
    with pymupdf.open() as scratch:
        scratch.insert_pdf(doc, annots=False, widgets=False, links=False)
        for page in scratch:
            report("Looking for hidden text", page.number, scratch.page_count)
            if hidden := _unseen(page, keep_ocr):
                found[page.number] = hidden
    return found
