"""HTTP API used by the browser UI."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict
from typing import Annotated

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from .config import Settings
from .core import ENGINE_LOCK
from .core.inspect import document_notices, page_infos
from .core.redact import redact_bytes
from .core.text import page_text_payload
from .core.verify import verify_bytes
from .models import (
    ApplyRequest,
    CheckOut,
    DocumentOut,
    NoticeOut,
    OutputOut,
    PageOut,
    StatsOut,
    UnlockRequest,
    VerificationOut,
)
from .store import Store, StoredDocument, StoredOutput

router = APIRouter(prefix="/api")

# The PDF header may be preceded by junk; readers accept it within the first 1 KiB.
HEADER_WINDOW = 1024


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _document(store: Store, document_id: str) -> StoredDocument:
    try:
        return store.document(document_id)
    except KeyError:
        raise HTTPException(404, "Document not found") from None


def _unlocked(store: Store, document_id: str) -> StoredDocument:
    document = _document(store, document_id)
    if document.locked:
        raise HTTPException(423, "Document is locked; unlock it with its password first")
    return document


def clean_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:200] or "document.pdf"


def redacted_filename(name: str) -> str:
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    return f"{stem}_redacted.pdf"


def _document_out(document: StoredDocument) -> DocumentOut:
    with ENGINE_LOCK:
        locked = document.locked
        pages = [] if locked else [PageOut(**asdict(p)) for p in page_infos(document.doc)]
        notices = [NoticeOut(**asdict(n)) for n in document_notices(document.doc)]
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        size=document.size,
        sha256=document.sha256,
        needs_password=locked,
        page_count=len(pages),
        pages=pages,
        notices=notices,
    )


def _open(path) -> pymupdf.Document:
    with ENGINE_LOCK:
        try:
            doc = pymupdf.open(path, filetype="pdf")
        except Exception:
            raise HTTPException(422, "The file could not be read as a PDF") from None
        if not doc.is_pdf or doc.page_count == 0:
            doc.close()
            raise HTTPException(422, "The file is not a PDF with at least one page")
        return doc


@router.post("/documents", status_code=201)
async def upload_document(
    request: Request,
    store: StoreDep,
    settings: SettingsDep,
    filename: Annotated[str, Query(max_length=1000)] = "document.pdf",
) -> DocumentOut:
    """Upload a PDF as the raw request body (Content-Type: application/pdf)."""
    limit = settings.max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"File is larger than the {limit // (1024 * 1024)} MiB limit")

    path = store.new_path()
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with path.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        413, f"File is larger than the {limit // (1024 * 1024)} MiB limit"
                    )
                if len(head) < HEADER_WINDOW:
                    head += chunk[: HEADER_WINDOW - len(head)]
                digest.update(chunk)
                f.write(chunk)
        if b"%PDF-" not in head:
            raise HTTPException(415, "The file is not a PDF")
        doc = await run_in_threadpool(_open, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise

    document = StoredDocument(
        id=uuid.uuid4().hex,
        filename=clean_filename(filename),
        path=path,
        size=size,
        sha256=digest.hexdigest(),
        doc=doc,
    )
    store.add_document(document)
    return await run_in_threadpool(_document_out, document)


@router.get("/documents/{document_id}")
def get_document(document_id: str, store: StoreDep) -> DocumentOut:
    return _document_out(_document(store, document_id))


@router.post("/documents/{document_id}/unlock")
def unlock_document(document_id: str, body: UnlockRequest, store: StoreDep) -> DocumentOut:
    document = _document(store, document_id)
    with ENGINE_LOCK:
        if document.locked:
            if not document.doc.authenticate(body.password):
                raise HTTPException(403, "Incorrect password")
            document.password = body.password
    return _document_out(document)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, store: StoreDep) -> Response:
    try:
        store.remove_document(document_id)
    except KeyError:
        raise HTTPException(404, "Document not found") from None
    return Response(status_code=204)


@router.get("/documents/{document_id}/pages/{page}/text")
def page_text(document_id: str, page: int, store: StoreDep) -> dict:
    document = _unlocked(store, document_id)
    with ENGINE_LOCK:
        if not 0 <= page < document.doc.page_count:
            raise HTTPException(404, "Page not found")
        if page not in document.text_cache:
            document.text_cache[page] = page_text_payload(document.doc[page])
        return document.text_cache[page]


@router.post("/documents/{document_id}/apply")
def apply_redactions(document_id: str, body: ApplyRequest, store: StoreDep) -> OutputOut:
    document = _unlocked(store, document_id)
    marks = [m.to_engine() for m in body.marks]
    options = body.options.to_engine()
    data = document.path.read_bytes()
    with ENGINE_LOCK:
        try:
            out, stats = redact_bytes(data, marks, options, document.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        verification = verify_bytes(out, marks, options, document.password)

    path = store.new_path()
    path.write_bytes(out)
    output = StoredOutput(
        id=uuid.uuid4().hex,
        document_id=document.id,
        filename=redacted_filename(document.filename),
        path=path,
        size=len(out),
        sha256=hashlib.sha256(out).hexdigest(),
    )
    store.add_output(output)
    return OutputOut(
        id=output.id,
        document_id=document.id,
        filename=output.filename,
        size=output.size,
        sha256=output.sha256,
        stats=StatsOut(**asdict(stats)),
        verification=VerificationOut(
            passed=verification.passed,
            counts=verification.counts(),
            checks=[CheckOut(**asdict(c)) for c in verification.checks],
        ),
    )


@router.get("/outputs/{output_id}/file")
def download_output(output_id: str, store: StoreDep) -> FileResponse:
    try:
        output = store.output(output_id)
    except KeyError:
        raise HTTPException(404, "Output not found") from None
    return FileResponse(output.path, media_type="application/pdf", filename=output.filename)
