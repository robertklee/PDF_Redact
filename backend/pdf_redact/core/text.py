"""Character-level text geometry extracted with PyMuPDF."""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from .geometry import rect_list, to_display, union

# Raw-dict defaults minus embedded image data (we only need text here).
TEXT_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES

REPLACEMENT_CHAR = "\ufffd"

# Tight glyph extent around the baseline, as fractions of the font size. MuPDF's own "small glyph
# heights" mode is global state and mis-places boxes for 180/270 degree text, so we derive tight
# boxes ourselves from the origin, writing direction and size.
TIGHT_ASCENT = 0.8
TIGHT_DESCENT = 0.2


@dataclass(frozen=True, slots=True)
class Char:
    c: str
    bbox: pymupdf.Rect  # full font box (what MuPDF redaction tests against), unrotated space
    box: pymupdf.Rect  # tight box for selection and display, unrotated space
    origin: pymupdf.Point  # baseline start point, unrotated page space
    size: float  # font size
    line: int  # index of the containing line, in reading order
    dir: tuple[float, float]  # unit writing direction of the line
    invisible: bool = False  # neither filled nor stroked, fully transparent, or an OCR font

    @property
    def center(self) -> pymupdf.Point:
        return pymupdf.Point((self.box.x0 + self.box.x1) / 2, (self.box.y0 + self.box.y1) / 2)


def tight_box(
    bbox: pymupdf.Rect, origin: pymupdf.Point, size: float, direction: tuple[float, float]
) -> pymupdf.Rect:
    """Axis-aligned bounds of the glyph's advance x [baseline - descent, baseline + ascent]."""
    dx, dy = direction
    ux, uy = dy, -dx  # "up" in y-down page space
    # The full box is symmetric about the glyph centre, so its projection onto the writing
    # direction gives the advance span (exact for axis-aligned text).
    along = [
        (x - origin.x) * dx + (y - origin.y) * dy
        for x in (bbox.x0, bbox.x1)
        for y in (bbox.y0, bbox.y1)
    ]
    a0, a1 = min(along), max(along)
    up0, up1 = -TIGHT_DESCENT * size, TIGHT_ASCENT * size
    xs, ys = [], []
    for a in (a0, a1):
        for u in (up0, up1):
            xs.append(origin.x + dx * a + ux * u)
            ys.append(origin.y + dy * a + uy * u)
    return pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))


_PAINTED = pymupdf.mupdf.FZ_STEXT_FILLED | pymupdf.mupdf.FZ_STEXT_STROKED


def _invisible(span: dict) -> bool:
    if span.get("alpha") == 0 or str(span.get("font", "")).endswith("GlyphLessFont"):
        return True
    flags = span.get("char_flags")
    return isinstance(flags, int) and not flags & _PAINTED


def extract_lines(page: pymupdf.Page, everywhere: bool = False) -> list[list[Char]]:
    """All text lines on the page in reading order, each as a list of characters.

    Only text inside the page area is included unless `everywhere` is set.
    """
    if everywhere:
        flags, clip = TEXT_FLAGS & ~pymupdf.TEXT_MEDIABOX_CLIP, pymupdf.INFINITE_RECT()
    else:
        flags, clip = TEXT_FLAGS, None
    raw = page.get_text("rawdict", flags=flags, clip=clip)
    lines: list[list[Char]] = []
    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            direction = (float(line["dir"][0]), float(line["dir"][1]))
            chars = []
            for span in line["spans"]:
                size = float(span["size"])
                invisible = _invisible(span)
                for ch in span["chars"]:
                    bbox, origin = pymupdf.Rect(ch["bbox"]), pymupdf.Point(ch["origin"])
                    chars.append(
                        Char(
                            c=ch["c"],
                            bbox=bbox,
                            box=tight_box(bbox, origin, size, direction),
                            origin=origin,
                            size=size,
                            line=len(lines),
                            dir=direction,
                            invisible=invisible,
                        )
                    )
            if chars:
                lines.append(chars)
    return lines


def line_texts(page: pymupdf.Page) -> list[str]:
    """The text of each line, like ``extract_lines`` but much faster as it skips geometry."""
    return page.get_text("text", flags=TEXT_FLAGS).split("\n")


def page_text_payload(page: pymupdf.Page) -> dict:
    """Text geometry for the UI, in display space."""
    out_lines = []
    unmapped = 0
    has_text = False
    m = page.rotation_matrix
    for chars in extract_lines(page):
        boxes = [to_display(page, ch.box) for ch in chars]
        direction = pymupdf.Point(chars[0].dir) * m - pymupdf.Point(0, 0) * m
        out_lines.append(
            {
                "bbox": rect_list(union(boxes)),
                "chars": [ch.c for ch in chars],
                "boxes": [rect_list(b) for b in boxes],
                "dir": [round(direction.x, 4), round(direction.y, 4)],
            }
        )
        unmapped += sum(ch.c == REPLACEMENT_CHAR for ch in chars)
        has_text = has_text or any(not ch.c.isspace() for ch in chars)
    return {
        "index": page.number,
        "width": round(page.rect.width, 2),
        "height": round(page.rect.height, 2),
        "lines": out_lines,
        "hasText": has_text,
        "unmappedChars": unmapped,
    }
