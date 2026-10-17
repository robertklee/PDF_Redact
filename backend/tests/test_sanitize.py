from __future__ import annotations

import pymupdf
import pytest

from pdf_redact.core.layers import Visibility
from pdf_redact.core.redact import RedactOptions, redact_bytes
from pdf_redact.core.sanitize import SanitizeOptions
from pdf_redact.core.verify import verify_bytes
from tests import corpus
from tests.corpus import ABOVE, BELOW, CLIPPED_SECRET, CLIPPED_VISIBLE, SECRET, SECRET_LINE
from tests.helpers import area_mark, display_hits, every_text, leaks, mupdf_text, text_mark

ONLY_PAGE_CONTENT = SanitizeOptions(
    metadata=False,
    annotations="keep",
    forms="keep",
    attachments=False,
    links=False,
    javascript=False,
    thumbnails=False,
)

EVERYTHING = SanitizeOptions(bookmarks=True, page_labels=True)
NOTHING = SanitizeOptions(
    metadata=False,
    annotations="keep",
    forms="keep",
    attachments=False,
    links=False,
    javascript=False,
    thumbnails=False,
    layers=False,
    outside_crop=False,
    hidden_text=False,
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
    "name",
    [
        "metadata",
        "attachments",
        "javascript",
        "annotations",
        "actual_text",
        "hidden_text",
        "outside_crop",
        "off_page_text",
        "layers",
        "form_fields",
        "field_with_kids",
        "tagged",
        "incremental_update",
        "kitchen_sink",
    ],
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


def _looks_the_same(a: bytes, b: bytes) -> bool:
    """Whether two files render alike, up to anti-aliasing changes from rewritten content."""
    with _doc(a) as first, _doc(b) as second:
        for pa, pb in zip(first, second, strict=True):
            sa, sb = pa.get_pixmap(dpi=96).samples, pb.get_pixmap(dpi=96).samples
            if len(sa) != len(sb) or any(abs(x - y) > 32 for x, y in zip(sa, sb, strict=True)):
                return False
    return True


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_hidden_text_is_removed_and_visible_text_kept(rotation: int) -> None:
    with _doc(corpus.hidden_text()) as doc:
        doc[0].set_rotation(rotation)
        data = doc.tobytes()
    out, stats, verification = _sanitize(data, ONLY_PAGE_CONTENT)
    assert _action(stats, "hidden-text").count == 3 * len(SECRET) + len("InvisibleWhiteCovered")
    assert _check(verification, "hidden-text").status == "pass"
    text = mupdf_text(out)
    assert "Invisible" not in text and "White" not in text and "Covered" not in text
    assert SECRET_LINE in text and ABOVE in text and BELOW in text
    assert _looks_the_same(out, data)


def test_original_with_hidden_text_fails_the_check() -> None:
    verification = verify_bytes(corpus.hidden_text(), [], RedactOptions(sanitize=ONLY_PAGE_CONTENT))
    check = _check(verification, "hidden-text")
    assert check.status == "fail"
    assert "hidden character" in check.message


def test_text_hidden_by_a_clip_path_is_hidden_text() -> None:
    data = corpus.clipped_text()
    assert CLIPPED_SECRET in every_text(data) and CLIPPED_SECRET not in mupdf_text(data)
    original = verify_bytes(data, [], RedactOptions(sanitize=ONLY_PAGE_CONTENT))
    assert _check(original, "hidden-text").status == "fail"

    out, stats, verification = _sanitize(data, ONLY_PAGE_CONTENT)
    assert _check(verification, "hidden-text").status == "pass"
    assert _action(stats, "hidden-text").count == len(f"{CLIPPED_SECRET}overflow")
    assert not leaks(out, CLIPPED_SECRET) and "overflow" not in every_text(out)
    assert CLIPPED_VISIBLE in mupdf_text(out) and SECRET_LINE in mupdf_text(out)
    assert _looks_the_same(out, data)


def test_ocr_text_layer_is_kept_unless_asked() -> None:
    data = corpus.image_with_ocr_text()
    out, stats, verification = _sanitize(data, ONLY_PAGE_CONTENT)
    assert _action(stats, "hidden-text").count == 0
    assert SECRET in mupdf_text(out)
    assert verification.passed

    strict = SanitizeOptions(**{**ONLY_PAGE_CONTENT.__dict__, "keep_ocr_text": False})
    out, stats, verification = _sanitize(data, strict)
    assert _action(stats, "hidden-text").count > 0
    assert not mupdf_text(out).strip()
    assert verification.passed


def test_content_outside_the_crop_box_is_removed() -> None:
    data = corpus.outside_crop()
    original = verify_bytes(data, [], RedactOptions(sanitize=ONLY_PAGE_CONTENT))
    assert _check(original, "outside-crop").status == "fail"

    out, stats, verification = _sanitize(data, ONLY_PAGE_CONTENT)
    assert _action(stats, "outside-crop").count == 1
    assert _check(verification, "outside-crop").status == "pass"
    assert not leaks(out, "Outside crop") and not leaks(out, "Off the page")
    assert SECRET_LINE in mupdf_text(out)
    with _doc(out) as doc:
        page = doc[0]
        assert len(page.get_image_info()) == 1  # the image wholly outside is gone
        assert len(page.get_drawings()) == 1  # only the visible rectangle is left
    assert _looks_the_same(out, data)


def test_visible_pages_are_not_touched_by_page_content_options() -> None:
    for name in ("text_basic", "rotated_90", "vertical_text", "image_with_ocr_text"):
        data = corpus.FIXTURES[name]()
        _, stats, _ = _sanitize(data, ONLY_PAGE_CONTENT)
        assert _action(stats, "outside-crop").count == 0, name
        assert _action(stats, "hidden-text").count == 0, name


def test_hidden_layers_are_removed_and_visible_layers_merged() -> None:
    data = corpus.layers()
    out, stats, verification = _sanitize(data, ONLY_PAGE_CONTENT)
    assert _action(stats, "layers").count == 1
    assert _check(verification, "layers").status == "pass"
    text = mupdf_text(out)
    assert "Hidden layer" not in text and "Needs both" not in text
    assert "Shown layer text" in text and "Shown by expression" in text and SECRET_LINE in text
    # Hidden text, the hidden image and comment, and the layer names are all gone.
    assert not leaks(out, corpus.LAYER_SECRET)
    assert not leaks(out, "Draft notes")
    with _doc(out) as doc:
        page = doc[0]
        assert not page.get_image_info()
        assert not list(page.annots())
        assert not page.get_drawings()
        assert not doc.get_ocgs()


def test_original_with_layers_fails_the_check() -> None:
    verification = verify_bytes(corpus.layers(), [], RedactOptions(sanitize=ONLY_PAGE_CONTENT))
    check = _check(verification, "layers")
    assert check.status == "fail"
    assert "layer definitions remain" in check.message


@pytest.mark.parametrize(
    ("kwargs", "hidden"),
    [
        ({"ocgs": "both", "policy": "AnyOn"}, False),
        ({"ocgs": "both", "policy": "AllOn"}, True),
        ({"ocgs": "both", "policy": "AnyOff"}, False),
        ({"ocgs": "both", "policy": "AllOff"}, True),
        ({"ocgs": "off", "policy": "AnyOff"}, False),
        ({"ve": ["not", "off"]}, False),
        ({"ve": ["and", "on", "off"]}, True),
        ({"ve": ["or", "on", ["not", "on"]]}, False),
        ({"ve": ["and", "on", ["not", "on"]]}, True),
    ],
)
def test_layer_membership_policies(kwargs: dict, hidden: bool) -> None:
    doc = pymupdf.open()
    doc.new_page()
    xrefs = {"off": doc.add_ocg("Off", on=False), "on": doc.add_ocg("On", on=True)}

    def resolve(value):
        if isinstance(value, list):
            return [v if i == 0 else resolve(v) for i, v in enumerate(value)]
        return xrefs[value]

    if "ve" in kwargs:
        ocmd = doc.set_ocmd(ve=resolve(kwargs["ve"]))
    else:
        members = list(xrefs.values()) if kwargs["ocgs"] == "both" else [xrefs["off"]]
        ocmd = doc.set_ocmd(ocgs=members, policy=kwargs["policy"])
    with _doc(doc.tobytes()) as reopened:
        assert Visibility(reopened).hidden(ocmd) is hidden
