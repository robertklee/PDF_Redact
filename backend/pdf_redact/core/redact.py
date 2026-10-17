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
metrics) using the glyph's full box. Finally, marked-content replacement text (``/ActualText``),
which MuPDF keeps and which can repeat the removed words, is stripped from redacted pages.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import pymupdf

from .geometry import contains_point, overlaps, page_area, to_unrotated
from .objects import strip_page_text_properties
from .overlay import DIRECTIONS, Appearance, drawable, layout_overlay
from .text import Char, extract_lines

MarkKind = Literal["text", "area", "page"]
ImageMode = Literal["pixels", "remove", "none"]
GraphicsMode = Literal["covered", "touched", "none"]

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

# Tolerance (points) when deciding whether a glyph centre lies inside a text mark.
SELECT_TOLERANCE = 0.5
# How far past the page edges page marks reach to remove content placed off the page.
OFF_PAGE = 100_000
# Removal band through each glyph, as fractions of the font size above the baseline.
BAND_LOW, BAND_HIGH = 0.30, 0.45


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
    # Marks with overlay text that did not fit (in at least one of their boxes).
    overlays_skipped: list[str] = field(default_factory=list)
    # Content streams and property lists whose replacement text (/ActualText etc.) was removed.
    replacement_text_removed: int = 0
    # Annotations, form fields and links that overlapped a mark and were deleted.
    annotations_removed: int = 0


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
    """Everything the page could draw, including content placed outside the MediaBox."""
    return pymupdf.Rect(page_area(page)) + (-OFF_PAGE, -OFF_PAGE, OFF_PAGE, OFF_PAGE)


def _add_box(page: pymupdf.Page, region: pymupdf.Rect, appearance: Appearance) -> None:
    page.add_redact_annot(region, fill=appearance.fill, cross_out=False)


def text_angle(page: pymupdf.Page, chars: Iterable[Char]) -> int | None:
    """Dominant display-space writing angle (0/90/180/270) of the glyphs, if axis-aligned."""
    votes: dict[int, int] = defaultdict(int)
    m = page.rotation_matrix
    for ch in chars:
        d = pymupdf.Point(ch.dir) * m - pymupdf.Point(0, 0) * m
        for angle, (dx, dy) in DIRECTIONS.items():
            if d.x * dx + d.y * dy > 0.999:
                votes[angle] += 1
    return max(votes, key=votes.__getitem__) if votes else None


@dataclass
class Overlay:
    region: pymupdf.Rect  # unrotated space
    appearance: Appearance
    mark_id: str
    angle: int | None = None  # display-space writing angle; None = choose from the box shape


def _draw_overlays(page: pymupdf.Page, overlays: list[Overlay]) -> list[str]:
    """Write overlay text into each box, oriented as seen in the viewer.

    PyMuPDF's built-in overlay ignores /Rotate and needs ~1.7x the font size in height, so we
    position the text ourselves. Returns the ids of marks whose overlay text did not fit.
    """
    shape = page.new_shape()
    skipped: list[str] = []
    for overlay in overlays:
        appearance = overlay.appearance
        shown = overlay.region * page.rotation_matrix
        layout = layout_overlay(shown, appearance, overlay.angle)
        if layout is None:
            if drawable(appearance.overlay_text) and overlay.mark_id not in skipped:
                skipped.append(overlay.mark_id)
            continue
        for line in layout.lines:
            shape.insert_text(
                pymupdf.Point(line.x, line.y) * page.derotation_matrix,
                line.text,
                fontname=appearance.font,
                fontsize=layout.size,
                color=appearance.text_color,
                rotate=(page.rotation + layout.angle) % 360,
            )
    shape.commit()
    return skipped


def _remove_glyphs(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> None:
    for r in rects:
        page.add_redact_annot(r, fill=None, cross_out=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )


def _field_parent(doc: pymupdf.Document, xref: int) -> int | None:
    """The field a widget belongs to, if the widget is a kid of a separate field dictionary."""
    if doc.xref_get_key(xref, "T")[0] != "null":
        return None
    kind, value = doc.xref_get_key(xref, "Parent")
    return int(value.split()[0]) if kind == "xref" else None


def _field_kids(doc: pymupdf.Document, xref: int) -> set[int]:
    kind, value = doc.xref_get_key(xref, "Kids")
    if kind != "array":
        return set()
    parts = value.strip("[]").split()
    return {int(parts[i]) for i in range(0, len(parts) - 2, 3) if parts[i + 2] == "R"}


def _remove_covered_annotations(page: pymupdf.Page, regions: list[pymupdf.Rect]) -> int:
    """Delete annotations, form fields and links that overlap a redacted region: their comments,
    values and targets are part of what is being redacted."""
    doc = page.parent

    def covered(rect: pymupdf.Rect) -> bool:
        return any(overlaps(rect, region) for region in regions)

    annots = [
        a.xref
        for a in page.annots()
        if a.type[0] not in (pymupdf.PDF_ANNOT_REDACT, pymupdf.PDF_ANNOT_POPUP) and covered(a.rect)
    ]
    for xref in annots:
        page.delete_annot(page.load_annot(xref))

    widgets = [w.xref for w in page.widgets() if covered(w.rect)]
    parents: dict[int, set[int]] = defaultdict(set)
    for xref in widgets:
        parent = _field_parent(doc, xref)
        if parent is not None:
            parents[parent].add(xref)
        page.delete_widget(page.load_widget(xref))
    for parent, deleted in parents.items():
        # A field whose every widget was redacted must not keep its value.
        if _field_kids(doc, parent) <= deleted:
            for key in ("V", "DV"):
                doc.xref_set_key(parent, key, "null")

    links = [link for link in page.get_links() if covered(to_unrotated(page, link["from"]))]
    for link in links:
        page.delete_link(link)
    return len(annots) + len(widgets) + len(links)


def _delete_existing_redact_annots(page: pymupdf.Page) -> None:
    """Pre-existing /Redact annotations would otherwise be applied implicitly."""
    for xref in [a.xref for a in page.annots(types=[pymupdf.PDF_ANNOT_REDACT])]:
        page.delete_annot(page.load_annot(xref))


def redact_page(
    page: pymupdf.Page, marks: list[Mark], options: RedactOptions, stats: RedactStats
) -> None:
    images = IMAGE_MODES[options.images]
    graphics = GRAPHICS_MODES[options.graphics]

    text_regions: list[pymupdf.Rect] = []
    covers: list[Overlay] = []
    # No owning mark = remove content without drawing anything.
    areas: list[tuple[pymupdf.Rect, Mark | None]] = []
    lines = extract_lines(page) if any(m.kind == "text" for m in marks) else []

    for mark in marks:
        regions = mark_regions(page, mark)
        stats.rects += len(regions)
        if mark.kind == "text":
            chars = selected_chars(lines, regions)
            if chars:
                text_regions += regions
                angle = text_angle(page, chars)
                covers += [Overlay(r, mark.appearance, mark.id, angle) for r in regions]
                continue
            stats.text_marks_as_area.append(mark.id)
        areas += [(r, mark) for r in regions]
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
        for region, owner in areas:
            if owner is None:
                page.add_redact_annot(region, fill=None, cross_out=False)
            else:
                _add_box(page, region, owner.appearance)
        page.apply_redactions(images=images, graphics=graphics, text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    covers += [Overlay(r, m.appearance, m.id) for r, m in areas if m is not None]
    stats.overlays_skipped += _draw_overlays(page, covers)


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
    for page in doc:
        # apply_redactions() would apply these too, and elsewhere they would be left unapplied.
        _delete_existing_redact_annots(page)
    for pno in sorted(by_page):
        page = doc[pno]
        redact_page(page, by_page[pno], options, stats)
        regions = [r for m in by_page[pno] for r in mark_regions(page, m)]
        stats.annotations_removed += _remove_covered_annotations(page, regions)
        stats.replacement_text_removed += strip_page_text_properties(doc, page)
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
    if doc.is_encrypted and not doc.authenticate(password or ""):
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
