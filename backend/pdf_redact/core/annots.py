"""Unapplied marks as standard /Redact annotations ("mark now, apply later").

Exporting writes one annotation per mark, so the marks can be reviewed or applied in Acrobat and
other tools. Importing turns such annotations back into marks. Text marks list one quadrilateral
per rectangle in /QuadPoints, which redaction applies separately (the text between two marked words
survives); area and page marks use /Rect alone. On import, an annotation with /QuadPoints becomes a
text mark, one covering the whole page a page mark, and any other an area mark.

The annotations' appearance is a red outline only: a viewer that does not apply redactions must not
make the (still present) content look removed.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

import pymupdf

from .geometry import to_display, union
from .overlay import Appearance
from .redact import (
    Mark,
    chars_text,
    delete_redact_annots,
    open_pdf,
    selected_chars,
    text_angle,
)
from .text import extract_lines

FONTS = {"helv": "Helv", "tiro": "TiRo", "cour": "Cour"}
ALIGN = {"left": 0, "center": 1, "right": 2}
OUTLINE = (1.0, 0.0, 0.0)
# An annotation covering this share of the visible page is imported as a page mark.
PAGE_COVERAGE = 0.98
MAX_OVERLAY_TEXT = 200
MAX_ID = 100


@dataclass
class ImportedMark:
    mark: Mark  # display space, like marks from the UI
    text: str = ""  # the text under a text mark
    angle: int | None = None  # display-space writing angle of that text


def _num(v: float) -> str:
    return f"{round(v, 4):g}"


def _array(values: Iterable[float]) -> str:
    return "[" + " ".join(_num(v) for v in values) + "]"


def _add_annot(
    page: pymupdf.Page,
    regions: list[pymupdf.Rect],
    appearance: Appearance,
    name: str,
    quads: bool,
) -> None:
    """One /Redact annotation covering `regions` (display space)."""
    doc = page.parent
    to_pdf = page.derotation_matrix * ~page.transformation_matrix
    annot = page.add_redact_annot(union(regions) * page.derotation_matrix)
    xref = annot.xref
    if quads:
        # Corners in Acrobat's order (upper left, upper right, lower left, lower right) as seen on
        # the displayed page, so they follow the text on rotated pages.
        points = [p * to_pdf for r in regions for p in (r.tl, r.tr, r.bl, r.br)]
        doc.xref_set_key(xref, "QuadPoints", _array(v for p in points for v in (p.x, p.y)))
    if appearance.fill is not None:
        doc.xref_set_key(xref, "IC", _array(appearance.fill))
    size = appearance.font_size or 0  # 0 = fit the text to the box
    da = f"{_array(appearance.text_color)[1:-1]} rg /{FONTS[appearance.font]} {_num(size)} Tf"
    doc.xref_set_key(xref, "DA", pymupdf.get_pdf_str(da))
    doc.xref_set_key(xref, "Q", str(ALIGN[appearance.align]))
    if appearance.overlay_text:
        doc.xref_set_key(xref, "OverlayText", pymupdf.get_pdf_str(appearance.overlay_text))
        doc.xref_set_key(xref, "Repeat", "true" if appearance.repeat else "false")
    doc.xref_set_key(xref, "C", _array(OUTLINE))
    doc.xref_set_key(xref, "NM", pymupdf.get_pdf_str(name))

    # The appearance form's BBox is the annotation /Rect in default user space.
    kind, ap = doc.xref_get_key(xref, "AP/N")
    if kind == "xref":
        boxes = []
        for r in regions:
            box = pymupdf.Rect(r * to_pdf)
            box = pymupdf.Rect(box.x0 + 0.5, box.y0 + 0.5, box.x1 - 0.5, box.y1 - 0.5)
            boxes.append(f"{_num(box.x0)} {_num(box.y0)} {_num(box.width)} {_num(box.height)} re")
        content = f"{_array(OUTLINE)[1:-1]} RG 1 w " + " ".join(boxes) + " S"
        doc.update_stream(int(ap.split()[0]), content.encode())


def write_redact_annots(doc: pymupdf.Document, marks: Iterable[Mark]) -> int:
    """Replace the document's /Redact annotations with `marks`. Returns the annotation count."""
    marks = list(marks)
    for mark in marks:
        if not 0 <= mark.page < doc.page_count:
            raise ValueError(f"Mark {mark.id} refers to page {mark.page}, which does not exist")
    for page in doc:
        delete_redact_annots(page)
    count = 0
    for mark in marks:
        page = doc[mark.page]
        if mark.kind == "page":
            groups = [[page.rect]]
        else:
            rects = [pymupdf.Rect(r) for r in mark.rects if pymupdf.Rect(r).is_valid]
            rects = [r for r in rects if not r.is_empty]
            # An annotation without quadrilaterals has a single area, so split multi-box areas.
            groups = [rects] if mark.kind == "text" else [[r] for r in rects]
        for i, regions in enumerate(g for g in groups if g):
            name = mark.id if i == 0 else f"{mark.id}-{i + 1}"
            _add_annot(page, regions, mark.appearance, name, quads=mark.kind == "text")
            count += 1
    return count


def marked_bytes(data: bytes, marks: Iterable[Mark], password: str | None = None) -> bytes:
    """A copy of the PDF carrying `marks` as unapplied /Redact annotations. Nothing is removed."""
    with open_pdf(data, password) as doc:
        write_redact_annots(doc, marks)
        return doc.tobytes(garbage=3, deflate=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)


def _floats(value: str) -> list[float]:
    return [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)", value)]


def _color(values: list[float]) -> tuple[float, float, float] | None:
    values = [min(max(v, 0.0), 1.0) for v in values]
    if len(values) == 1:
        return (values[0],) * 3  # type: ignore[return-value]
    if len(values) == 3:
        return tuple(values)  # type: ignore[return-value]
    if len(values) == 4:
        c, m, y, k = values
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _font(name: str) -> str:
    name = name.lower()
    if name.startswith(("tiro", "times")):
        return "tiro"
    if name.startswith("cour"):
        return "cour"
    return "helv"


def _appearance(doc: pymupdf.Document, xref: int) -> Appearance:
    def get(key: str) -> tuple[str, str]:
        return doc.xref_get_key(xref, key)

    appearance = Appearance()
    kind, value = get("IC")
    appearance.fill = _color(_floats(value)) if kind == "array" else None

    kind, da = get("DA")
    if kind == "string":
        if m := re.search(r"([-+.\d\s]+)\s(rg|g|k)\b", da):
            n = {"g": 1, "rg": 3, "k": 4}[m[2]]
            appearance.text_color = _color(_floats(m[1])[-n:]) or appearance.text_color
        if m := re.search(r"/([^\s/]+)\s+([-+.\d]+)\s+Tf", da):
            appearance.font = _font(m.group(1))
            size = _floats(m.group(2))
            if size and size[0] > 0:
                appearance.font_size = min(max(size[0], 4.0), 72.0)

    kind, text = get("OverlayText")
    if kind == "string":
        appearance.overlay_text = text[:MAX_OVERLAY_TEXT]
    kind, value = get("Q")
    if kind == "int" and value in ("0", "1", "2"):
        appearance.align = ("left", "center", "right")[int(value)]
    appearance.repeat = get("Repeat") == ("bool", "true")
    return appearance


def read_redact_annots(doc: pymupdf.Document) -> list[ImportedMark]:
    """The document's /Redact annotations as marks, in page order."""
    imported: list[ImportedMark] = []
    ids: set[str] = set()
    for page in doc:
        annots = list(page.annots(types=[pymupdf.PDF_ANNOT_REDACT]))
        if not annots:
            continue
        visible = page.rect
        lines = None
        for annot in annots:
            vertices = annot.vertices or []
            quads = [pymupdf.Quad(vertices[i : i + 4]).rect for i in range(0, len(vertices) - 3, 4)]
            regions = [to_display(page, r) & visible for r in (quads or [annot.rect])]
            regions = [r for r in regions if r.is_valid and not r.is_empty]
            if not regions:
                continue
            if quads:
                kind = "text"
            elif regions[0].get_area() >= PAGE_COVERAGE * visible.get_area():
                kind = "page"
            else:
                kind = "area"

            kind_nm, name = doc.xref_get_key(annot.xref, "NM")
            mark_id = name if kind_nm == "string" and 0 < len(name) <= MAX_ID else ""
            if not mark_id or mark_id in ids:
                mark_id = str(uuid.uuid4())
            ids.add(mark_id)

            rects = [] if kind == "page" else [tuple(r) for r in regions]
            appearance = _appearance(doc, annot.xref)
            item = ImportedMark(Mark(mark_id, page.number, kind, rects, appearance))  # type: ignore[arg-type]
            if kind == "text":
                lines = lines if lines is not None else extract_lines(page)
                chars = selected_chars(lines, [r * page.derotation_matrix for r in regions])
                item.text = chars_text(lines, chars)
                item.angle = text_angle(page, chars)
            imported.append(item)
    return imported
