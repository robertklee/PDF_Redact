"""Independent inspection helpers used by tests to prove content is really gone."""

from __future__ import annotations

import io

import pymupdf
import pypdf

from pdf_redact.core.geometry import to_display, union
from pdf_redact.core.redact import Appearance, Mark
from pdf_redact.core.text import extract_lines


def pypdf_text(data: bytes, password: str | None = None) -> str:
    """Text as seen by a second, independent PDF engine."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt(password or "")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def mupdf_text(data: bytes, password: str | None = None) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.is_encrypted:
            doc.authenticate(password or "")
        return "\n".join(page.get_text() for page in doc)


def raw_contains(data: bytes, needle: str) -> bool:
    """Literal or hex-encoded occurrence anywhere in the raw file bytes (all revisions)."""
    lowered = data.lower()
    return needle.encode() in data or needle.encode().hex().encode() in lowered


def _pypdf_dump(obj, out: list[str], seen: set[int]) -> None:
    if isinstance(obj, pypdf.generic.IndirectObject):
        if obj.idnum in seen:
            return
        seen.add(obj.idnum)
        obj = obj.get_object()
    if isinstance(obj, pypdf.generic.StreamObject):
        try:
            data = obj.get_data()
        except Exception:  # undecodable image data etc.
            data = obj._data
        out.append(data.decode("latin-1"))
        out.append(data.hex())
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.append(str(key))
            _pypdf_dump(value, out, seen)
    elif isinstance(obj, list):
        for value in obj:
            _pypdf_dump(value, out, seen)
    elif isinstance(obj, (bytes, str)):
        out.append(str(obj) if isinstance(obj, str) else obj.decode("latin-1"))
        raw = obj.encode("utf-8") if isinstance(obj, str) else bytes(obj)
        out.append(raw.hex())


def pdf_dump(data: bytes, password: str | None = None) -> str:
    """Every object reachable from the trailer, with decoded streams and hex forms of strings,
    as seen by pypdf (an engine independent of MuPDF). Use `leaks()` to search it."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt(password or "")
    out: list[str] = []
    seen: set[int] = set()
    _pypdf_dump(reader.trailer, out, seen)
    for num in range(1, int(reader.trailer["/Size"])):
        try:
            obj = reader.get_object(num)
        except Exception:
            continue
        if obj is not None and num not in seen:
            seen.add(num)
            _pypdf_dump(obj, out, seen)
    return "\n".join(out)


def leaks(data: bytes, needle: str, password: str | None = None) -> bool:
    """Whether `needle` appears anywhere in the file's objects, decoded, in plain or hex form."""
    dump = pdf_dump(data, password).lower()
    forms = [needle, needle.encode().hex(), needle.encode("utf-16-be").hex()]
    return any(form.lower() in dump for form in forms)


def display_hits(data: bytes, needle: str, page: int = 0, password: str | None = None):
    """Display-space rects of `needle` on a page, built from tight char boxes like the UI does."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.is_encrypted:
            doc.authenticate(password or "")
        pg = doc[page]
        hits = []
        for line in extract_lines(pg):
            text = "".join(ch.c for ch in line)
            start = text.find(needle)
            while start >= 0:
                box = union([ch.box for ch in line[start : start + len(needle)]])
                hits.append(tuple(to_display(pg, box)))
                start = text.find(needle, start + 1)
        return hits


def text_mark(rects, page: int = 0, mark_id: str = "m1", overlay: str = "") -> Mark:
    return Mark(mark_id, page, "text", list(rects), Appearance(overlay_text=overlay))


def area_mark(rect, page: int = 0, mark_id: str = "a1", overlay: str = "") -> Mark:
    return Mark(mark_id, page, "area", [tuple(rect)], Appearance(overlay_text=overlay))
