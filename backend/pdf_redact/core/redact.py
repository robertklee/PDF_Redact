"""True redaction engine.

MuPDF removes a glyph when its *font* bounding box (ascender to descender) touches a redaction
rectangle at all. Font boxes of adjacent lines often overlap, so redacting a text line's visual box
would also delete glyphs from the lines above and below. To be both precise and complete, text
marks are applied in passes:

1. **Glyph removal**: thin bands through the vertical middle of the selected glyphs remove exactly
   those glyphs (text only; images and graphics untouched).
2. **Cover**: the visual rectangles blank image pixels, remove covered vector graphics, and draw
   the fill box plus overlay text. Text is left alone in this pass so neighbours survive.
3. **Area marks** remove everything they touch (text, image pixels, graphics), just like Acrobat.

A safety pass then removes any selected glyph that survived the bands (e.g. fonts with unusual
metrics) using the glyph's full box.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import pymupdf

from .geometry import contains_point, page_area, to_unrotated, union
from .text import Char, extract_lines

MarkKind = Literal["text", "area", "page"]
ImageMode = Literal["pixels", "remove", "none"]
GraphicsMode = Literal["covered", "touched", "none"]
Color = tuple[float, float, float]

IMAGE_MODES: dict[str, int] = {
    "pixels": pymupdf.PDF_REDACT_IMAGE_PIXELS,
    "remove": pymupdf.PDF_REDACT_IMAGE_REMOVE,
    "none": pymupdf.PDF_REDACT_IMAGE_NONE,
}
GRAPHICS_MODES: dict[str, int] = {
    "covered": pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
    "touched": pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
    "none": pymupdf.PDF_REDACT_LINE_ART_NONE,
}

OVERLAY_FONT = "helv"
_OVERLAY_METRICS = pymupdf.Font(OVERLAY_FONT)
# Ascender-to-descender height of the overlay font, plus a little breathing room.
OVERLAY_LINE_HEIGHT = 1.4
OVERLAY_PADDING = 1.0
MIN_OVERLAY_FONT_SIZE = 4.0
MAX_AUTO_FONT_SIZE = 24.0
# Tolerance (points) when deciding whether a glyph centre lies inside a text mark.
SELECT_TOLERANCE = 0.5
# Removal band through each glyph, as fractions of the font size above the baseline.
BAND_LOW, BAND_HIGH = 0.30, 0.45


@dataclass
class Appearance:
    fill: Color | None = (0.0, 0.0, 0.0)
    text_color: Color = (1.0, 1.0, 1.0)
    overlay_text: str = ""
    font_size: float | None = None  # None = auto-fit to the box
    align: Literal["left", "center", "right"] = "center"


@dataclass
class Mark:
    id: str
    page: int
    kind: MarkKind
    rects: list[tuple[float, float, float, float]]  # display space
    appearance: Appearance = field(default_factory=Appearance)


@dataclass
class RedactOptions:
    images: ImageMode = "pixels"
    graphics: GraphicsMode = "covered"


@dataclass
class RedactStats:
    marks: int = 0
    rects: int = 0
    pages: list[int] = field(default_factory=list)
    glyphs_removed: int = 0
    # Text marks with no glyphs under them; applied as area marks instead.
    text_marks_as_area: list[str] = field(default_factory=list)
    # Glyphs that survived the band pass and were removed by the safety pass.
    safety_pass_glyphs: int = 0


def fit_font_size(text: str, width: float, height: float, requested: float | None) -> float | None:
    """Largest overlay font size (capped by `requested`) that fits on one line, else None."""
    unit_width = pymupdf.get_text_length(text, fontname=OVERLAY_FONT, fontsize=1)
    if unit_width <= 0:
        return None
    fit = min((width - 2 * OVERLAY_PADDING) / unit_width, height / OVERLAY_LINE_HEIGHT)
    size = min(fit, requested or MAX_AUTO_FONT_SIZE)
    return round(size, 2) if size >= MIN_OVERLAY_FONT_SIZE else None


def mark_regions(page: pymupdf.Page, mark: Mark) -> list[pymupdf.Rect]:
    """The mark's regions in unrotated page space."""
    if mark.kind == "page":
        return [page_area(page)]
    return [to_unrotated(page, r) for r in mark.rects if pymupdf.Rect(r).is_valid]


def selected_chars(lines: Iterable[list[Char]], regions: list[pymupdf.Rect]) -> list[Char]:
    return [
        ch
        for line in lines
        for ch in line
        if any(contains_point(r, ch.center, SELECT_TOLERANCE) for r in regions)
    ]


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


def _full_extent(page: pymupdf.Page) -> pymupdf.Rect:
    """Visible area plus anything in the MediaBox outside the CropBox, in unrotated space."""
    mb, cb = page.mediabox, page.cropbox
    media = pymupdf.Rect(mb.x0 - cb.x0, mb.y0 - cb.y0, mb.x1 - cb.x0, mb.y1 - cb.y0)
    return union([page_area(page), media])


def _add_box(page: pymupdf.Page, region: pymupdf.Rect, appearance: Appearance) -> None:
    page.add_redact_annot(region, fill=appearance.fill, cross_out=False)


# Overlay writing directions in display space, keyed by counter-clockwise angle (y points down).
_DIRECTIONS: dict[int, tuple[float, float]] = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}


def text_angle(page: pymupdf.Page, chars: Iterable[Char]) -> int | None:
    """Dominant display-space writing angle (0/90/180/270) of the glyphs, if axis-aligned."""
    votes: dict[int, int] = defaultdict(int)
    m = page.rotation_matrix
    for ch in chars:
        d = pymupdf.Point(ch.dir) * m - pymupdf.Point(0, 0) * m
        for angle, (dx, dy) in _DIRECTIONS.items():
            if d.x * dx + d.y * dy > 0.999:
                votes[angle] += 1
    return max(votes, key=votes.__getitem__) if votes else None


@dataclass
class Overlay:
    region: pymupdf.Rect  # unrotated space
    appearance: Appearance
    angle: int | None = None  # display-space writing angle; None = choose from the box shape


def _overlay_layout(
    text: str, shown: pymupdf.Rect, appearance: Appearance, angle: int | None
) -> tuple[int, float] | None:
    def fit(a: int) -> float | None:
        along, across = (
            (shown.width, shown.height) if a in (0, 180) else (shown.height, shown.width)
        )
        return fit_font_size(text, along, across, appearance.font_size)

    if angle is not None:
        size = fit(angle)
        return (angle, size) if size else None
    size, size_vertical = fit(0), fit(90)
    # Tall, narrow boxes read better with bottom-to-top text.
    if size_vertical and (size is None or size_vertical > 1.5 * size):
        return 90, size_vertical
    return (0, size) if size else None


def _draw_overlays(page: pymupdf.Page, overlays: list[Overlay]) -> None:
    """Write overlay text centred in each box, oriented as seen in the viewer.

    PyMuPDF's built-in overlay ignores /Rotate and needs ~1.7x the font size in height, so we
    position the text ourselves.
    """
    shape = page.new_shape()
    asc, desc = _OVERLAY_METRICS.ascender, _OVERLAY_METRICS.descender
    for overlay in overlays:
        appearance = overlay.appearance
        text = appearance.overlay_text.strip()
        if not text:
            continue
        shown = overlay.region * page.rotation_matrix
        layout = _overlay_layout(text, shown, appearance, overlay.angle)
        if layout is None:
            continue
        angle, size = layout
        dx, dy = _DIRECTIONS[angle]
        ux, uy = dy, -dx
        width = pymupdf.get_text_length(text, fontname=OVERLAY_FONT, fontsize=size)
        along = abs(shown.width * dx + shown.height * dy)
        shift = {
            "left": -along / 2 + OVERLAY_PADDING,
            "center": -width / 2,
            "right": along / 2 - OVERLAY_PADDING - width,
        }[appearance.align]
        # Baseline sits below the centre line by half the glyph's ascender+descender height.
        drop = size * (asc + desc) / 2
        centre = (shown.tl + shown.br) / 2
        point = pymupdf.Point(centre.x + dx * shift - ux * drop, centre.y + dy * shift - uy * drop)
        shape.insert_text(
            point * page.derotation_matrix,
            text,
            fontname=OVERLAY_FONT,
            fontsize=size,
            color=appearance.text_color,
            rotate=(page.rotation + angle) % 360,
        )
    shape.commit()


def _remove_glyphs(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> None:
    for r in rects:
        page.add_redact_annot(r, fill=None, cross_out=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )


def _delete_existing_redact_annots(page: pymupdf.Page) -> None:
    """Pre-existing /Redact annotations would otherwise be applied implicitly."""
    for xref in [a.xref for a in page.annots(types=[pymupdf.PDF_ANNOT_REDACT])]:
        page.delete_annot(page.load_annot(xref))


def redact_page(
    page: pymupdf.Page, marks: list[Mark], options: RedactOptions, stats: RedactStats
) -> None:
    images = IMAGE_MODES[options.images]
    graphics = GRAPHICS_MODES[options.graphics]
    _delete_existing_redact_annots(page)

    text_regions: list[pymupdf.Rect] = []
    covers: list[Overlay] = []
    # Appearance None = remove content without drawing anything.
    areas: list[tuple[pymupdf.Rect, Appearance | None]] = []
    lines = extract_lines(page) if any(m.kind == "text" for m in marks) else []

    for mark in marks:
        regions = mark_regions(page, mark)
        stats.rects += len(regions)
        if mark.kind == "text":
            chars = selected_chars(lines, regions)
            if chars:
                text_regions += regions
                angle = text_angle(page, chars)
                covers += [Overlay(r, mark.appearance, angle) for r in regions]
                continue
            stats.text_marks_as_area.append(mark.id)
        areas += [(r, mark.appearance) for r in regions]
        if mark.kind == "page":
            # Also strip content hidden outside the CropBox.
            areas.append((_full_extent(page), None))

    if text_regions:
        targets = selected_chars(lines, text_regions)
        stats.glyphs_removed += len(targets)
        _remove_glyphs(page, removal_bands(targets))
        survivors = selected_chars(extract_lines(page), text_regions)
        if survivors:
            stats.safety_pass_glyphs += len(survivors)
            _remove_glyphs(page, [ch.bbox for ch in survivors])

    if covers:
        for cover in covers:
            _add_box(page, cover.region, cover.appearance)
        page.apply_redactions(images=images, graphics=graphics, text=pymupdf.PDF_REDACT_TEXT_NONE)

    if areas:
        for region, appearance in areas:
            if appearance is None:
                page.add_redact_annot(region, fill=None, cross_out=False)
            else:
                _add_box(page, region, appearance)
        page.apply_redactions(images=images, graphics=graphics, text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    _draw_overlays(page, covers + [Overlay(r, a) for r, a in areas if a is not None])


def apply_marks(
    doc: pymupdf.Document, marks: Iterable[Mark], options: RedactOptions | None = None
) -> RedactStats:
    options = options or RedactOptions()
    stats = RedactStats()
    by_page: dict[int, list[Mark]] = defaultdict(list)
    for mark in marks:
        if not 0 <= mark.page < doc.page_count:
            raise ValueError(f"Mark {mark.id} refers to page {mark.page}, which does not exist")
        by_page[mark.page].append(mark)
        stats.marks += 1
    for pno in sorted(by_page):
        redact_page(doc[pno], by_page[pno], options, stats)
    stats.pages = sorted(by_page)
    return stats


def save_redacted(doc: pymupdf.Document) -> bytes:
    """Full rewrite: drops unreferenced objects and earlier incremental revisions."""
    return doc.tobytes(
        garbage=4,
        deflate=True,
        clean=True,
        encryption=pymupdf.PDF_ENCRYPT_KEEP,
    )


def open_pdf(data: bytes, password: str | None = None) -> pymupdf.Document:
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        raise PermissionError("Incorrect or missing password")
    return doc


def redact_bytes(
    data: bytes,
    marks: Iterable[Mark],
    options: RedactOptions | None = None,
    password: str | None = None,
) -> tuple[bytes, RedactStats]:
    with open_pdf(data, password) as doc:
        stats = apply_marks(doc, marks, options)
        return save_redacted(doc), stats
