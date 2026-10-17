from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime

import pymupdf

from pdf_redact.core.redact import Appearance, Mark, RedactOptions, redact_bytes
from pdf_redact.core.report import (
    FileInfo,
    MarkInfo,
    audit_csv,
    audit_html,
    audit_view,
    build_audit,
    marked_text,
)
from pdf_redact.core.sanitize import SanitizeOptions
from pdf_redact.core.verify import verify_bytes
from tests import corpus
from tests.corpus import ABOVE, BELOW, SECRET, SECRET_LINE
from tests.helpers import display_hits, text_mark


def _audit(data: bytes, marks: list[Mark], search_terms=(), options=None, infos=None) -> dict:
    options = options or RedactOptions()
    out, stats = redact_bytes(data, marks, options)
    verification = verify_bytes(out, marks, options, None, search_terms)
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return build_audit(
            doc=doc,
            source=FileInfo("case.pdf", len(data), hashlib.sha256(data).hexdigest()),
            output=FileInfo("case_redacted.pdf", len(out), hashlib.sha256(out).hexdigest()),
            marks=marks,
            infos=infos or {},
            texts=marked_text(doc, marks),
            options=options,
            stats=stats,
            verification=verification,
            applied_at=datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC),
        )


def test_marked_text_per_kind() -> None:
    data = corpus.text_basic()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        page = doc[0]
        lines = [page.search_for(t)[0] for t in (ABOVE, BELOW)]
        marks = [
            text_mark(display_hits(data, SECRET), mark_id="t"),
            Mark("a", 0, "area", [(0, lines[0].y0, page.rect.width, lines[1].y1)]),
            Mark("p", 0, "page", []),
        ]
        texts = marked_text(doc, marks)
    assert texts["t"] == SECRET
    assert texts["a"].split("\n") == [ABOVE, SECRET_LINE, BELOW]
    assert texts["p"].endswith(texts["a"]) and len(texts["p"]) > len(texts["a"])


def test_audit_record() -> None:
    data = corpus.text_basic()
    marks = [
        text_mark(display_hits(data, SECRET), mark_id="t"),
        Mark("empty", 0, "text", [(400, 700, 420, 710)], Appearance(overlay_text="(b)(6)")),
    ]
    infos = {"t": MarkInfo("detect", "SSN", "2024-05-06T07:00:00Z")}
    audit = _audit(data, marks, infos=infos)

    assert audit["tool"]["name"] == "PDF Redact"
    assert audit["appliedAt"] == "2024-05-06T07:08:09Z"
    assert audit["input"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert audit["input"]["pages"] == 1
    assert audit["options"]["sanitize"] is None
    assert audit["summary"]["pages"] == [{"page": 1, "marks": 2}]
    assert audit["summary"]["overlayTexts"] == [{"text": "(b)(6)", "marks": 1}]
    assert audit["summary"]["charactersRemoved"] == len(SECRET)
    assert audit["verification"]["passed"] is True

    empty, t = audit["marks"]
    assert (t["id"], t["page"], t["source"], t["category"]) == ("t", 1, "detect", "SSN")
    assert t["createdAt"] == "2024-05-06T07:00:00Z"
    assert t["status"] == "pass" and t["notes"] == []
    assert t["text"] == SECRET
    assert t["fill"] == "#000000"
    assert empty["source"] == "manual" and empty["text"] == ""
    assert empty["notes"] == ["No text under the text mark; redacted as an area"]
    assert empty["bbox"] == [400, 700, 420, 710]


def test_views_withhold_text_unless_asked() -> None:
    data = corpus.personal_info()
    # Mark only the first of two occurrences, so a warning quotes the text.
    marks = [text_mark(display_hits(data, SECRET), mark_id="t")]
    audit = _audit(data, marks, search_terms=[SECRET])
    assert any(SECRET in c["message"] for c in audit["verification"]["checks"])

    length = audit_view(audit)
    assert length["textInReport"] == "length"
    assert length["marks"][0]["textLength"] == len(SECRET)
    assert "text" not in length["marks"][0] and "textSha256" not in length["marks"][0]
    for render in (audit_html, audit_csv, lambda v: repr(v)):
        assert SECRET not in render(length)
    assert "[text withheld]" in repr(length["verification"])

    hashed = audit_view(audit, "hash")
    assert hashed["marks"][0]["textSha256"] == hashlib.sha256(SECRET.encode()).hexdigest()
    assert SECRET not in audit_html(hashed)

    plain = audit_view(audit, "plain")
    assert plain["marks"][0]["text"] == SECRET
    html = audit_html(plain)
    assert SECRET in html and "plain form" in html
    # The stored record itself is unchanged.
    assert audit["marks"][0]["text"] == SECRET and "textLength" not in audit["marks"][0]


def test_csv_has_one_row_per_mark_and_defuses_formulas() -> None:
    data = corpus.text_basic()
    marks = [
        text_mark(display_hits(data, SECRET), mark_id="t", overlay="=HYPERLINK(1)"),
        Mark("p", 0, "page", []),
    ]
    rows = list(csv.DictReader(io.StringIO(audit_csv(audit_view(_audit(data, marks), "hash")))))
    assert [r["id"] for r in rows] == ["p", "t"]
    assert rows[1]["overlayText"] == "'=HYPERLINK(1)"
    assert rows[1]["textSha256"] == hashlib.sha256(SECRET.encode()).hexdigest()
    assert "text" not in rows[0]
    assert rows[0]["kind"] == "page" and rows[0]["page"] == "1"
    assert [float(rows[0][k]) for k in ("x0", "y0", "x1", "y1")] == [0, 0, 595, 842]


def test_html_report_escapes_content_and_lists_sections() -> None:
    data = corpus.metadata()
    marks = [text_mark(display_hits(data, SECRET), mark_id="t", overlay="<b>(b)(6)</b>")]
    audit = _audit(data, marks, options=RedactOptions(sanitize=SanitizeOptions()))
    html = audit_html(audit_view(audit))
    assert "&lt;b&gt;(b)(6)&lt;/b&gt;" in html and "<b>(b)(6)" not in html
    assert "Verified: the marked content is no longer in the file." in html
    assert "Hidden information" in html and "metadata entries" in html
    assert audit["input"]["sha256"] in html and audit["output"]["sha256"] in html


def test_html_report_for_sanitizing_only() -> None:
    data = corpus.metadata()
    audit = _audit(data, [], options=RedactOptions(sanitize=SanitizeOptions()))
    html = audit_html(audit_view(audit))
    assert "Verified: the hidden information is no longer in the file." in html
    assert "<h2>Marks</h2>" not in html and "Images under marks" not in html
