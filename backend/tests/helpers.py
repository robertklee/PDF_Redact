"""Independent inspection helpers used by tests to prove content is really gone."""

from __future__ import annotations

import io

import pymupdf
import pypdf

from pdf_redact.core.geometry import to_display
from pdf_redact.core.redact import Appearance, Mark


def pypdf_text(data: bytes, password: str | None = None) -> str:
    """Text as seen by a second, independent PDF engine."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt(password or "")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def mupdf_text(data: bytes, password: str | None = None) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            doc.authenticate(password or "")
        return "\n".join(page.get_text() for page in doc)


def raw_contains(data: bytes, needle: str) -> bool:
    """Literal or hex-encoded occurrence anywhere in the raw file bytes (all revisions)."""
    lowered = data.lower()
    return needle.encode() in data or needle.encode().hex().encode() in lowered


def display_hits(data: bytes, needle: str, page: int = 0, password: str | None = None):
    """Display-space rects of `needle` on a page, as the UI would send them."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            doc.authenticate(password or "")
        pg = doc[page]
        return [tuple(to_display(pg, r)) for r in pg.search_for(needle)]


def text_mark(rects, page: int = 0, mark_id: str = "m1", overlay: str = "") -> Mark:
    return Mark(mark_id, page, "text", list(rects), Appearance(overlay_text=overlay))


def area_mark(rect, page: int = 0, mark_id: str = "a1", overlay: str = "") -> Mark:
    return Mark(mark_id, page, "area", [tuple(rect)], Appearance(overlay_text=overlay))
