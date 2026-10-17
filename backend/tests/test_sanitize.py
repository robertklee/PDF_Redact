from __future__ import annotations

import pymupdf
import pytest

from pdf_redact.core.redact import RedactOptions, redact_bytes
from pdf_redact.core.sanitize import SanitizeOptions
from pdf_redact.core.verify import verify_bytes
from tests import corpus
from tests.corpus import ABOVE, SECRET
from tests.helpers import area_mark, display_hits, leaks, mupdf_text, text_mark

EVERYTHING = SanitizeOptions(bookmarks=True, page_labels=True)
NOTHING = SanitizeOptions(
    metadata=False,
    annotations="keep",
    forms="keep",
    attachments=False,
    links=False,
    javascript=False,
    thumbnails=False,
)


def _marks_for(data: bytes, needle: str = SECRET, password: str | None = None) -> list:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pages = doc.page_count
    return [
        text_mark(hits, page=pno, mark_id=f"m{pno}")
        for pno in range(pages)
        if (hits := display_hits(data, needle, pno, password))
    ]


def _sanitize(data: bytes, sanitize=EVERYTHING, marks=(), password=None):
    options = RedactOptions(sanitize=sanitize)
    out, stats = redact_bytes(data, list(marks), options, password)
    verification = verify_bytes(out, list(marks), options, password)
    return out, stats, verification


def _check(verification, code: str):
    return next(c for c in verification.checks if c.name == f"sanitize-{code}")


def _action(stats, code: str):
    return next(a for a in stats.sanitized if a.code == code)


def _doc(data: bytes) -> pymupdf.Document:
    return pymupdf.open(stream=data, filetype="pdf")


@pytest.mark.parametrize(
    "name", ["metadata", "attachments", "javascript", "annotations", "actual_text", "kitchen_sink"]
)
def test_redacting_and_sanitizing_leaves_no_trace_of_the_secret(name: str) -> None:
    data = corpus.FIXTURES[name]()
    assert leaks(data, SECRET)
    out, _, verification = _sanitize(data, marks=_marks_for(data))
    assert verification.passed, [c for c in verification.checks if c.status != "pass"]
    assert not leaks(out, SECRET)


@pytest.mark.parametrize("name", sorted(corpus.FIXTURES))
def test_every_sanitize_check_passes_on_every_fixture(name: str) -> None:
    data = corpus.FIXTURES[name]()
    password = corpus.USER_PASSWORD if name == "encrypted" else None
    _, _, verification = _sanitize(data, password=password)
    failed = [c for c in verification.checks if c.status == "fail"]
    assert not failed


def test_metadata_is_removed() -> None:
    data = corpus.metadata()
    out, stats, verification = _sanitize(data, marks=_marks_for(data))
    assert _action(stats, "metadata").count >= 4  # author, subject, keywords, ... and XMP
    assert _check(verification, "metadata").status == "pass"
    with _doc(out) as doc:
        assert not doc.get_xml_metadata()
        assert not doc.metadata["author"]
        assert not doc.metadata["title"]


def test_disabled_options_keep_everything() -> None:
    data = corpus.metadata()
    out, stats, verification = _sanitize(data, NOTHING)
    assert stats.sanitized == []
    assert not any(c.name.startswith("sanitize-") for c in verification.checks)
    with _doc(out) as doc:
        assert doc.metadata["author"] == SECRET
        assert SECRET in doc.get_xml_metadata()


def test_original_with_javascript_fails_the_check() -> None:
    data = corpus.javascript()
    verification = verify_bytes(data, [], RedactOptions(sanitize=EVERYTHING))
    check = _check(verification, "javascript")
    assert check.status == "fail"
    assert not verification.passed


def test_javascript_and_automatic_actions_are_removed() -> None:
    doc = _doc(corpus.javascript())
    page = doc[0]
    js = doc.get_new_xref()
    doc.update_object(js, "<</S/JavaScript/JS(app.alert('page-open'))>>")
    doc.xref_set_key(page.xref, "AA", f"<</O {js} 0 R>>")
    page.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(72, 400, 200, 420),
            "uri": "https://example.org",
        }
    )
    names = doc.get_new_xref()
    doc.update_object(names, "<</S/JavaScript/JS(app.alert('names'))>>")
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</JavaScript<</Names[(a) {names} 0 R]>>>>")
    data = doc.tobytes()
    out, stats, verification = _sanitize(data, SanitizeOptions(links=False))
    assert _action(stats, "javascript").count >= 3
    assert _check(verification, "javascript").status == "pass"
    for needle in ("app.alert", "/JavaScript", "/AA"):
        assert not leaks(out, needle), needle
    with _doc(out) as doc:
        # Ordinary links are not actions that run anything.
        assert [link["uri"] for link in doc[0].get_links()] == ["https://example.org"]


def test_open_action_that_is_a_destination_is_kept() -> None:
    doc = pymupdf.open()
    doc.new_page()
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"[{doc[0].xref} 0 R /Fit]")
    out, _, verification = _sanitize(doc.tobytes())
    assert verification.passed
    with _doc(out) as doc:
        assert doc.xref_get_key(doc.pdf_catalog(), "OpenAction")[0] == "array"


def test_attachments_are_removed() -> None:
    doc = _doc(corpus.attachments())
    annot = doc[0].add_file_annot((300, 300), b"annotated " + SECRET.encode(), "note.txt")
    annot.update()
    data = doc.tobytes()
    out, stats, verification = _sanitize(data, SanitizeOptions(annotations="keep"))
    assert _action(stats, "attachments").count == 2
    assert _check(verification, "attachments").status == "pass"
    assert not leaks(out, "annotated")
    assert not leaks(out, "secret.txt")


def test_comments_are_removed() -> None:
    data = corpus.annotations()
    out, stats, verification = _sanitize(data)
    assert _action(stats, "annotations").count == 2
    assert _check(verification, "annotations").status == "pass"
    assert not leaks(out, f"Note about {SECRET}")
    assert not leaks(out, f"Comment {SECRET}")
    assert ABOVE in mupdf_text(out)


def test_comments_can_be_flattened_and_then_redacted() -> None:
    data = corpus.annotations()
    out, stats, verification = _sanitize(data, SanitizeOptions(annotations="flatten"))
    assert _action(stats, "annotations").count == 2
    assert verification.passed
    with _doc(out) as doc:
        assert not list(doc[0].annots())
    # The free-text comment is now page text; its popup note is gone.
    assert f"Comment {SECRET}" in mupdf_text(out)
    assert not leaks(out, f"Note about {SECRET}")
    # Marks on the flattened comment remove it.
    out, _, verification = _sanitize(
        data, SanitizeOptions(annotations="flatten"), [area_mark((300, 300, 500, 340))]
    )
    assert verification.passed
    assert f"Comment {SECRET}" not in mupdf_text(out)


def test_flattening_comments_does_not_bake_unapplied_redactions() -> None:
    data = corpus.existing_redaction()  # a page with only text and a /Redact annotation
    out, _, verification = _sanitize(data, SanitizeOptions(annotations="flatten"))
    assert verification.passed
    with _doc(out) as doc:
        assert not doc[0].get_drawings()
    assert ABOVE in mupdf_text(out)


def test_links_are_removed() -> None:
    doc = _doc(corpus.text_basic())
    doc[0].insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(72, 400, 200, 420),
            "uri": f"mailto:{SECRET}@x.org",
        }
    )
    out, stats, verification = _sanitize(doc.tobytes())
    assert _action(stats, "links").count == 1
    assert _check(verification, "links").status == "pass"
    assert not leaks(out, f"mailto:{SECRET}")


def test_form_fields_are_flattened_before_marks() -> None:
    data = corpus.form_fields()
    out, stats, verification = _sanitize(data)
    assert _action(stats, "forms").count == 1
    assert _check(verification, "forms").status == "pass"
    with _doc(out) as doc:
        assert not doc.is_form_pdf
        assert not list(doc[0].widgets())
    assert SECRET in mupdf_text(out)  # the value is now ordinary page text
    out, _, verification = _sanitize(data, marks=[area_mark((100, 80, 320, 110))])
    assert verification.passed
    assert not leaks(out, SECRET)
    assert "SSN:" in mupdf_text(out)


def test_form_fields_can_be_reset() -> None:
    for data in (corpus.form_fields(), corpus.field_with_kids()):
        out, stats, verification = _sanitize(data, SanitizeOptions(forms="reset"))
        assert _action(stats, "forms").count >= 1
        assert _check(verification, "forms").status == "pass"
        assert not leaks(out, SECRET)
        with _doc(out) as doc:
            assert [w.field_name for w in doc[0].widgets()][0] == "ssn"


def test_original_form_fails_the_reset_check() -> None:
    verification = verify_bytes(
        corpus.form_fields(), [], RedactOptions(sanitize=SanitizeOptions(forms="reset"))
    )
    assert _check(verification, "forms").status == "fail"


def test_bookmarks_page_labels_and_thumbnails() -> None:
    doc = _doc(corpus.many_pages(3))
    doc.set_toc([[1, f"Chapter {SECRET}", 1], [2, "Section", 2]])
    doc.set_page_labels([{"startpage": 0, "prefix": f"{SECRET}-", "style": "D"}])
    thumb = doc.get_new_xref()
    doc.update_object(
        thumb,
        "<</Type/XObject/Subtype/Image/Width 1/Height 1/ColorSpace/DeviceGray/BitsPerComponent 8>>",
    )
    doc.update_stream(thumb, b"\x00")
    doc.xref_set_key(doc[0].xref, "Thumb", f"{thumb} 0 R")
    data = doc.tobytes()

    out, _, _ = _sanitize(data, SanitizeOptions())  # bookmarks and labels are kept by default
    with _doc(out) as result:
        assert len(result.get_toc()) == 2
        assert result[0].get_label() == f"{SECRET}-1"
        assert result.xref_get_key(result[0].xref, "Thumb")[0] == "null"

    out, stats, verification = _sanitize(data)
    assert _action(stats, "bookmarks").count == 2
    assert _action(stats, "page-labels").count == 1
    assert _action(stats, "thumbnails").count == 1
    assert verification.passed
    assert not leaks(out, f"Chapter {SECRET}")
    assert not leaks(out, f"{SECRET}-")
