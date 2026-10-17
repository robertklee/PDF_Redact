"""Optional content (layers): which content is hidden, and merging layers into the page.

Visibility follows the document's default configuration, which is what viewers show when the file
is opened: OCGs that are off, and membership dictionaries (OCMDs) whose policy or visibility
expression evaluates to hidden. Hidden content is removed; visible content stays in place with its
layer markers flattened, after which the layer definitions are deleted.
"""

from __future__ import annotations

import re

import pymupdf

from .content import ContentError, optional_content_markers, remove_hidden_content
from .objects import Node, child, delete_key, get, keys, page_streams, ref_xref, xobjects

_REF = re.compile(r"(\d+)\s+\d+\s+R")
_VE_TOKEN = re.compile(r"\[|\]|/[A-Za-z]+|\d+\s+\d+\s+R")
_MAX_DEPTH = 32


def _refs(value: str) -> list[int]:
    return [int(m.group(1)) for m in _REF.finditer(value)]


def _parse_ve(value: str) -> list | int:
    """A visibility expression as nested lists of operator names and OCG xrefs."""
    tokens = _VE_TOKEN.findall(value)
    pos = 0

    def item(depth: int) -> list | int:
        nonlocal pos
        if depth > _MAX_DEPTH or pos >= len(tokens):
            raise ValueError("malformed visibility expression")
        token = tokens[pos]
        pos += 1
        if token == "[":
            items: list = []
            while pos < len(tokens) and tokens[pos] != "]":
                items.append(item(depth + 1))
            pos += 1
            return items
        if token.startswith("/"):
            return token  # type: ignore[return-value]
        if token == "]":
            raise ValueError("malformed visibility expression")
        return int(token.split()[0])

    return item(0)


class Visibility:
    """Default visibility of optional content in a document."""

    def __init__(self, doc: pymupdf.Document):
        self.doc = doc
        self.ocgs = {xref: bool(info["on"]) for xref, info in doc.get_ocgs().items()}
        self._cache: dict[int, bool] = {}

    def hidden(self, xref: int | None) -> bool:
        """Whether content marked with the OCG or OCMD `xref` is hidden. Unknown means visible."""
        if xref is None:
            return False
        if xref in self.ocgs:
            return not self.ocgs[xref]
        if xref not in self._cache:
            visible = True
            if self.doc.xref_get_key(xref, "Type")[1] == "/OCMD":
                visible = self._ocmd_visible(xref)
            self._cache[xref] = not visible
        return self._cache[xref]

    def _ocmd_visible(self, xref: int) -> bool:
        kind, value = self.doc.xref_get_key(xref, "VE")
        if kind == "array":
            try:
                return self._evaluate(_parse_ve(value))
            except ValueError:
                pass
        members = _refs(self.doc.xref_get_key(xref, "OCGs")[1])
        if not members:
            return True
        states = [self.ocgs.get(m, True) for m in members]
        policy = self.doc.xref_get_key(xref, "P")[1]
        if policy == "/AllOn":
            return all(states)
        if policy == "/AnyOff":
            return not all(states)
        if policy == "/AllOff":
            return not any(states)
        return any(states)

    def _evaluate(self, expr: list | int) -> bool:
        if isinstance(expr, int):
            return self.ocgs.get(expr, True)
        if not expr or not isinstance(expr[0], str):
            raise ValueError("malformed visibility expression")
        operator, operands = expr[0], [self._evaluate(e) for e in expr[1:]]
        if operator == "/Not" and len(operands) == 1:
            return not operands[0]
        if operator == "/And" and operands:
            return all(operands)
        if operator == "/Or" and operands:
            return any(operands)
        raise ValueError("malformed visibility expression")


def _oc(doc: pymupdf.Document, xref: int) -> int | None:
    kind, value = doc.xref_get_key(xref, "OC")
    return ref_xref(value) if kind == "xref" else None


def _property_xref(doc: pymupdf.Document, resources: Node | None, name: bytes) -> int | None:
    table = child(doc, resources, "Properties") if resources else None
    if table is None:
        return None
    kind, value = get(doc, table, name.decode("latin-1"))
    return ref_xref(value) if kind == "xref" else None


def _is_layer(doc: pymupdf.Document, xref: int | None) -> bool:
    return bool(xref) and doc.xref_get_key(xref, "Type")[1] in ("/OCG", "/OCMD")


def _drop_layer_properties(doc: pymupdf.Document, resources: Node | None) -> None:
    table = child(doc, resources, "Properties") if resources else None
    if table is None:
        return
    for name in keys(doc, table):
        kind, value = get(doc, table, name)
        if kind == "xref" and _is_layer(doc, ref_xref(value)):
            delete_key(doc, table.xref, table.key(name))


def _delete_annotation(page: pymupdf.Page, xref: int, kind: int) -> None:
    if kind == pymupdf.PDF_ANNOT_WIDGET:
        page.delete_widget(page.load_widget(xref))
    elif kind == pymupdf.PDF_ANNOT_LINK:
        page.delete_link({"xref": xref, "kind": pymupdf.LINK_NONE})
    else:
        page.delete_annot(page.load_annot(xref))


def has_layers(doc: pymupdf.Document) -> bool:
    return doc.xref_get_key(doc.pdf_catalog(), "OCProperties")[0] != "null"


def merge_layers(doc: pymupdf.Document) -> int:
    """Remove hidden optional content and merge the rest into the page.

    Returns the number of hidden layers whose content was removed.
    """
    if not has_layers(doc):
        return 0
    visibility = Visibility(doc)
    hidden_layers = sum(1 for on in visibility.ocgs.values() if not on)
    optional: set[int] = set()  # XObjects that carry their own /OC
    all_resources: set[Node] = set()
    for page in doc:
        for xref, resources in page_streams(doc, page):
            data = doc.xref_stream(xref)
            names = dict(xobjects(doc, resources))
            optional.update(x for x in names.values() if _oc(doc, x) is not None)

            def hidden_xobject(name: bytes, names: dict[str, int] = names) -> bool:
                target = names.get(name.decode("latin-1"))
                return target is not None and visibility.hidden(_oc(doc, target))

            if data:
                try:
                    result = remove_hidden_content(
                        data,
                        lambda name, res=resources: visibility.hidden(
                            _property_xref(doc, res, name)
                        ),
                        hidden_xobject=hidden_xobject,
                    )
                except ContentError:
                    result = None
                if result is not None and result.data is not None:
                    doc.update_stream(xref, result.data)
            if resources is not None:
                all_resources.add(resources)
        for xref, kind, _ in page.annot_xrefs():
            if (oc := _oc(doc, xref)) is None:
                continue
            if visibility.hidden(oc):
                _delete_annotation(page, xref, kind)
            else:
                delete_key(doc, xref, "OC")
    # Only now: streams sharing these resources must all resolve their layers first.
    for resources in all_resources:
        _drop_layer_properties(doc, resources)
    for xref in optional:
        delete_key(doc, xref, "OC")
    delete_key(doc, doc.pdf_catalog(), "OCProperties")
    return hidden_layers


def layer_problems(doc: pymupdf.Document) -> list[str]:
    """What is left of optional content in a document that should have none."""
    problems = []
    if has_layers(doc):
        problems.append("layer definitions remain")
    markers = 0
    for page in doc:
        for xref, _ in page_streams(doc, page):
            try:
                markers += optional_content_markers(doc.xref_stream(xref) or b"")
            except ContentError:
                continue
    if markers:
        problems.append(f"{markers} layer marker{'s' if markers != 1 else ''} remain in content")
    tagged = sum(
        1
        for xref in range(1, doc.xref_length())
        if doc.xref_get_key(xref, "OC")[0] != "null" or _is_layer(doc, xref)
    )
    if tagged:
        problems.append(f"{tagged} layer object{'s' if tagged != 1 else ''} remain")
    return problems
