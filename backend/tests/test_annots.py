from __future__ import annotations

import pymupdf
import pytest

from pdf_redact.core.annots import marked_bytes, read_redact_annots, write_redact_annots
from pdf_redact.core.redact import Appearance, Mark, redact_bytes
from tests import corpus
from tests.corpus import ABOVE, BELOW, SECRET
from tests.helpers import area_mark, display_hits, mupdf_text, text_mark

ROUND_TRIP = ["text_basic", "rotated_90", "rotated_180", "rotated_270", "cropbox_offset"]


def _imported(data: bytes):
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return read_redact_annots(doc)


def _close(a, b, tol: float = 0.01) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


@pytest.mark.parametrize("name", ROUND_TRIP)
def test_round_trip(name: str) -> None:
    data = corpus.FIXTURES[name]()
    words = display_hits(data, "Account") + display_hits(data, "confidential.")
    below = display_hits(data, BELOW)[0]
    styled = Appearance(
        fill=(0.2, 0.4, 0.6),
        text_color=(1.0, 1.0, 0.0),
        overlay_text="(b)(6) — §552",
        font_size=9.0,
        align="right",
        font="cour",
        repeat=True,
    )
    marks = [
        Mark("t1", 0, "text", words, styled),
        area_mark(below, mark_id="a1", overlay="A"),
    ]
    out = marked_bytes(data, marks)

    assert SECRET in mupdf_text(out), "a marked copy keeps all content"
    imported = _imported(out)
    assert [(i.mark.id, i.mark.kind) for i in imported] == [("t1", "text"), ("a1", "area")]
    text, area = imported
    assert len(text.mark.rects) == 2
    for got, want in zip(text.mark.rects, words, strict=True):
        assert _close(got, want), (got, want)
    assert _close(area.mark.rects[0], below)
    assert text.mark.appearance == Appearance(
        fill=(0.2, 0.4, 0.6),
        text_color=(1.0, 1.0, 0.0),
        overlay_text="(b)(6) — §552",
        font_size=9.0,
        align="right",
        font="cour",
        repeat=True,
    )
    assert area.mark.appearance == Appearance(overlay_text="A")
    assert text.text == "Accountconfidential."
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        assert text.angle == -doc[0].rotation % 360, "text drawn upright turns with the page"


@pytest.mark.parametrize("name", ROUND_TRIP)
def test_other_tools_apply_each_quad(name: str) -> None:
    """MuPDF applying the annotations itself (as Acrobat would) removes exactly the marked words."""
    data = corpus.FIXTURES[name]()
    words = display_hits(data, "Account") + display_hits(data, "confidential.")
    out = marked_bytes(data, [text_mark(words)])
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        page = doc[0]
        page.apply_redactions()
        text = page.get_text()
    assert "Account" not in text
    assert "confidential" not in text
    assert SECRET in text, "the text between the two quadrilaterals survives"
    assert ABOVE in text and BELOW in text


def test_page_marks_and_split_areas() -> None:
    data = corpus.many_pages(3)
    marks = [
        Mark("p", 1, "page", []),
        Mark("multi", 2, "area", [(10, 10, 50, 50), (100, 100, 150, 150)]),
    ]
    imported = _imported(marked_bytes(data, marks))
    assert [(i.mark.id, i.mark.page, i.mark.kind) for i in imported] == [
        ("p", 1, "page"),
        ("multi", 2, "area"),
        ("multi-2", 2, "area"),
    ]
    assert imported[0].mark.rects == []


def test_replaces_existing_annotations() -> None:
    data = corpus.existing_redaction()
    (existing,) = _imported(data)
    assert existing.mark.kind == "area"
    assert existing.mark.appearance.fill is None, "no /IC means no fill"

    out = marked_bytes(data, [text_mark(display_hits(data, SECRET), mark_id="new")])
    assert [i.mark.id for i in _imported(out)] == ["new"]
    assert [i.mark.id for i in _imported(marked_bytes(data, []))] == []


def test_marks_on_missing_pages_are_rejected() -> None:
    with (
        pymupdf.open(stream=corpus.text_basic(), filetype="pdf") as doc,
        pytest.raises(ValueError, match="page 3"),
    ):
        write_redact_annots(doc, [Mark("m", 3, "page", [])])


def test_applying_drops_exported_annotations() -> None:
    data = corpus.text_basic()
    marked = marked_bytes(data, [text_mark(display_hits(data, ABOVE))])
    out, _ = redact_bytes(marked, [text_mark(display_hits(data, SECRET))])
    assert _imported(out) == []
    assert ABOVE in mupdf_text(out), "unapplied annotations are not applied implicitly"


def _foreign(**keys: str) -> bytes:
    """A /Redact annotation as another tool might write it."""
    doc = pymupdf.open()
    page = doc.new_page()
    corpus._three_lines(page)
    annot = page.add_redact_annot(pymupdf.Rect(70, 100, 300, 140))
    for key in ("NM", "DA", "Q", "IC", "OverlayText", "Repeat"):
        doc.xref_set_key(annot.xref, key, keys.get(key, "null"))
    return doc.tobytes()


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ({}, Appearance(fill=None)),
        (
            {"IC": "[0 0 0 1]", "DA": "(/TiRo 12 Tf 1 0 0 rg)", "Q": "2"},
            Appearance(text_color=(1.0, 0.0, 0.0), font="tiro", font_size=12.0, align="right"),
        ),
        (
            {"IC": "[0.5]", "DA": "(/Arial 0 Tf 0 g)", "OverlayText": "(Withheld)"},
            Appearance(
                fill=(0.5, 0.5, 0.5),
                text_color=(0.0, 0.0, 0.0),
                overlay_text="Withheld",
            ),
        ),
        (
            {"IC": "[1 1 1]", "DA": "(/Cour 200 Tf)", "Repeat": "true", "Q": "7"},
            Appearance(fill=(1.0, 1.0, 1.0), font="cour", font_size=72.0, repeat=True),
        ),
    ],
)
def test_foreign_appearance(keys: dict[str, str], expected: Appearance) -> None:
    (item,) = _imported(_foreign(**keys))
    assert item.mark.appearance == expected


def test_ids_are_unique() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    for i in range(3):
        annot = page.add_redact_annot(pymupdf.Rect(10, 10 + 30 * i, 100, 30 + 30 * i))
        doc.xref_set_key(annot.xref, "NM", "(same)" if i < 2 else "null")
    ids = [i.mark.id for i in _imported(doc.tobytes())]
    assert ids[0] == "same"
    assert len(set(ids)) == 3


def test_annotations_off_the_page_are_skipped() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.add_redact_annot(pymupdf.Rect(10, 10, 100, 100))
    page.set_cropbox(pymupdf.Rect(200, 200, 400, 400))
    assert _imported(doc.tobytes()) == []


def test_outline_appearance_only() -> None:
    """Viewers that do not apply redactions must not show the content as removed."""
    data = corpus.text_basic()
    out = marked_bytes(data, [text_mark(display_hits(data, SECRET))])
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        page = doc[0]
        annot = next(page.annots())
        ap = doc.xref_stream(int(doc.xref_get_key(annot.xref, "AP/N")[1].split()[0]))
        assert b" re S" in ap
        assert b" f" not in ap
