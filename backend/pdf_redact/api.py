"""HTTP API used by the browser UI."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from typing import Annotated, Literal
from urllib.parse import quote

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from .config import Settings
from .core import ENGINE_LOCK
from .core.annots import marked_bytes, read_redact_annots
from .core.inspect import document_notices, page_infos
from .core.pii import DETECTORS, DETECTORS_BY_ID, CustomPattern, detect, keyword_pattern
from .core.progress import report
from .core.redact import redact_bytes
from .core.report import (
    TEXT_MODES,
    FileInfo,
    TextMode,
    audit_csv,
    audit_html,
    audit_view,
    build_audit,
    marked_text,
)
from .core.search import Match, compile_query, find
from .core.text import page_text_payload
from .core.verify import verify_bytes
from .jobs import Jobs, respond
from .models import (
    ApplyRequest,
    CheckOut,
    DetectorOut,
    DetectRequest,
    DocumentOut,
    MarkedRequest,
    MarkOut,
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


def get_jobs(request: Request) -> Jobs:
    return request.app.state.jobs


StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
JobsDep = Annotated[Jobs, Depends(get_jobs)]


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
        redactions = (
            [] if locked else [MarkOut.from_engine(m) for m in read_redact_annots(document.doc)]
        )
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        size=document.size,
        sha256=document.sha256,
        needs_password=locked,
        page_count=len(pages),
        pages=pages,
        notices=notices,
        redactions=redactions,
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


def _pages(document: StoredDocument, pages: list[int] | None) -> list[int]:
    """The given pages (all pages if None) in page order; 404 if one doesn't exist."""
    with ENGINE_LOCK:
        count = document.doc.page_count
    wanted = list(range(count)) if pages is None else sorted(set(pages))
    if wanted and not (wanted[0] >= 0 and wanted[-1] < count):
        raise HTTPException(404, "Page not found")
    return wanted


def _page_texts(document: StoredDocument, wanted: list[int]) -> list[dict]:
    """Cached text payloads of pages that exist."""
    with ENGINE_LOCK:
        missing = [page for page in wanted if page not in document.text_cache]
        for done, page in enumerate(missing):
            report("Reading the text", done, len(missing))
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
    return _page_texts(document, _pages(document, [page]))[0]


@router.post("/documents/{document_id}/search", response_model=SearchOut)
def search_document(
    document_id: str, body: SearchRequest, store: StoreDep, jobs: JobsDep, request: Request
) -> SearchOut | Response:
    """Find text, a phrase or a regular expression; matches come back as mark geometry."""
    document = _unlocked(store, document_id)
    if body.mode != "regex" and not body.query.strip():
        raise HTTPException(422, "Enter something to search for")
    pattern = _compile(body.query, body.mode, body.case_sensitive)
    pages = _pages(document, body.pages)

    def work() -> SearchOut:
        texts = _page_texts(document, pages)

        def matches() -> Iterator[Match]:
            for done, text in enumerate(texts):
                report("Searching", done, len(texts))
                yield from find(text["index"], text["lines"], pattern)

        return _search_out(matches())

    return respond(request, jobs, work)


@router.get("/detectors")
def list_detectors() -> list[DetectorOut]:
    return [
        DetectorOut(
            id=d.id, label=d.label, short=d.short, description=d.description, default=d.default
        )
        for d in DETECTORS
    ]


@router.post("/documents/{document_id}/detect", response_model=SearchOut)
def detect_pii(
    document_id: str, body: DetectRequest, store: StoreDep, jobs: JobsDep, request: Request
) -> SearchOut | Response:
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
    pages = _pages(document, body.pages)

    def work() -> SearchOut:
        texts = _page_texts(document, pages)

        def matches() -> Iterator[Match]:
            for done, text in enumerate(texts):
                report("Looking for personal information", done, len(texts))
                yield from detect(text["index"], text["lines"], detectors, keywords, custom)

        return _search_out(matches())

    return respond(request, jobs, work)


@router.post("/documents/{document_id}/apply", response_model=OutputOut)
def apply_redactions(
    document_id: str, body: ApplyRequest, store: StoreDep, jobs: JobsDep, request: Request
) -> OutputOut | Response:
    document = _unlocked(store, document_id)
    return respond(request, jobs, lambda: _apply(store, document, body))


@router.delete("/jobs/{job_id}", status_code=204)
def cancel_job(job_id: str, jobs: JobsDep) -> Response:
    """Cancel a search, detection or apply that streams its progress."""
    try:
        jobs.cancel(job_id)
    except KeyError:
        raise HTTPException(404, "No such job; it may have finished already") from None
    return Response(status_code=204)


def _apply(store: Store, document: StoredDocument, body: ApplyRequest) -> OutputOut:
    marks = [m.to_engine() for m in body.marks]
    options = body.options.to_engine()
    data = document.path.read_bytes()
    with ENGINE_LOCK:
        try:
            out, stats = redact_bytes(data, marks, options, document.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        verification = verify_bytes(out, marks, options, document.password, body.search_terms)
        output_info = FileInfo(
            redacted_filename(document.filename), len(out), hashlib.sha256(out).hexdigest()
        )
        audit = build_audit(
            doc=document.doc,
            source=FileInfo(document.filename, document.size, document.sha256),
            output=output_info,
            marks=marks,
            infos={m.id: m.info() for m in body.marks},
            texts=marked_text(document.doc, marks),
            options=options,
            stats=stats,
            verification=verification,
        )

    path = store.new_path()
    path.write_bytes(out)
    output = StoredOutput(
        id=uuid.uuid4().hex,
        document_id=document.id,
        filename=output_info.filename,
        path=path,
        size=output_info.size,
        sha256=output_info.sha256,
        audit=audit,
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


def _stem(filename: str) -> str:
    return filename[:-4] if filename.lower().endswith(".pdf") else filename


def _attachment(filename: str) -> str:
    quoted = quote(filename)
    if quoted == filename:
        return f'attachment; filename="{filename}"'
    return f"attachment; filename*=utf-8''{quoted}"


REPORT_FORMATS = {
    "html": ("text/html; charset=utf-8", "redaction_report.html"),
    "json": ("application/json", "redaction_log.json"),
    "csv": ("text/csv; charset=utf-8", "redaction_log.csv"),
}


@router.post("/documents/{document_id}/marked")
def export_marked(document_id: str, body: MarkedRequest, store: StoreDep) -> Response:
    """The original with the marks as unapplied /Redact annotations, for review in other tools."""
    document = _unlocked(store, document_id)
    data = document.path.read_bytes()
    with ENGINE_LOCK:
        try:
            out = marked_bytes(data, [m.to_engine() for m in body.marks], document.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    filename = f"{_stem(document.filename)}_marked.pdf"
    return Response(
        out, media_type="application/pdf", headers={"Content-Disposition": _attachment(filename)}
    )


@router.get("/outputs/{output_id}/report")
def download_report(
    output_id: str,
    store: StoreDep,
    format: Literal["html", "json", "csv"] = "html",
    text: Annotated[TextMode, Query(description=f"One of {', '.join(TEXT_MODES)}")] = "length",
) -> Response:
    try:
        output = store.output(output_id)
    except KeyError:
        raise HTTPException(404, "Output not found") from None
    if output.audit is None:
        raise HTTPException(404, "No report for this output")
    view = audit_view(output.audit, text)
    if format == "html":
        content = audit_html(view)
    elif format == "csv":
        # A byte order mark makes spreadsheet apps read the file as UTF-8.
        content = "\ufeff" + audit_csv(view)
    else:
        content = json.dumps(view, indent=2, ensure_ascii=False)
    media_type, suffix = REPORT_FORMATS[format]
    filename = f"{_stem(output.audit['input']['filename'])}_{suffix}"
    return Response(
        content, media_type=media_type, headers={"Content-Disposition": _attachment(filename)}
    )


@router.get("/outputs/{output_id}/file")
def download_output(output_id: str, store: StoreDep) -> FileResponse:
    try:
        output = store.output(output_id)
    except KeyError:
        raise HTTPException(404, "Output not found") from None
    return FileResponse(output.path, media_type="application/pdf", filename=output.filename)
