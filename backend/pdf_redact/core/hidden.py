"""Detection of text that is in the file but cannot be seen.

A character is hidden when removing it does not change the rendered page: invisible text (render
mode 3, fully transparent, OCR fonts), text in the background colour, and text covered by images
or shapes. The page is rendered with and without its text and each character's box is compared.
"""

from __future__ import annotations

import pymupdf

from .geometry import contains_point, full_extent
from .text import Char, extract_lines

ZOOM = 2.0
# Largest per-channel difference that still counts as unchanged (about 5% contrast).
THRESHOLD = 12


def _differs(a: pymupdf.Pixmap, b: pymupdf.Pixmap, box: pymupdf.IRect) -> bool:
    n, stride = a.n, a.stride
    sa, sb = a.samples_mv, b.samples_mv
    for y in range(box.y0, box.y1):
        start = y * stride + box.x0 * n
        end = y * stride + box.x1 * n
        ra, rb = sa[start:end], sb[start:end]
        if ra != rb and max(abs(p - q) for p, q in zip(ra, rb, strict=True)) > THRESHOLD:
            return True
    return False


def _unseen(page: pymupdf.Page, keep_ocr: bool) -> list[Char]:
    """The chars that do not change how `page` (a scratch copy, modified here) renders."""
    # Chars without a glyph (/ActualText beyond the glyph count) have zero-width boxes.
    chars = [
        ch
        for line in extract_lines(page)
        for ch in line
        if not ch.c.isspace() and not ch.bbox.is_empty
    ]
    if keep_ocr and chars:
        images = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
        chars = [ch for ch in chars if not is_ocr(ch, images)]
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
    hidden = []
    for ch in chars:
        box = pymupdf.Rect(ch.box * to_pixels).irect & before.irect
        if box.is_empty or not _differs(before, after, box):
            hidden.append(ch)
    return hidden


def is_ocr(ch: Char, images: list[pymupdf.Rect]) -> bool:
    """Invisible text over an image: the searchable text layer of a scanned page."""
    return ch.invisible and any(contains_point(img, ch.center) for img in images)


def hidden_text(doc: pymupdf.Document, keep_ocr: bool = True) -> dict[int, list[Char]]:
    """Hidden characters inside the page area, per page number."""
    found: dict[int, list[Char]] = {}
    if not any(page.get_texttrace() for page in doc):
        return found
    # Annotations and form fields are left out: their text is not page content.
    with pymupdf.open() as scratch:
        scratch.insert_pdf(doc, annots=False, widgets=False, links=False)
        for page in scratch:
            if hidden := _unseen(page, keep_ocr):
                found[page.number] = hidden
    return found
