"""Audit log (JSON, CSV) and a human-readable HTML report for one application of marks.

The audit record is built once, when the marks are applied, and holds the removed text in plain
form. Views of it withhold that text unless asked: by default only its length is shown, since even
a hash of a short value such as an account number can be reversed by trying every candidate.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html import escape
from typing import Any, Literal

import pymupdf

from .. import __version__
from .geometry import to_display, union
from .redact import Mark, RedactOptions, RedactStats, mark_regions, selected_chars
from .text import extract_lines
from .verify import Verification

TextMode = Literal["length", "hash", "plain"]
TEXT_MODES: tuple[TextMode, ...] = ("length", "hash", "plain")

STATUS_LABELS = {"pass": "Verified", "warn": "Warning", "fail": "Failed"}


@dataclass
class MarkInfo:
    """What the UI knows about a mark beyond its geometry."""

    source: str = "manual"
    category: str | None = None
    created_at: str | None = None


@dataclass
class FileInfo:
    filename: str
    size: int
    sha256: str


def marked_text(doc: pymupdf.Document, marks: list[Mark]) -> dict[str, str]:
    """The text under each mark in the original document, one line of the page per line."""
    by_page: dict[int, list[Mark]] = defaultdict(list)
    for mark in marks:
        by_page[mark.page].append(mark)
    texts: dict[str, str] = {}
    for pno, page_marks in by_page.items():
        page = doc[pno]
        lines = extract_lines(page)
        for mark in page_marks:
            regions = mark_regions(page, mark)
            chosen = {id(ch) for ch in selected_chars(lines, regions)}
            parts = ["".join(ch.c for ch in line if id(ch) in chosen) for line in lines]
            texts[mark.id] = "\n".join(p for p in parts if p.strip())
    return texts


def _hex(rgb: tuple[float, float, float] | None) -> str | None:
    if rgb is None:
        return None
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def _bbox(doc: pymupdf.Document, mark: Mark) -> list[float]:
    page = doc[mark.page]
    if mark.kind == "page":
        box = page.rect
    else:
        box = union([to_display(page, r) for r in mark_regions(page, mark)] or [pymupdf.Rect()])
    return [round(v, 2) for v in box]


def _mark_status(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    return "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"


def build_audit(
    *,
    doc: pymupdf.Document,
    source: FileInfo,
    output: FileInfo,
    marks: list[Mark],
    infos: dict[str, MarkInfo],
    texts: dict[str, str],
    options: RedactOptions,
    stats: RedactStats,
    verification: Verification,
    applied_at: datetime | None = None,
) -> dict[str, Any]:
    """The complete audit record, with the removed text in plain form; see `audit_view`."""
    applied = (applied_at or datetime.now(UTC)).isoformat(timespec="seconds").replace("+00:00", "Z")
    checks = [
        {
            "name": c.name,
            "status": c.status,
            "message": c.message,
            "page": None if c.page is None else c.page + 1,
            "markId": c.mark_id,
        }
        for c in verification.checks
    ]
    by_mark: dict[str, list[dict]] = defaultdict(list)
    for c in checks:
        if c["markId"]:
            by_mark[c["markId"]].append(c)
    as_area = set(stats.text_marks_as_area)
    skipped = set(stats.overlays_skipped)

    records = []
    for mark in sorted(marks, key=lambda m: (m.page, m.id)):
        info = infos.get(mark.id, MarkInfo())
        notes = [c["message"] for c in by_mark[mark.id] if c["status"] != "pass"]
        if mark.id in as_area:
            notes.append("No text under the text mark; redacted as an area")
        if mark.id in skipped:
            notes.append("Overlay text left out where it did not fit")
        a = mark.appearance
        records.append(
            {
                "id": mark.id,
                "page": mark.page + 1,
                "kind": mark.kind,
                "source": info.source,
                "category": info.category,
                "overlayText": a.overlay_text,
                "fill": _hex(a.fill),
                "bbox": _bbox(doc, mark),
                "rects": len(mark.rects) if mark.kind != "page" else 1,
                "status": _mark_status(by_mark[mark.id]),
                "notes": notes,
                "createdAt": info.created_at,
                "appliedAt": applied,
                "text": texts.get(mark.id, ""),
            }
        )

    per_page = Counter(m.page + 1 for m in marks)
    codes = Counter(m.appearance.overlay_text.strip() for m in marks if m.appearance.overlay_text)
    sanitize = options.sanitize
    return {
        "tool": {
            "name": "PDF Redact",
            "version": __version__,
            "engine": f"PyMuPDF {pymupdf.__version__} (MuPDF {pymupdf.mupdf_version})",
        },
        "appliedAt": applied,
        "input": {**asdict(source), "pages": doc.page_count},
        "output": asdict(output),
        "options": {
            "images": options.images,
            "graphics": options.graphics,
            "sanitize": None if sanitize is None else _camel(asdict(sanitize)),
        },
        "summary": {
            "marks": len(marks),
            "pages": [{"page": p, "marks": n} for p, n in sorted(per_page.items())],
            "kinds": dict(Counter(m.kind for m in marks)),
            "overlayTexts": [{"text": t, "marks": n} for t, n in codes.most_common()],
            "charactersRemoved": stats.glyphs_removed,
            "annotationsRemoved": stats.annotations_removed,
        },
        "sanitized": [asdict(a) for a in stats.sanitized],
        "verification": {
            "passed": verification.passed,
            "counts": verification.counts(),
            "checks": checks,
        },
        "marks": records,
    }


def _camel(values: dict[str, Any]) -> dict[str, Any]:
    def camel(key: str) -> str:
        head, *rest = key.split("_")
        return head + "".join(w.title() for w in rest)

    return {camel(k): v for k, v in values.items()}


_QUOTED = re.compile(r"“[^”]*”")


def audit_view(audit: dict[str, Any], text: TextMode = "length") -> dict[str, Any]:
    """A copy of the audit record that shows the removed text as chosen."""
    marks = []
    for record in audit["marks"]:
        record = dict(record)
        content = record.pop("text")
        record["textLength"] = len(content)
        if text == "hash":
            record["textSha256"] = hashlib.sha256(content.encode()).hexdigest() if content else None
        elif text == "plain":
            record["text"] = content
        marks.append(record)
    verification = dict(audit["verification"])
    if text != "plain":
        # Messages quote the marked search results that remain in the output.
        verification["checks"] = [
            {**c, "message": _QUOTED.sub("[text withheld]", c["message"])}
            for c in verification["checks"]
        ]
        for record in marks:
            record["notes"] = [_QUOTED.sub("[text withheld]", n) for n in record["notes"]]
    return {**audit, "textInReport": text, "verification": verification, "marks": marks}


CSV_COLUMNS = [
    "id",
    "page",
    "kind",
    "source",
    "category",
    "overlayText",
    "fill",
    "x0",
    "y0",
    "x1",
    "y1",
    "rects",
    "status",
    "notes",
    "createdAt",
    "appliedAt",
    "textLength",
    "textSha256",
    "text",
]


def _cell(value: Any) -> Any:
    # Spreadsheet apps run cells that start with these as formulas.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def audit_csv(view: dict[str, Any]) -> str:
    """One row per mark, from `audit_view`; the document-level sections are in the JSON log."""
    columns = [
        c
        for c in CSV_COLUMNS
        if c not in ("textSha256", "text") or any(c in r for r in view["marks"])
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for record in view["marks"]:
        x0, y0, x1, y1 = record["bbox"]
        row = {
            **record,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "notes": "; ".join(record["notes"]),
        }
        writer.writerow({k: _cell(v) for k, v in row.items()})
    return out.getvalue()


# --- HTML report ----------------------------------------------------------------------------------

_STYLE = """
body { font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1f2937;
       max-width: 1000px; margin: 32px auto; padding: 0 24px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 28px 0 8px; padding-bottom: 4px;
     border-bottom: 1px solid #e5e7eb; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; vertical-align: top; padding: 4px 8px;
         border-bottom: 1px solid #e5e7eb; }
th { background: #f9fafb; font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
code, .hash { font: 12px ui-monospace, Menlo, monospace; word-break: break-all; }
code.pos { white-space: nowrap; word-break: normal; }
table.compact { width: auto; min-width: 280px; }
.muted { color: #6b7280; }
.verdict { padding: 10px 14px; border-radius: 8px; font-weight: 600; margin: 16px 0; }
.verdict.pass { background: #f0fdf4; color: #166534; }
.verdict.warn { background: #fffbeb; color: #92400e; }
.verdict.fail { background: #fef2f2; color: #b91c1c; }
.status { font-weight: 600; white-space: nowrap; }
.status.pass { color: #166534; } .status.warn { color: #92400e; } .status.fail { color: #b91c1c; }
.notice { background: #fef2f2; color: #b91c1c; padding: 8px 12px; border-radius: 6px; }
pre { margin: 0; white-space: pre-wrap; font: inherit; }
@media print {
  body { margin: 0; max-width: none; }
  h2 { break-after: avoid; }
  tr { break-inside: avoid; }
}
"""

_KINDS = {"text": "Text", "area": "Area", "page": "Page"}
_SANITIZE = {
    "layers": "Hidden layers",
    "forms": "Form fields",
    "annotations": "Comments and markup",
    "outside-crop": "Content outside the visible page area",
    "hidden-text": "Hidden text",
    "links": "Links",
    "attachments": "Attached files",
    "javascript": "JavaScript and automatic actions",
    "metadata": "Document properties and metadata",
    "thumbnails": "Page thumbnails",
    "bookmarks": "Bookmarks",
    "page-labels": "Page labels",
}
_SOURCES = {"manual": "Manual", "search": "Search", "detect": "Detected"}
_IMAGES = {
    "pixels": "Covered pixels blanked",
    "remove": "Images touched by a mark removed",
    "none": "Left unchanged",
}
_GRAPHICS = {
    "covered": "Shapes inside marks removed",
    "touched": "Shapes touched by a mark removed",
    "none": "Left unchanged",
}
_TEXT_MODES = {
    "length": "Only the length of the removed text is shown.",
    "hash": "The removed text is shown as a SHA-256 hash. Short values can be recovered from "
    "their hash by trying every candidate.",
    "plain": "This report contains the removed text in plain form. Keep it as confidential as the "
    "original document.",
}


def _e(value: Any) -> str:
    return escape("" if value is None else str(value))


def _rows(
    rows: list[list[str]],
    head: list[str],
    numeric: frozenset[int] = frozenset(),
    compact: bool = False,
) -> str:
    def cells(tag: str, values: list[str]) -> str:
        return "".join(
            f"<{tag}{' class=num' if i in numeric else ''}>{v}</{tag}>"
            for i, v in enumerate(values)
        )

    body = "".join(f"<tr>{cells('td', r)}</tr>" for r in rows)
    table = "<table class=compact>" if compact else "<table>"
    return f"{table}<thead><tr>{cells('th', head)}</tr></thead><tbody>{body}</tbody></table>"


def _size(n: int) -> str:
    return f"{n:,} bytes"


def _mark_text(record: dict[str, Any]) -> str:
    if "text" in record:
        return (
            f"<pre>{_e(record['text'])}</pre>" if record["text"] else "<span class=muted>—</span>"
        )
    length = f"{record['textLength']:,} characters"
    if record.get("textSha256"):
        return f"{length}<br><span class=hash>{_e(record['textSha256'])}</span>"
    return length


def audit_html(view: dict[str, Any]) -> str:
    """A self-contained, printable summary from `audit_view`."""
    v = view["verification"]
    counts = v["counts"]
    s = view["summary"]
    issues = [c for c in v["checks"] if c["status"] != "pass"]
    if not v["passed"]:
        verdict = ("fail", f"Verification failed: {counts['fail']} check(s) found problems.")
    elif issues:
        verdict = ("warn", f"Verified with {len(issues)} warning(s) to review.")
    else:
        verdict = ("pass", "Verified: the marked content is no longer in the file.")
    if not s["marks"]:
        verdict = (
            verdict[0],
            verdict[1].replace("the marked content", "the hidden information"),
        )

    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Redaction report — {_e(view['input']['filename'])}</title>",
        f"<style>{_STYLE}</style></head><body>",
        "<h1>Redaction report</h1>",
        f"<div class=muted>{_e(view['input']['filename'])} · applied {_e(view['appliedAt'])}</div>",
        f"<div class='verdict {verdict[0]}'>{_e(verdict[1])}</div>",
    ]
    if view["textInReport"] == "plain":
        parts.append(f"<p class=notice>{_e(_TEXT_MODES['plain'])}</p>")

    i, o = view["input"], view["output"]
    parts += [
        "<h2>Files</h2>",
        _rows(
            [
                [
                    "Original",
                    _e(i["filename"]),
                    _size(i["size"]),
                    f"<span class=hash>{i['sha256']}</span>",
                ],
                [
                    "Redacted",
                    _e(o["filename"]),
                    _size(o["size"]),
                    f"<span class=hash>{o['sha256']}</span>",
                ],
            ],
            ["", "File", "Size", "SHA-256"],
        ),
        f"<p class=muted>{_e(view['tool']['name'])} {_e(view['tool']['version'])} · "
        f"{_e(view['tool']['engine'])}</p>",
    ]

    kinds = ", ".join(f"{n} {_KINDS[k].lower()}" for k, n in s["kinds"].items())
    summary = f"{s['marks']} mark(s) on {len(s['pages'])} of {i['pages']} page(s)"
    if kinds:
        summary += f" ({kinds})"
    summary += f". {s['charactersRemoved']:,} character(s) removed."
    if s["annotationsRemoved"]:
        summary += (
            f" {s['annotationsRemoved']} comment(s), field(s) or link(s) under marks removed."
        )
    parts += ["<h2>Summary</h2>", f"<p>{summary}</p>"]
    if s["pages"]:
        parts.append(
            _rows(
                [[str(p["page"]), str(p["marks"])] for p in s["pages"]],
                ["Page", "Marks"],
                frozenset({1}),
                compact=True,
            )
        )
    if s["overlayTexts"]:
        parts += [
            "<h2>Codes and overlay text</h2>",
            _rows(
                [[_e(t["text"]), str(t["marks"])] for t in s["overlayTexts"]],
                ["Overlay text", "Marks"],
                frozenset({1}),
                compact=True,
            ),
        ]

    opts = view["options"]
    parts += ["<h2>Options</h2>"]
    option_rows = []
    if s["marks"]:
        option_rows += [
            ["Images under marks", _e(_IMAGES[opts["images"]])],
            ["Vector graphics under marks", _e(_GRAPHICS[opts["graphics"]])],
        ]
    if opts["sanitize"] is None:
        option_rows.append(["Hidden information", "Not removed"])
    option_rows.append(["Removed text in this report", _e(_TEXT_MODES[view["textInReport"]])])
    parts.append(_rows(option_rows, ["Option", "Setting"]))

    if view["sanitized"]:
        parts += [
            "<h2>Hidden information</h2>",
            _rows(
                [
                    [
                        _e(_SANITIZE.get(a["code"], a["code"])),
                        _e(a["message"]) if a["count"] else "<span class=muted>None found</span>",
                    ]
                    for a in view["sanitized"]
                ],
                ["Item", "Result"],
            ),
        ]

    parts += [
        "<h2>Verification</h2>",
        f"<p>{counts['pass']} passed, {counts['warn']} warning(s), {counts['fail']} failed.</p>",
    ]
    if issues:
        parts.append(
            _rows(
                [
                    [
                        f"<span class='status {c['status']}'>{STATUS_LABELS[c['status']]}</span>",
                        _e(c["page"] or ""),
                        _e(c["markId"] or ""),
                        _e(c["message"]),
                    ]
                    for c in issues
                ],
                ["Status", "Page", "Mark", "Problem"],
            )
        )

    if view["marks"]:
        parts += [
            "<h2>Marks</h2>",
            "<p class=muted>Positions are in PDF points from the top-left corner of the page "
            "as displayed.</p>",
            _rows(
                [
                    [
                        str(r["page"]),
                        _e(_KINDS[r["kind"]]),
                        _e(_SOURCES.get(r["source"], r["source"]))
                        + (
                            f"<br><span class=muted>{_e(r['category'])}</span>"
                            if r["category"]
                            else ""
                        ),
                        _e(r["overlayText"]),
                        "<code class=pos>" + ", ".join(f"{x:g}" for x in r["bbox"]) + "</code>",
                        _mark_text(r),
                        f"<span class='status {r['status']}'>{STATUS_LABELS[r['status']]}</span>"
                        + "".join(f"<br><span class=muted>{_e(n)}</span>" for n in r["notes"]),
                    ]
                    for r in view["marks"]
                ],
                ["Page", "Kind", "Source", "Overlay text", "Position", "Removed text", "Status"],
            ),
        ]
    parts.append("</body></html>")
    return "\n".join(parts)
