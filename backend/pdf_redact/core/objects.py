"""Helpers for walking PDF objects (resources, XObjects, property lists) with PyMuPDF."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pymupdf

from .content import (
    TEXT_PROPERTIES,
    ContentError,
    Operand,
    dict_entries,
    has_text_properties,
    property_names,
    strip_text_properties,
)

MAX_INHERITANCE = 64


@dataclass(frozen=True)
class Node:
    """A dictionary: an object (`path` empty) or a direct dictionary nested inside one."""

    xref: int
    path: str = ""

    def key(self, key: str) -> str:
        return f"{self.path}/{key}" if self.path else key


def get(doc: pymupdf.Document, node: Node, key: str) -> tuple[str, str]:
    return doc.xref_get_key(node.xref, node.key(key))


def child(doc: pymupdf.Document, node: Node, key: str) -> Node | None:
    """The dictionary stored under `key`, following an indirect reference."""
    kind, value = get(doc, node, key)
    if kind == "xref":
        xref = ref_xref(value)
        return Node(xref) if _is_dict(doc, xref) else None
    if kind == "dict":
        return Node(node.xref, node.key(key))
    return None


def _is_dict(doc: pymupdf.Document, xref: int | None) -> bool:
    if not xref or not 0 < xref < doc.xref_length():
        return False
    return doc.xref_object(xref, compressed=True).startswith("<<")


def ref_xref(value: str) -> int | None:
    parts = value.split()
    if len(parts) == 3 and parts[2] == "R" and parts[0].isdigit():
        return int(parts[0])
    return None


def keys(doc: pymupdf.Document, node: Node) -> list[str]:
    if not node.path:
        return list(doc.xref_get_keys(node.xref))
    kind, value = doc.xref_get_key(node.xref, node.path)
    if kind != "dict":
        return []
    data = value.encode("latin-1", "replace")
    try:
        entries = dict_entries(data, Operand(0, len(data), "dict"))
    except (ContentError, IndexError):
        return []
    return [key.decode("latin-1") for key, _, _ in entries]


def page_resources(doc: pymupdf.Document, page: pymupdf.Page) -> Node | None:
    """The page's resource dictionary, inherited from the page tree if needed."""
    xref = page.xref
    for _ in range(MAX_INHERITANCE):
        resources = child(doc, Node(xref), "Resources")
        if resources is not None:
            return resources
        kind, value = doc.xref_get_key(xref, "Parent")
        parent = ref_xref(value) if kind == "xref" else None
        if parent is None:
            return None
        xref = parent
    return None


def xobjects(doc: pymupdf.Document, resources: Node | None) -> Iterator[tuple[str, int]]:
    """(name, xref) of the XObjects in a resource dictionary."""
    table = child(doc, resources, "XObject") if resources else None
    if table is None:
        return
    for name in keys(doc, table):
        kind, value = get(doc, table, name)
        xref = ref_xref(value) if kind == "xref" else None
        if xref:
            yield name, xref


def is_form(doc: pymupdf.Document, xref: int) -> bool:
    return doc.xref_get_key(xref, "Subtype")[1] == "/Form" and doc.xref_is_stream(xref)


def page_streams(doc: pymupdf.Document, page: pymupdf.Page) -> Iterator[tuple[int, Node | None]]:
    """(xref, resources) of every content stream drawn by the page: its contents and, recursively,
    the form XObjects it uses."""
    resources = page_resources(doc, page)
    for xref in page.get_contents():
        yield xref, resources
    seen: set[int] = set()
    stack = [resources]
    while stack:
        res = stack.pop()
        for _, xref in xobjects(doc, res):
            if xref in seen or not is_form(doc, xref):
                continue
            seen.add(xref)
            form_resources = child(doc, Node(xref), "Resources") or res
            yield xref, form_resources
            stack.append(form_resources)


def property_list(doc: pymupdf.Document, resources: Node | None, name: str) -> Node | None:
    table = child(doc, resources, "Properties") if resources else None
    return child(doc, table, name) if table else None


def strip_page_text_properties(doc: pymupdf.Document, page: pymupdf.Page) -> int:
    """Remove marked-content replacement text (``/ActualText``, ``/Alt``, ``/E``) from everything
    the page draws. Returns the number of streams and property lists changed."""
    changed = 0
    for xref, resources in page_streams(doc, page):
        data = doc.xref_stream(xref)
        if not data:
            continue
        try:
            new = strip_text_properties(data)
            names = property_names(new if new is not None else data)
        except ContentError:
            continue
        if new is not None:
            doc.update_stream(xref, new)
            changed += 1
        for name in names:
            props = property_list(doc, resources, name.decode("latin-1"))
            if props is None:
                continue
            removed = False
            for key in TEXT_PROPERTIES:
                removed |= delete_key(doc, props.xref, props.key(key.decode()))
            changed += removed
    return changed


def page_has_text_properties(doc: pymupdf.Document, page: pymupdf.Page) -> bool | None:
    """Whether anything the page draws has marked-content replacement text (None: unreadable)."""
    for xref, resources in page_streams(doc, page):
        data = doc.xref_stream(xref)
        if not data:
            continue
        try:
            if has_text_properties(data):
                return True
            names = property_names(data)
        except ContentError:
            return None
        for name in names:
            props = property_list(doc, resources, name.decode("latin-1"))
            if props is not None and any(
                get(doc, props, key.decode())[0] != "null" for key in TEXT_PROPERTIES
            ):
                return True
    return False


def delete_key(doc: pymupdf.Document, xref: int, path: str) -> bool:
    """Delete a dictionary entry (``key`` or ``Outer/Inner/key``, following indirect references).

    ``xref_set_key(..., "null")`` would leave the key in the file with a null value. Returns
    whether the entry existed.
    """
    mupdf = pymupdf.mupdf
    obj = mupdf.pdf_load_object(pymupdf._as_pdf_document(doc), xref)
    *parents, last = path.split("/")
    for name in parents:
        if not mupdf.pdf_is_dict(obj):
            return False
        obj = mupdf.pdf_resolve_indirect(mupdf.pdf_dict_gets(obj, name))
    if not mupdf.pdf_is_dict(obj) or mupdf.pdf_is_null(mupdf.pdf_dict_gets(obj, last)):
        return False
    mupdf.pdf_dict_dels(obj, last)
    return True


def _struct_page(doc: pymupdf.Document, xref: int) -> int | None:
    """The page object a structure element belongs to: its own /Pg or the nearest ancestor's."""
    for _ in range(MAX_INHERITANCE):
        kind, value = doc.xref_get_key(xref, "Pg")
        if kind == "xref":
            return ref_xref(value)
        kind, value = doc.xref_get_key(xref, "P")
        parent = ref_xref(value) if kind == "xref" else None
        if parent is None or doc.xref_get_key(parent, "Type")[1] == "/StructTreeRoot":
            return None
        xref = parent
    return None


def struct_text_elements(doc: pymupdf.Document, pages: set[int]) -> list[int]:
    """Structure elements on the given pages (page object xrefs) that carry replacement or
    alternate text. Elements whose page is unknown are included, to be safe."""
    if doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] == "null":
        return []
    found = []
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "S")[0] != "name":
            continue
        if not any(doc.xref_get_key(xref, k.decode())[0] != "null" for k in TEXT_PROPERTIES):
            continue
        page = _struct_page(doc, xref)
        if page is None or page in pages:
            found.append(xref)
    return found


def strip_struct_text(doc: pymupdf.Document, pages: set[int]) -> int:
    """Remove ``/ActualText``, ``/Alt`` and ``/E`` from structure elements on the given pages.
    Returns the number of elements changed."""
    elements = struct_text_elements(doc, pages)
    for xref in elements:
        for key in TEXT_PROPERTIES:
            delete_key(doc, xref, key.decode())
    return len(elements)
