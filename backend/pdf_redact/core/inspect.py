"""Document-level facts the user should know before redacting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pymupdf


@dataclass
class Notice:
    code: str
    level: Literal["info", "warning"]
    message: str


@dataclass
class PageInfo:
    index: int
    width: float  # display space (rotation applied), points
    height: float
    rotation: int


def page_infos(doc: pymupdf.Document) -> list[PageInfo]:
    infos = []
    for page in doc:
        rect = page.rect
        infos.append(
            PageInfo(page.number, round(rect.width, 2), round(rect.height, 2), page.rotation)
        )
    return infos


def _catalog_key(doc: pymupdf.Document, key: str) -> str | None:
    kind, value = doc.xref_get_key(doc.pdf_catalog(), key)
    return None if kind == "null" else value


def _has_javascript(doc: pymupdf.Document) -> bool:
    if _catalog_key(doc, "Names/JavaScript"):
        return True
    open_action = _catalog_key(doc, "OpenAction")
    if open_action is None:
        return False
    if "/JavaScript" in open_action:
        return True
    if open_action.endswith(" R"):
        xref = int(open_action.split()[0])
        return doc.xref_get_key(xref, "S") == ("name", "/JavaScript")
    return False


def existing_redact_annots(doc: pymupdf.Document) -> int:
    return sum(1 for page in doc for _ in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]))


def document_notices(doc: pymupdf.Document) -> list[Notice]:
    """Notices for an opened (and, if needed, authenticated) document."""
    # `doc.needs_pass` must not be used here: MuPDF answers it by authenticating with an empty
    # password, which replaces the key of an already unlocked document and breaks decryption.
    notices: list[Notice] = []
    if doc.is_encrypted or doc.metadata.get("encryption"):
        notices.append(
            Notice(
                "encrypted",
                "info",
                "The document is encrypted. The redacted copy keeps the same encryption and "
                "passwords.",
            )
        )
    if doc.is_encrypted:
        return notices
    if doc.is_repaired:
        notices.append(
            Notice(
                "repaired",
                "warning",
                "The file is damaged and was repaired while opening. Check the redacted copy "
                "carefully.",
            )
        )
    if doc.get_sigflags() > 0:
        notices.append(
            Notice(
                "signed",
                "warning",
                "The document is digitally signed. Redacting it invalidates the signatures.",
            )
        )
    if _catalog_key(doc, "AcroForm/XFA"):
        notices.append(
            Notice(
                "xfa",
                "warning",
                "The document contains an XFA form, whose data is stored outside the pages and "
                "is not affected by redaction marks.",
            )
        )
    if doc.is_form_pdf:
        notices.append(
            Notice(
                "forms",
                "info",
                "The document has interactive form fields. Field values are stored separately "
                "from page content; review them before sharing.",
            )
        )
    if count := doc.embfile_count():
        notices.append(
            Notice(
                "attachments",
                "warning",
                f"The document has {count} embedded file(s), which redaction marks do not affect.",
            )
        )
    if _has_javascript(doc):
        notices.append(Notice("javascript", "warning", "The document contains JavaScript."))
    if count := existing_redact_annots(doc):
        notices.append(
            Notice(
                "existing-redactions",
                "warning",
                f"The document has {count} unapplied redaction mark(s) from another tool. They "
                "are not applied and are dropped from the redacted copy; mark those areas again "
                "to redact them.",
            )
        )
    return notices
