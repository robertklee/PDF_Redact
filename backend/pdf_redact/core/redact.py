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

from .geometry import contains_point, full_extent, overlaps, page_area, to_unrotated
from .objects import delete_key, strip_page_text_properties, strip_struct_text
from .overlay import DIRECTIONS, Appearance, drawable, layout_overlay
from .progress import report
from .removal import apply_regions, removal_bands, remove_glyphs
from .sanitize import SanitizeAction, SanitizeOptions, sanitize_document
from .text import Char, all_text_lines, extract_lines

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
    # Removal of hidden information; None leaves the rest of the document as it is.
    sanitize: SanitizeOptions | None = None


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
    sanitized: list[SanitizeAction] = field(default_factory=list)


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


def chars_text(lines: Iterable[list[Char]], chars: Iterable[Char]) -> str:
    """The text of `chars`, one line of the page per line."""
    chosen = {id(ch) for ch in chars}
    parts = ["".join(ch.c for ch in line if id(ch) in chosen) for line in lines]
    return "\n".join(p for p in parts if p.strip())


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
                delete_key(doc, parent, key)

    links = [link for link in page.get_links() if covered(to_unrotated(page, link["from"]))]
    for link in links:
        page.delete_link(link)
    return len(annots) + len(widgets) + len(links)


def delete_redact_annots(page: pymupdf.Page) -> None:
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
            areas.append((full_extent(page), None))

    if text_regions:
        # Including glyphs the user cannot see: clipped away, or in a layer that is switched off.
        targets = selected_chars(all_text_lines(page), text_regions)
        stats.glyphs_removed += len(targets)
        remove_glyphs(page, removal_bands(targets))
        survivors = selected_chars(all_text_lines(page), text_regions)
        if survivors:
            stats.safety_pass_glyphs += len(survivors)
            remove_glyphs(page, [ch.bbox for ch in survivors])

    apply_regions(
        page,
        [(c.region, c.appearance.fill) for c in covers],
        images,
        graphics,
        pymupdf.PDF_REDACT_TEXT_NONE,
    )
    apply_regions(
        page,
        [(r, None if owner is None else owner.appearance.fill) for r, owner in areas],
        images,
        graphics,
        pymupdf.PDF_REDACT_TEXT_REMOVE,
    )

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
    if options.sanitize is not None:
        # Before the marks, so flattened fields and comments are page content they can redact.
        stats.sanitized = sanitize_document(doc, options.sanitize)
    for page in doc:
        # apply_redactions() would apply these too, and elsewhere they would be left unapplied.
        delete_redact_annots(page)
    for done, pno in enumerate(sorted(by_page)):
        report("Applying redactions", done, len(by_page))
        page = doc[pno]
        redact_page(page, by_page[pno], options, stats)
        regions = [r for m in by_page[pno] for r in mark_regions(page, m)]
        stats.annotations_removed += _remove_covered_annotations(page, regions)
        stats.replacement_text_removed += strip_page_text_properties(doc, page)
    if by_page:
        pages = {doc[pno].xref for pno in by_page}
        stats.replacement_text_removed += strip_struct_text(doc, pages)
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
        report("Saving the redacted file")
        return save_redacted(doc), stats
