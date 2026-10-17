"""Removal of hidden information, like Acrobat's "Remove Hidden Information".

`sanitize_document` runs on the opened document before marks are applied, so flattened form
fields and annotations become page content that marks can redact. `sanitize_checks` re-inspects
the saved output and proves each enabled option left nothing behind.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

import pymupdf

from .objects import Node, child, delete_key, get

AnnotationMode = Literal["remove", "flatten", "keep"]
FormMode = Literal["flatten", "reset", "keep"]

# Actions that run code, open other files or send data.
UNSAFE_ACTIONS = frozenset(
    {
        "/JavaScript",
        "/Launch",
        "/SubmitForm",
        "/ImportData",
        "/Rendition",
        "/Movie",
        "/Sound",
        "/GoToE",
        "/RichMediaExecute",
    }
)
_ACTION_TYPE = re.compile(r"/S\s*(/[A-Za-z]+)")


@dataclass
class SanitizeOptions:
    metadata: bool = True
    annotations: AnnotationMode = "remove"  # comments and markup
    forms: FormMode = "flatten"
    attachments: bool = True
    links: bool = True
    javascript: bool = True  # JavaScript and other unsafe or automatic actions
    thumbnails: bool = True
    bookmarks: bool = False
    page_labels: bool = False


@dataclass
class SanitizeAction:
    code: str
    count: int
    message: str


def _xrefs(doc: pymupdf.Document) -> Iterator[int]:
    for xref in range(1, doc.xref_length()):
        if doc.xref_object(xref, compressed=True) not in ("", "null"):
            yield xref


def _has_key(doc: pymupdf.Document, xref: int, key: str) -> bool:
    return doc.xref_get_key(xref, key)[0] != "null"


def _drop_key(doc: pymupdf.Document, xref: int, key: str) -> bool:
    return delete_key(doc, xref, key)


def _refs(value: str) -> list[int]:
    parts = value.strip("[]").split()
    return [
        int(parts[i])
        for i in range(len(parts) - 2)
        if parts[i + 2] == "R" and parts[i].isdigit() and parts[i + 1].isdigit()
    ]


def _is_unsafe(doc: pymupdf.Document, kind: str, value: str, depth: int = 0) -> bool:
    """Whether an action (or a chain of actions through ``/Next``) contains an unsafe one."""
    if depth > 32:
        return True
    if kind == "xref":
        xref = int(value.split()[0])
        if doc.xref_get_key(xref, "S")[1] in UNSAFE_ACTIONS:
            return True
        return _is_unsafe(doc, *doc.xref_get_key(xref, "Next"), depth + 1)
    if kind == "array":
        return any(_is_unsafe(doc, "xref", f"{r} 0 R", depth + 1) for r in _refs(value))
    if kind == "dict":
        types = set(_ACTION_TYPE.findall(value))
        return bool(types & UNSAFE_ACTIONS) or any(
            _is_unsafe(doc, "xref", f"{r} 0 R", depth + 1) for r in _refs(value)
        )
    return False


# --- individual options -------------------------------------------------------------------------


def remove_metadata(doc: pymupdf.Document) -> int:
    removed = sum(1 for k, v in doc.metadata.items() if v and k not in ("format", "encryption"))
    doc.set_metadata({})
    if doc.get_xml_metadata():
        removed += 1
    doc.del_xml_metadata()
    for xref in _xrefs(doc):
        # XMP on pages, images and fonts, and private application data (e.g. Illustrator).
        removed += _drop_key(doc, xref, "Metadata") + _drop_key(doc, xref, "PieceInfo")
    return removed


def flatten_forms(doc: pymupdf.Document) -> int:
    count = sum(1 for page in doc for _ in page.widgets())
    if count:
        doc.bake(annots=False, widgets=True)
    return count + _drop_form(doc)


def _form_fields(doc: pymupdf.Document) -> list[int]:
    """Every field dictionary in the form's field tree (roots first)."""
    form = child(doc, Node(doc.pdf_catalog()), "AcroForm")
    if form is None:
        return []
    kind, value = get(doc, form, "Fields")
    stack = list(reversed(_refs(value))) if kind == "array" else []
    fields: list[int] = []
    seen: set[int] = set()
    while stack:
        xref = stack.pop()
        if xref in seen or not 0 < xref < doc.xref_length():
            continue
        seen.add(xref)
        fields.append(xref)
        kind, value = doc.xref_get_key(xref, "Kids")
        if kind == "array":
            stack += reversed(_refs(value))
    return fields


def _holds_value(doc: pymupdf.Document, xref: int) -> bool:
    return doc.xref_get_key(xref, "V") != doc.xref_get_key(xref, "DV")


def reset_forms(doc: pymupdf.Document) -> int:
    """Set every field back to its default value and regenerate its appearance."""
    fields = _form_fields(doc)
    count = sum(_holds_value(doc, xref) for xref in fields)
    mupdf = pymupdf.mupdf
    pdf = pymupdf._as_pdf_document(doc)
    for xref in fields:
        if _holds_value(doc, xref):
            mupdf.pdf_field_reset(pdf, mupdf.pdf_load_object(pdf, xref))
    for page in doc:
        for widget in page.widgets():
            widget.update()
    _drop_key(doc, doc.pdf_catalog(), "AcroForm/XFA")
    return count


def _drop_form(doc: pymupdf.Document) -> int:
    """Remove a form left with no fields (and any XFA data, which holds field values)."""
    catalog = doc.pdf_catalog()
    xfa = _has_key(doc, catalog, "AcroForm/XFA")
    if not any(True for page in doc for _ in page.widgets()):
        _drop_key(doc, catalog, "AcroForm")
    else:
        _drop_key(doc, catalog, "AcroForm/XFA")
    return int(xfa)


def _annotations(page: pymupdf.Page, types: list[int] | None = None) -> list[int]:
    return [a.xref for a in page.annots(types=types) if a.type[0] != pymupdf.PDF_ANNOT_POPUP]


def _delete_annotations(page: pymupdf.Page, xrefs: list[int]) -> None:
    for xref in xrefs:
        page.delete_annot(page.load_annot(xref))


def remove_annotations(doc: pymupdf.Document) -> int:
    count = 0
    for page in doc:
        xrefs = _annotations(page)
        _delete_annotations(page, xrefs)
        # Popups whose parent is gone (deleting a parent deletes its popup).
        _delete_annotations(page, [a.xref for a in page.annots()])
        count += len(xrefs)
    return count


def flatten_annotations(doc: pymupdf.Document) -> int:
    count = 0
    for page in doc:
        # Unapplied redactions from other tools would look redacted without removing anything.
        _delete_annotations(page, _annotations(page, [pymupdf.PDF_ANNOT_REDACT]))
        count += len(_annotations(page))
    if count:
        doc.bake(annots=True, widgets=False)
    return count


def remove_links(doc: pymupdf.Document) -> int:
    count = 0
    for page in doc:
        links = page.get_links()
        for link in links:
            page.delete_link(link)
        count += len(links)
    return count


def remove_attachments(doc: pymupdf.Document) -> int:
    count = 0
    for name in doc.embfile_names():
        doc.embfile_del(name)
        count += 1
    for page in doc:
        xrefs = _annotations(page, [pymupdf.PDF_ANNOT_FILE_ATTACHMENT])
        _delete_annotations(page, xrefs)
        count += len(xrefs)
    catalog = doc.pdf_catalog()
    _drop_key(doc, catalog, "Names/EmbeddedFiles")
    _drop_key(doc, catalog, "Collection")
    for xref in _xrefs(doc):
        # Associated files (PDF/A-3) and file specifications that embed a file.
        count += _drop_key(doc, xref, "AF") + _drop_key(doc, xref, "EF")
    return count


def remove_javascript(doc: pymupdf.Document) -> int:
    count = 0
    catalog = doc.pdf_catalog()
    count += _drop_key(doc, catalog, "Names/JavaScript")
    for xref in _xrefs(doc):
        # Additional actions run automatically (on open, page view, field focus, ...).
        count += _drop_key(doc, xref, "AA")
        for key in ("A", "OpenAction", "Next"):
            kind, value = doc.xref_get_key(xref, key)
            if kind != "null" and _is_unsafe(doc, kind, value):
                count += delete_key(doc, xref, key)
        if doc.xref_get_key(xref, "S")[1] in UNSAFE_ACTIONS:
            doc.update_object(xref, "<<>>")
    return count


def remove_thumbnails(doc: pymupdf.Document) -> int:
    return sum(_drop_key(doc, page.xref, "Thumb") for page in doc)


def remove_bookmarks(doc: pymupdf.Document) -> int:
    count = len(doc.get_toc(simple=True))
    doc.set_toc([])
    _drop_key(doc, doc.pdf_catalog(), "Outlines")
    return count


def remove_page_labels(doc: pymupdf.Document) -> int:
    return int(_drop_key(doc, doc.pdf_catalog(), "PageLabels"))


# --- orchestration --------------------------------------------------------------------------------


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def sanitize_document(doc: pymupdf.Document, options: SanitizeOptions) -> list[SanitizeAction]:
    """Apply the enabled options; one action per option says what was removed."""
    steps: list[tuple[str, Callable[[pymupdf.Document], int], Callable[[int], str]]] = []
    if options.forms == "flatten":
        steps.append(("forms", flatten_forms, lambda n: f"Flattened {_plural(n, 'form field')}"))
    elif options.forms == "reset":
        steps.append(("forms", reset_forms, lambda n: f"Reset {_plural(n, 'form field')}"))
    if options.annotations == "remove":
        steps.append(
            ("annotations", remove_annotations, lambda n: f"Removed {_plural(n, 'comment')}")
        )
    elif options.annotations == "flatten":
        steps.append(
            ("annotations", flatten_annotations, lambda n: f"Flattened {_plural(n, 'comment')}")
        )
    if options.links:
        steps.append(("links", remove_links, lambda n: f"Removed {_plural(n, 'link')}"))
    if options.attachments:
        steps.append(
            ("attachments", remove_attachments, lambda n: f"Removed {_plural(n, 'attachment')}")
        )
    if options.javascript:
        steps.append(
            (
                "javascript",
                remove_javascript,
                lambda n: f"Removed {_plural(n, 'JavaScript or automatic action')}",
            )
        )
    if options.metadata:
        steps.append(
            (
                "metadata",
                remove_metadata,
                lambda n: f"Removed {_plural(n, 'metadata entry', 'metadata entries')}",
            )
        )
    if options.thumbnails:
        steps.append(
            ("thumbnails", remove_thumbnails, lambda n: f"Removed {_plural(n, 'page thumbnail')}")
        )
    if options.bookmarks:
        steps.append(("bookmarks", remove_bookmarks, lambda n: f"Removed {_plural(n, 'bookmark')}"))
    if options.page_labels:
        steps.append(
            ("page-labels", remove_page_labels, lambda n: "Removed page labels" if n else "")
        )
    actions = []
    for code, step, describe in steps:
        count = step(doc)
        actions.append(SanitizeAction(code, count, describe(count) if count else "None found"))
    return actions


# --- verification ---------------------------------------------------------------------------------


@dataclass
class Finding:
    """Outcome of re-inspecting the output for one option: `problem` is None when it is clean."""

    code: str
    problem: str | None
    clean: str


def _objects_with(doc: pymupdf.Document, *keys: str) -> int:
    return sum(1 for xref in _xrefs(doc) if any(_has_key(doc, xref, k) for k in keys))


def _finding(code: str, problems: list[str], clean: str) -> Finding:
    return Finding(code, "; ".join(problems) if problems else None, clean)


def sanitize_findings(doc: pymupdf.Document, options: SanitizeOptions) -> list[Finding]:
    catalog = doc.pdf_catalog()
    findings: list[Finding] = []
    if options.forms != "keep":
        problems = []
        if _has_key(doc, catalog, "AcroForm/XFA"):
            problems.append("XFA form data remains")
        widgets = [w.xref for page in doc for w in page.widgets()]
        if options.forms == "flatten" and widgets:
            problems.append(f"{_plural(len(widgets), 'form field')} remain")
        if options.forms == "reset":
            filled = sum(_holds_value(doc, xref) for xref in _form_fields(doc))
            if filled:
                problems.append(f"{_plural(filled, 'form field')} still hold a value")
        findings.append(_finding("forms", problems, "No form data left"))
    if options.annotations != "keep":
        count = sum(1 for page in doc for _ in page.annots())
        problems = [f"{_plural(count, 'comment')} remain"] if count else []
        findings.append(_finding("annotations", problems, "No comments left"))
    if options.links:
        count = sum(len(page.get_links()) for page in doc)
        problems = [f"{_plural(count, 'link')} remain"] if count else []
        findings.append(_finding("links", problems, "No links left"))
    if options.attachments:
        problems = []
        if count := doc.embfile_count():
            problems.append(f"{_plural(count, 'embedded file')} remain")
        annots = sum(
            1 for page in doc for _ in page.annots(types=[pymupdf.PDF_ANNOT_FILE_ATTACHMENT])
        )
        if annots:
            problems.append(f"{_plural(annots, 'file attachment comment')} remain")
        if count := _objects_with(doc, "EF", "AF"):
            problems.append(f"{_plural(count, 'object')} still reference embedded files")
        findings.append(_finding("attachments", problems, "No attachments left"))
    if options.javascript:
        problems = []
        if _has_key(doc, catalog, "Names/JavaScript"):
            problems.append("document-level JavaScript remains")
        unsafe = sum(
            1
            for xref in _xrefs(doc)
            if doc.xref_get_key(xref, "S")[1] in UNSAFE_ACTIONS or _has_key(doc, xref, "JS")
        )
        if unsafe:
            problems.append(f"{_plural(unsafe, 'JavaScript or unsafe action')} remain")
        if count := _objects_with(doc, "AA"):
            problems.append(f"{_plural(count, 'object')} still have automatic actions")
        findings.append(_finding("javascript", problems, "No JavaScript or unsafe actions left"))
    if options.metadata:
        problems = []
        info = [k for k, v in doc.metadata.items() if v and k not in ("format", "encryption")]
        if info:
            problems.append(f"document information remains ({', '.join(info)})")
        if count := _objects_with(doc, "Metadata", "PieceInfo"):
            problems.append(f"{_plural(count, 'object')} still carry XMP or private data")
        findings.append(_finding("metadata", problems, "No metadata left"))
    if options.thumbnails:
        count = sum(_has_key(doc, page.xref, "Thumb") for page in doc)
        problems = [f"{_plural(count, 'page thumbnail')} remain"] if count else []
        findings.append(_finding("thumbnails", problems, "No page thumbnails left"))
    if options.bookmarks:
        problems = ["bookmarks remain"] if _has_key(doc, catalog, "Outlines") else []
        findings.append(_finding("bookmarks", problems, "No bookmarks left"))
    if options.page_labels:
        problems = ["page labels remain"] if _has_key(doc, catalog, "PageLabels") else []
        findings.append(_finding("page-labels", problems, "No page labels left"))
    return findings
