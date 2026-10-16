"""HTTP API used by the browser UI."""

from __future__ import annotations

import hashlib
import itertools
import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from typing import Annotated

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from .config import Settings
from .core import ENGINE_LOCK
from .core.inspect import document_notices, page_infos
from .core.pii import DETECTORS, DETECTORS_BY_ID, CustomPattern, detect, keyword_pattern
from .core.redact import redact_bytes
from .core.search import Match, compile_query, find
from .core.text import page_text_payload
from .core.verify import verify_bytes
from .models import (
    ApplyRequest,
    CheckOut,
    DetectorOut,
    DetectRequest,
    DocumentOut,
    MatchOut,
    NoticeOut,
    OutputOut,
    PageOut,
    SearchOut,
    SearchRequest,
    StatsOut,
    UnlockRequest,
    VerificationOut,
)
from .store import Store, StoredDocument, StoredOutput

router = APIRouter(prefix="/api")

# The PDF header may be preceded by junk; readers accept it within the first 1 KiB.
HEADER_WINDOW = 1024
# Search and detection stop after this many hits.
MAX_MATCHES = 5000


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


def _page_texts(document: StoredDocument, pages: list[int] | None) -> list[dict]:
    """Cached text payloads of the given pages (all pages if None), in page order."""
    with ENGINE_LOCK:
        count = document.doc.page_count
        wanted = range(count) if pages is None else sorted(set(pages))
        if wanted and not 0 <= wanted[-1] < count:
            raise HTTPException(404, "Page not found")
        for page in wanted:
            if page not in document.text_cache:
                document.text_cache[page] = page_text_payload(document.doc[page])
        return [document.text_cache[page] for page in wanted]


def _search_out(matches: Iterable[Match]) -> SearchOut:
    hits = list(itertools.islice(matches, MAX_MATCHES + 1))
    return SearchOut(
        matches=[
            MatchOut(
                page=m.page,
                rects=m.rects,
                text=m.text,
                angle=m.angle,
                before=m.before,
                after=m.after,
                category=m.category,
            )
            for m in hits[:MAX_MATCHES]
        ],
        truncated=len(hits) > MAX_MATCHES,
    )


def _compile(pattern: str, mode: str, case_sensitive: bool, name: str | None = None):
    try:
        return compile_query(pattern, mode, case_sensitive)
    except re.error as exc:
        where = f" “{name}”" if name else ""
        raise HTTPException(422, f"Invalid regular expression{where}: {exc}") from None


@router.get("/documents/{document_id}/pages/{page}/text")
def page_text(document_id: str, page: int, store: StoreDep) -> dict:
    document = _unlocked(store, document_id)
    if page < 0:
        raise HTTPException(404, "Page not found")
    return _page_texts(document, [page])[0]


@router.post("/documents/{document_id}/search")
def search_document(document_id: str, body: SearchRequest, store: StoreDep) -> SearchOut:
    """Find text, a phrase or a regular expression; matches come back as mark geometry."""
    document = _unlocked(store, document_id)
    if body.mode != "regex" and not body.query.strip():
        raise HTTPException(422, "Enter something to search for")
    pattern = _compile(body.query, body.mode, body.case_sensitive)
    texts = _page_texts(document, body.pages)

    def matches() -> Iterator[Match]:
        for text in texts:
            yield from find(text["index"], text["lines"], pattern)

    return _search_out(matches())


@router.get("/detectors")
def list_detectors() -> list[DetectorOut]:
    return [
        DetectorOut(
            id=d.id, label=d.label, short=d.short, description=d.description, default=d.default
        )
        for d in DETECTORS
    ]


@router.post("/documents/{document_id}/detect")
def detect_pii(document_id: str, body: DetectRequest, store: StoreDep) -> SearchOut:
    """Find personal information, keywords and custom patterns."""
    document = _unlocked(store, document_id)
    unknown = [c for c in body.categories if c not in DETECTORS_BY_ID]
    if unknown:
        raise HTTPException(422, f"Unknown detector: {', '.join(unknown)}")
    detectors = [d for d in DETECTORS if d.id in body.categories]
    keywords = keyword_pattern(body.keywords)
    custom = [
        CustomPattern(p.name, _compile(p.pattern, "regex", True, p.name)) for p in body.patterns
    ]
    texts = _page_texts(document, body.pages)

    def matches() -> Iterator[Match]:
        for text in texts:
            yield from detect(text["index"], text["lines"], detectors, keywords, custom)

    return _search_out(matches())


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
