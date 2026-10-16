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
