from __future__ import annotations

import hashlib

import pymupdf
import pytest

from pdf_redact.api import clean_filename, redacted_filename
from tests import corpus
from tests.corpus import ABOVE, OWNER_PASSWORD, SECRET, USER_PASSWORD
from tests.helpers import display_hits, mupdf_text, pypdf_text, raw_contains


def upload(client, data: bytes, filename: str = "case file.pdf"):
    return client.post(
        "/api/documents",
        params={"filename": filename},
        content=data,
        headers={"Content-Type": "application/pdf"},
    )


def _mark(rects, kind: str = "text", **appearance) -> dict:
    return {"id": "m1", "page": 0, "kind": kind, "rects": rects, "appearance": appearance}


def test_upload_returns_document_info(client) -> None:
    data = corpus.rotated(90)
    res = upload(client, data)
    assert res.status_code == 201, res.text
    info = res.json()
    assert info["filename"] == "case file.pdf"
    assert info["size"] == len(data)
    assert info["sha256"] == hashlib.sha256(data).hexdigest()
    assert info["needsPassword"] is False
    assert info["pageCount"] == 1
    page = info["pages"][0]
    assert page["rotation"] == 90
    assert page["width"] > page["height"]  # display orientation
    assert info["notices"] == []


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("form_fields", "forms"),
        ("attachments", "attachments"),
        ("javascript", "javascript"),
        ("existing_redaction", "existing-redactions"),
    ],
)
def test_upload_notices(client, fixture: str, code: str) -> None:
    info = upload(client, corpus.FIXTURES[fixture]()).json()
    assert code in [n["code"] for n in info["notices"]]


def test_rejects_non_pdf(client) -> None:
    assert upload(client, b"hello world").status_code == 415
    assert upload(client, b"%PDF-1.7\n garbage").status_code == 422


def test_rejects_oversized_upload(client, settings) -> None:
    settings.max_upload_bytes = 1000
    res = upload(client, corpus.text_basic())
    assert res.status_code == 413
    assert not list(client.app.state.store.root.iterdir())


def test_page_text_is_in_display_space(client) -> None:
    data = corpus.rotated(90)
    doc_id = upload(client, data).json()["id"]
    res = client.get(f"/api/documents/{doc_id}/pages/0/text")
    assert res.status_code == 200
    payload = res.json()
    assert payload["hasText"] is True
    line = next(ln for ln in payload["lines"] if SECRET in "".join(ln["chars"]))
    start = "".join(line["chars"]).index(SECRET)
    boxes = [pymupdf.Rect(b) for b in line["boxes"][start : start + len(SECRET)]]
    tight = boxes[0]
    for b in boxes[1:]:
        tight |= b
    # Compare with an independent full-height hit, rotated into the UI's (PDF.js) space.
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        page = doc[0]
        full = page.search_for(SECRET)[0] * page.rotation_matrix
    assert abs(tight.y0 - full.y0) < 1 and abs(tight.y1 - full.y1) < 1  # along the text
    assert full.x0 - 0.5 <= tight.x0 < tight.x1 <= full.x1 + 0.5  # across: tighter
    assert line["dir"] == [0, 1]  # rot 90: text runs down the screen
    assert client.get(f"/api/documents/{doc_id}/pages/5/text").status_code == 404


def test_apply_and_download(client) -> None:
    data = corpus.text_basic()
    doc_id = upload(client, data).json()["id"]
    marks = [_mark(display_hits(data, SECRET), overlayText="(b)(6)", fill="#202020")]
    res = client.post(f"/api/documents/{doc_id}/apply", json={"marks": marks})
    assert res.status_code == 200, res.text
    output = res.json()
    assert output["filename"] == "case file_redacted.pdf"
    assert output["verification"]["passed"] is True
    assert output["stats"]["glyphsRemoved"] == len(SECRET)

    file = client.get(f"/api/outputs/{output['id']}/file")
    assert file.status_code == 200
    assert file.headers["content-type"] == "application/pdf"
    assert "attachment" in file.headers["content-disposition"]
    out = file.content
    assert hashlib.sha256(out).hexdigest() == output["sha256"]
    assert SECRET not in mupdf_text(out) and SECRET not in pypdf_text(out)
    assert not raw_contains(out, SECRET)
    assert ABOVE in mupdf_text(out)


def test_apply_sanitizes_by_default(client) -> None:
    data = corpus.metadata()
    doc_id = upload(client, data).json()["id"]
    marks = [_mark(display_hits(data, SECRET))]
    output = client.post(f"/api/documents/{doc_id}/apply", json={"marks": marks}).json()
    sanitized = {a["code"]: a for a in output["stats"]["sanitized"]}
    assert sanitized["metadata"]["count"] >= 4
    assert "bookmarks" not in sanitized and "page-labels" not in sanitized  # off by default
    checks = {c["name"] for c in output["verification"]["checks"]}
    assert {"sanitize-metadata", "sanitize-hidden-text", "sanitize-layers"} <= checks
    assert output["verification"]["passed"] is True
    out = client.get(f"/api/outputs/{output['id']}/file").content
    assert not raw_contains(out, SECRET)


def test_apply_sanitize_options(client) -> None:
    data = corpus.metadata()
    doc_id = upload(client, data).json()["id"]
    url = f"/api/documents/{doc_id}/apply"
    options = {"sanitize": {"metadata": False, "pageLabels": True, "keepOcrText": False}}
    output = client.post(url, json={"marks": [], "options": options}).json()
    codes = [a["code"] for a in output["stats"]["sanitized"]]
    assert "metadata" not in codes and "page-labels" in codes
    out = client.get(f"/api/outputs/{output['id']}/file").content
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert doc.metadata["author"] == SECRET

    # null turns sanitization off: only the marks are applied.
    output = client.post(url, json={"marks": [], "options": {"sanitize": None}}).json()
    assert output["stats"]["sanitized"] == []
    assert not any(c["name"].startswith("sanitize-") for c in output["verification"]["checks"])

    bad = {"sanitize": {"forms": "shred"}}
    assert client.post(url, json={"marks": [], "options": bad}).status_code == 422


def test_apply_validation(client) -> None:
    doc_id = upload(client, corpus.text_basic()).json()["id"]
    url = f"/api/documents/{doc_id}/apply"
    bad = [
        [_mark([])],  # text mark without rects
        [_mark([[0, 0, 10, 10]], kind="bogus")],
        [_mark([[0, 0, 10, 10]], fill="black")],
        [{**_mark([[0, 0, 10, 10]]), "page": 3}],  # page out of range
    ]
    for marks in bad:
        assert client.post(url, json={"marks": marks}).status_code == 422, marks
    # Reversed coordinates are normalised; page marks need no rects.
    ok = [_mark([[100, 100, 50, 50]], kind="area"), {**_mark([], kind="page"), "id": "p"}]
    assert client.post(url, json={"marks": ok}).status_code == 200


def test_apply_checks_search_terms(client) -> None:
    data = corpus.personal_info()
    doc_id = upload(client, data).json()["id"]
    hits = client.post(f"/api/documents/{doc_id}/search", json={"query": SECRET}).json()
    first = hits["matches"][0]
    marks = [{**_mark(first["rects"]), "page": first["page"]}]
    url = f"/api/documents/{doc_id}/apply"
    res = client.post(url, json={"marks": marks, "searchTerms": [first["text"]]})
    assert res.status_code == 200, res.text
    verification = res.json()["verification"]
    assert verification["passed"] is True
    [check] = [c for c in verification["checks"] if c["name"] == "residual-text"]
    assert check["status"] == "warn" and check["page"] == 1

    too_long = {"marks": marks, "searchTerms": ["x" * 1001]}
    assert client.post(url, json=too_long).status_code == 422


@pytest.mark.parametrize("password", [USER_PASSWORD, OWNER_PASSWORD])
def test_encrypted_document_flow(client, password: str) -> None:
    data = corpus.encrypted()
    info = upload(client, data).json()
    assert info["needsPassword"] is True and info["pages"] == []
    assert "encrypted" in [n["code"] for n in info["notices"]]
    doc_id = info["id"]
    assert client.get(f"/api/documents/{doc_id}/pages/0/text").status_code == 423

    assert (
        client.post(f"/api/documents/{doc_id}/unlock", json={"password": "nope"}).status_code == 403
    )
    info = client.post(f"/api/documents/{doc_id}/unlock", json={"password": password}).json()
    assert info["needsPassword"] is False and info["pageCount"] == 1
    assert "encrypted" in [n["code"] for n in info["notices"]]
    # Inspecting the unlocked document must not disturb its decryption.
    assert client.get(f"/api/documents/{doc_id}").json()["needsPassword"] is False
    text = client.get(f"/api/documents/{doc_id}/pages/0/text").json()
    assert SECRET in "".join("".join(line["chars"]) for line in text["lines"])

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        doc.authenticate(USER_PASSWORD)
        hits = [tuple(r) for r in doc[0].search_for(SECRET)]
    output = client.post(f"/api/documents/{doc_id}/apply", json={"marks": [_mark(hits)]}).json()
    assert output["verification"]["passed"] is True
    out = client.get(f"/api/outputs/{output['id']}/file").content
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert doc.needs_pass  # encryption is kept
    assert SECRET not in mupdf_text(out, USER_PASSWORD)


def test_delete_document_removes_files(client) -> None:
    data = corpus.text_basic()
    doc_id = upload(client, data).json()["id"]
    output = client.post(
        f"/api/documents/{doc_id}/apply", json={"marks": [_mark(display_hits(data, SECRET))]}
    ).json()
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert client.get(f"/api/outputs/{output['id']}/file").status_code == 404
    assert not list(client.app.state.store.root.iterdir())


def test_store_removed_on_shutdown(settings) -> None:
    from fastapi.testclient import TestClient

    from pdf_redact.main import create_app

    with TestClient(create_app(settings), headers={"X-Session-Token": settings.token}) as c:
        upload(c, corpus.text_basic())
        root = c.app.state.store.root
        assert root.exists()
    assert not root.exists()


def test_filenames() -> None:
    assert clean_filename("C:\\Users\\me\\Secret.PDF") == "Secret.PDF"
    assert clean_filename("../../etc/passwd") == "passwd"
    assert clean_filename("bad\x00name\n.pdf") == "badname.pdf"
    assert clean_filename("") == "document.pdf"
    assert redacted_filename("Secret.PDF") == "Secret_redacted.pdf"
    assert redacted_filename("notes") == "notes_redacted.pdf"


def _search(client, doc_id: str, **body):
    return client.post(f"/api/documents/{doc_id}/search", json=body)


def test_search_returns_mark_geometry(client) -> None:
    doc_id = upload(client, corpus.many_pages(3)).json()["id"]
    res = _search(client, doc_id, query=SECRET.lower())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["truncated"] is False
    assert [m["page"] for m in body["matches"]] == [0, 1, 2]
    hit = body["matches"][0]
    assert hit["text"] == SECRET
    assert hit["before"].endswith(f"{ABOVE} Account number ")
    assert hit["after"].startswith(" is confidential.")
    assert hit["angle"] == 0

    # The rect is exactly what a manual text mark needs: applying it removes the secret.
    marks = [
        {"id": f"m{i}", "page": m["page"], "kind": "text", "rects": m["rects"]}
        for i, m in enumerate(body["matches"])
    ]
    out = client.post(f"/api/documents/{doc_id}/apply", json={"marks": marks}).json()
    assert out["verification"]["passed"] is True
    pdf = client.get(f"/api/outputs/{out['id']}/file").content
    text = mupdf_text(pdf)
    assert SECRET not in text
    assert text.count(ABOVE) == 3


def test_search_options_and_page_filter(client) -> None:
    doc_id = upload(client, corpus.many_pages(3)).json()["id"]
    assert _search(client, doc_id, query="visible", caseSensitive=True).json()["matches"] == []
    res = _search(client, doc_id, query=r"Page \d", mode="regex", pages=[2, 1]).json()
    assert [(m["page"], m["text"]) for m in res["matches"]] == [(1, "Page 2"), (2, "Page 3")]
    words = _search(client, doc_id, query="lin", mode="word").json()["matches"]
    assert words == []


def test_search_on_rotated_page(client) -> None:
    data = corpus.rotated(90)
    doc_id = upload(client, data).json()["id"]
    [hit] = _search(client, doc_id, query=SECRET).json()["matches"]
    [expected] = display_hits(data, SECRET)
    assert hit["rects"] == [pytest.approx(expected, abs=0.01)]
    assert hit["angle"] in (90, 270)


def test_search_errors(client) -> None:
    doc_id = upload(client, corpus.text_basic()).json()["id"]
    res = _search(client, doc_id, query="(oops", mode="regex")
    assert res.status_code == 422
    assert "Invalid regular expression" in res.json()["detail"]
    assert _search(client, doc_id, query="   ").status_code == 422
    assert _search(client, doc_id, query="x", pages=[5]).status_code == 404
    assert _search(client, "nope", query="x").status_code == 404

    locked = upload(client, corpus.encrypted()).json()["id"]
    assert _search(client, locked, query="x").status_code == 423


def test_search_truncates(client, monkeypatch) -> None:
    from pdf_redact import api

    monkeypatch.setattr(api, "MAX_MATCHES", 4)
    doc_id = upload(client, corpus.many_pages(3)).json()["id"]
    body = _search(client, doc_id, query="visible").json()
    assert len(body["matches"]) == 4
    assert body["truncated"] is True


def test_detectors_list(client) -> None:
    detectors = client.get("/api/detectors").json()
    ids = [d["id"] for d in detectors]
    assert {"ssn", "email", "phone", "card"} <= set(ids)
    assert all(d["label"] and d["short"] and "default" in d for d in detectors)


def test_detect_personal_info(client) -> None:
    doc_id = upload(client, corpus.personal_info()).json()["id"]
    res = client.post(
        f"/api/documents/{doc_id}/detect",
        json={
            "categories": ["ssn", "email", "phone", "card", "address"],
            "keywords": ["international", "jane q. doe"],
            "patterns": [{"name": "Case ref", "pattern": r"TOPSECRET-\d+"}],
        },
    )
    assert res.status_code == 200, res.text
    found = [(m["page"], m["category"], m["text"]) for m in res.json()["matches"]]
    assert found == [
        (0, "keyword", "Jane Q. Doe"),
        (0, "ssn", "123-45-6789"),
        (0, "phone", "(202) 555-0143"),
        (0, "email", "jane.doe@example.com"),
        (0, "address", "1600 Pennsylvania Avenue"),
        (0, "custom:Case ref", SECRET),
        (0, "keyword", "inter- national"),
        (1, "email", "john.smith@example.org"),
        (1, "phone", "415-555-2671"),
        (1, "card", "4111 1111 1111 1111"),
        (1, "custom:Case ref", SECRET),
    ]


def test_detect_errors(client) -> None:
    doc_id = upload(client, corpus.text_basic()).json()["id"]
    url = f"/api/documents/{doc_id}/detect"
    res = client.post(url, json={"categories": ["ssn", "horoscope"]})
    assert res.status_code == 422
    assert "horoscope" in res.json()["detail"]
    res = client.post(url, json={"patterns": [{"name": "Bad", "pattern": "[a-"}]})
    assert res.status_code == 422
    assert "“Bad”" in res.json()["detail"]
    assert client.post(url, json={}).json() == {"matches": [], "truncated": False}


def test_reports(client) -> None:
    data = corpus.text_basic()
    doc_id = upload(client, data).json()["id"]
    mark = {
        **_mark(display_hits(data, SECRET), overlayText="(b)(6)"),
        "source": "detect",
        "category": "SSN",
        "createdAt": "2024-05-06T07:00:00Z",
    }
    output = client.post(f"/api/documents/{doc_id}/apply", json={"marks": [mark]}).json()
    url = f"/api/outputs/{output['id']}/report"

    log = client.get(url, params={"format": "json"})
    assert log.status_code == 200
    assert (
        log.headers["content-disposition"]
        == "attachment; filename*=utf-8''case%20file_redaction_log.json"
    )
    audit = log.json()
    assert audit["input"]["filename"] == "case file.pdf"
    assert audit["input"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert audit["output"]["sha256"] == output["sha256"]
    assert audit["textInReport"] == "length"
    record = audit["marks"][0]
    assert (record["source"], record["category"]) == ("detect", "SSN")
    assert record["createdAt"] == "2024-05-06T07:00:00Z"
    assert record["textLength"] == len(SECRET)

    html = client.get(url)
    assert html.headers["content-type"].startswith("text/html")
    assert html.headers["content-disposition"].endswith("case%20file_redaction_report.html")
    assert "attachment" in html.headers["content-disposition"]
    csv_file = client.get(url, params={"format": "csv"})
    assert csv_file.headers["content-type"].startswith("text/csv")
    assert csv_file.content.startswith("\ufeff".encode())
    for res in (log, html, csv_file):
        assert SECRET not in res.text

    plain = client.get(url, params={"format": "json", "text": "plain"}).json()
    assert plain["marks"][0]["text"] == SECRET
    assert client.get(url, params={"text": "everything"}).status_code == 422
    assert client.get(url, params={"format": "pdf"}).status_code == 422
    assert client.get("/api/outputs/nope/report").status_code == 404


def test_marked_copy_round_trip(client) -> None:
    data = corpus.text_basic()
    info = upload(client, data).json()
    assert info["redactions"] == []
    rects = display_hits(data, SECRET)
    mark = {**_mark(rects, overlayText="(b)(6)"), "id": "mark-1"}
    page_mark = {"id": "mark-2", "page": 0, "kind": "page"}
    res = client.post(f"/api/documents/{info['id']}/marked", json={"marks": [mark, page_mark]})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"] == (
        "attachment; filename*=utf-8''case%20file_marked.pdf"
    )
    assert SECRET in mupdf_text(res.content), "nothing is removed from a marked copy"

    reopened = upload(client, res.content, "case file_marked.pdf").json()
    assert "existing-redactions" in [n["code"] for n in reopened["notices"]]
    text, page = reopened["redactions"]
    assert (text["id"], text["kind"], text["source"], text["text"]) == (
        "mark-1",
        "text",
        "import",
        SECRET,
    )
    assert all(abs(a - b) < 0.01 for a, b in zip(text["rects"][0], rects[0], strict=True))
    assert text["appearance"] == {
        "fill": "#000000",
        "textColor": "#ffffff",
        "overlayText": "(b)(6)",
        "fontSize": None,
        "align": "center",
        "font": "helv",
        "repeat": False,
    }
    assert (page["id"], page["kind"], page["rects"]) == ("mark-2", "page", [])

    # Imported marks apply like any other, and the annotations do not survive.
    applied = client.post(
        f"/api/documents/{reopened['id']}/apply", json={"marks": [{**text, "angle": None}]}
    )
    assert applied.status_code == 200
    out = client.get(f"/api/outputs/{applied.json()['id']}/file").content
    assert SECRET not in mupdf_text(out)
    assert ABOVE in mupdf_text(out)


def test_marked_copy_errors(client) -> None:
    doc_id = upload(client, corpus.text_basic()).json()["id"]
    bad = {"marks": [{"id": "m", "page": 5, "kind": "page"}]}
    assert client.post(f"/api/documents/{doc_id}/marked", json=bad).status_code == 422
    locked = upload(client, corpus.encrypted()).json()
    assert locked["redactions"] == []
    res = client.post(f"/api/documents/{locked['id']}/marked", json={"marks": []})
    assert res.status_code == 423
    assert client.post("/api/documents/nope/marked", json={"marks": []}).status_code == 404
