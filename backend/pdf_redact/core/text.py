"""Character-level text geometry extracted with PyMuPDF."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pymupdf

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


Box = tuple[float, float, float, float]


def tight_box(
    bbox: Sequence[float], origin: Sequence[float], size: float, direction: tuple[float, float]
) -> Box:
    """Axis-aligned bounds of the glyph's advance x [baseline - descent, baseline + ascent]."""
    x0, y0, x1, y1 = bbox
    ox, oy = origin
    dx, dy = direction
    if dx == 1.0 and dy == 0.0:
        # Horizontal text, by far the most common: the general case below, simplified.
        a0, a1 = x0 - ox, x1 - ox
        if a1 < a0:
            a0, a1 = a1, a0
        return ox + a0, oy - TIGHT_ASCENT * size, ox + a1, oy + TIGHT_DESCENT * size
    ux, uy = dy, -dx  # "up" in y-down page space
    # The full box is symmetric about the glyph centre, so its projection onto the writing
    # direction gives the advance span (exact for axis-aligned text).
    along = (
        (x0 - ox) * dx + (y0 - oy) * dy,
        (x1 - ox) * dx + (y0 - oy) * dy,
        (x0 - ox) * dx + (y1 - oy) * dy,
        (x1 - ox) * dx + (y1 - oy) * dy,
    )
    a0, a1 = min(along), max(along)
    u0, u1 = -TIGHT_DESCENT * size, TIGHT_ASCENT * size
    xs = (
        ox + dx * a0 + ux * u0,
        ox + dx * a0 + ux * u1,
        ox + dx * a1 + ux * u0,
        ox + dx * a1 + ux * u1,
    )
    ys = (
        oy + dy * a0 + uy * u0,
        oy + dy * a0 + uy * u1,
        oy + dy * a1 + uy * u0,
        oy + dy * a1 + uy * u1,
    )
    return min(xs), min(ys), max(xs), max(ys)


_PAINTED = pymupdf.mupdf.FZ_STEXT_FILLED | pymupdf.mupdf.FZ_STEXT_STROKED


def _invisible(span: dict) -> bool:
    if span.get("alpha") == 0 or str(span.get("font", "")).endswith("GlyphLessFont"):
        return True
    flags = span.get("char_flags")
    return isinstance(flags, int) and not flags & _PAINTED


# A character as plain values (fast to build): c, bbox, tight box, origin, size, invisible.
RawChar = tuple[str, Box, Box, tuple[float, float], float, bool]


def raw_lines(
    page: pymupdf.Page, everywhere: bool = False
) -> Iterator[tuple[tuple[float, float], list[RawChar]]]:
    """The writing direction and characters of each text line, in reading order."""
    if everywhere:
        flags, clip = TEXT_FLAGS & ~pymupdf.TEXT_MEDIABOX_CLIP, pymupdf.INFINITE_RECT()
    else:
        flags, clip = TEXT_FLAGS, None
    raw = page.get_text("rawdict", flags=flags, clip=clip)
    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            direction = (float(line["dir"][0]), float(line["dir"][1]))
            chars: list[RawChar] = []
            for span in line["spans"]:
                size = float(span["size"])
                invisible = _invisible(span)
                for ch in span["chars"]:
                    bbox, origin = ch["bbox"], ch["origin"]
                    box = tight_box(bbox, origin, size, direction)
                    chars.append((ch["c"], bbox, box, origin, size, invisible))
            if chars:
                yield direction, chars


def extract_lines(page: pymupdf.Page, everywhere: bool = False) -> list[list[Char]]:
    """All text lines on the page in reading order, each as a list of characters.

    Only text inside the page area is included unless `everywhere` is set.
    """
    Rect, Point = pymupdf.Rect, pymupdf.Point
    return [
        [
            Char(c, Rect(bbox), Rect(box), Point(origin), size, n, direction, invisible)
            for c, bbox, box, origin, size, invisible in chars
        ]
        for n, (direction, chars) in enumerate(raw_lines(page, everywhere))
    ]


def line_texts(page: pymupdf.Page) -> list[str]:
    """The text of each line, like ``extract_lines`` but much faster as it skips geometry."""
    return page.get_text("text", flags=TEXT_FLAGS).split("\n")


def page_text_payload(page: pymupdf.Page) -> dict:
    """Text geometry for the UI, in display space."""
    out_lines = []
    unmapped = 0
    has_text = False
    # The rotation is a multiple of 90 degrees, so two opposite corners give the rotated box.
    a, b, c, d, e, f = page.rotation_matrix
    unrotated = page.rotation == 0
    for (dx, dy), chars in raw_lines(page):
        boxes = []
        for _, _, (x0, y0, x1, y1), _, _, _ in chars:
            if unrotated:
                boxes.append([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)])
                continue
            px, py = x0 * a + y0 * c + e, x0 * b + y0 * d + f
            qx, qy = x1 * a + y1 * c + e, x1 * b + y1 * d + f
            boxes.append(
                [
                    round(min(px, qx), 2),
                    round(min(py, qy), 2),
                    round(max(px, qx), 2),
                    round(max(py, qy), 2),
                ]
            )
        text = [ch[0] for ch in chars]
        out_lines.append(
            {
                "bbox": [
                    min(r[0] for r in boxes),
                    min(r[1] for r in boxes),
                    max(r[2] for r in boxes),
                    max(r[3] for r in boxes),
                ],
                "chars": text,
                "boxes": boxes,
                "dir": [round(dx * a + dy * c, 4), round(dx * b + dy * d, 4)],
            }
        )
        unmapped += text.count(REPLACEMENT_CHAR)
        has_text = has_text or any(not ch.isspace() for ch in text)
    return {
        "index": page.number,
        "width": round(page.rect.width, 2),
        "height": round(page.rect.height, 2),
        "lines": out_lines,
        "hasText": has_text,
        "unmappedChars": unmapped,
    }
