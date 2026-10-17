from __future__ import annotations

import pymupdf
import pytest

from pdf_redact.core.geometry import to_display, union
from pdf_redact.core.redact import (
    Appearance,
    Mark,
    RedactOptions,
    redact_bytes,
)
from pdf_redact.core.search import compile_query, find
from pdf_redact.core.text import extract_lines, line_texts, page_text_payload
from pdf_redact.core.verify import verify_bytes
from tests import corpus
from tests.corpus import ABOVE, BELOW, SECRET
from tests.helpers import (
    area_mark,
    display_hits,
    leaks,
    mupdf_text,
    pypdf_text,
    raw_contains,
    text_mark,
)


def _redact_and_verify(data, marks, options=None, password=None):
    out, stats = redact_bytes(data, marks, options, password)
    verification = verify_bytes(out, marks, options, password)
    return out, stats, verification


def _mark_check(verification):
    return [c for c in verification.checks if c.name == "mark"][-1]


def _assert_gone(out: bytes, needle: str = SECRET, password: str | None = None) -> None:
    assert needle not in mupdf_text(out, password)
    assert needle not in pypdf_text(out, password)


def _assert_neighbours_intact(out: bytes, password: str | None = None) -> None:
    for engine in (mupdf_text, pypdf_text):
        text = engine(out, password)
        assert ABOVE in text
        assert BELOW in text
        assert "Account number" in text
        assert "is confidential." in text


def test_text_mark_removes_only_selected_text() -> None:
    data = corpus.text_basic()
    assert SECRET in pypdf_text(data)
    out, stats, verification = _redact_and_verify(data, [text_mark(display_hits(data, SECRET))])
    _assert_gone(out)
    _assert_neighbours_intact(out)
    assert verification.passed, verification.checks
    assert stats.glyphs_removed == len(SECRET)
    assert stats.safety_pass_glyphs == 0


def test_partial_word_selection_keeps_rest_of_word() -> None:
    data = corpus.text_basic()
    out, _, verification = _redact_and_verify(data, [text_mark(display_hits(data, "SECRET"))])
    text = mupdf_text(out)
    assert "SECRET" not in text
    assert "TOP" in text and "-4471" in text
    assert verification.passed


@pytest.mark.parametrize("ratio", [1.0, 0.9])
def test_tight_leading_keeps_adjacent_lines(ratio: float) -> None:
    data = corpus.tight_leading(ratio)
    out, _, verification = _redact_and_verify(data, [text_mark(display_hits(data, SECRET))])
    _assert_gone(out)
    _assert_neighbours_intact(out)
    assert verification.passed


def test_multi_line_text_mark() -> None:
    data = corpus.text_basic()
    rects = display_hits(data, ABOVE) + display_hits(data, "Account number")
    out, _, verification = _redact_and_verify(data, [text_mark(rects)])
    text = mupdf_text(out)
    assert ABOVE not in text and "Account number" not in text
    assert BELOW in text and SECRET in text
    assert verification.passed


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_pages(rotation: int) -> None:
    data = corpus.rotated(rotation)
    hits = display_hits(data, SECRET)
    marks = [text_mark(hits, overlay="(b)(6)")]
    out, _, verification = _redact_and_verify(data, marks)
    _assert_gone(out)
    _assert_neighbours_intact(out)
    assert verification.passed, verification.checks
    _assert_overlay_follows_text(data, out, "(b)(6)", pymupdf.Rect(hits[0]))


def _assert_overlay_follows_text(
    original: bytes, out: bytes, overlay: str, mark: pymupdf.Rect
) -> None:
    with pymupdf.open(stream=original, filetype="pdf") as doc:
        secret_line = next(
            line for line in extract_lines(doc[0]) if SECRET in "".join(ch.c for ch in line)
        )
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        page = doc[0]
        lines = [line for line in extract_lines(page) if "".join(ch.c for ch in line) == overlay]
        assert lines, "overlay text missing"
        # The overlay runs in the same direction as the text it replaces...
        assert lines[0][0].dir == pytest.approx(secret_line[0].dir, abs=1e-3)
        # ...and is centred in the mark (as displayed).
        shown = union([ch.box for ch in lines[0]]) * page.rotation_matrix
        centre, expected = (shown.tl + shown.br) / 2, (mark.tl + mark.br) / 2
        assert (centre.x, centre.y) == pytest.approx((expected.x, expected.y), abs=1.5)
        assert mark.contains(shown)


def test_vertical_text_within_page() -> None:
    data = corpus.vertical_text()
    hits = display_hits(data, SECRET)
    out, _, verification = _redact_and_verify(data, [text_mark(hits, overlay="(b)(6)")])
    _assert_gone(out)
    _assert_neighbours_intact(out)
    assert verification.passed
    _assert_overlay_follows_text(data, out, "(b)(6)", pymupdf.Rect(hits[0]))


def test_cropbox_offset() -> None:
    data = corpus.cropbox_offset()
    out, _, verification = _redact_and_verify(data, [text_mark(display_hits(data, SECRET)[:1])])
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert SECRET not in doc[0].get_text(clip=doc[0].rect)
    assert verification.passed


def test_invisible_ocr_text_and_image_pixels_removed() -> None:
    data = corpus.image_with_ocr_text()
    hits = display_hits(data, SECRET)
    out, _, verification = _redact_and_verify(data, [text_mark(hits)])
    _assert_gone(out)
    _assert_neighbours_intact(out)
    assert verification.passed, verification.checks
    # Pixels beneath the mark are blanked, but the rest of the image is untouched.
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        info = doc[0].get_image_info(xrefs=True)[0]
        pix = pymupdf.Pixmap(doc, info["xref"])
        assert pix.color_count(clip=pymupdf.IRect(0, 0, 20, 20)) > 1


def test_area_mark_blanks_scanned_image_region() -> None:
    data = corpus.scanned_image()
    marks = [area_mark((150, 100, 250, 180))]
    out, _, verification = _redact_and_verify(data, marks)
    assert verification.passed, verification.checks
    # The original image is noisy under the same region, so the check is meaningful.
    bad = verify_bytes(data, marks)
    assert not bad.passed
    assert "image pixels" in _mark_check(bad).message


def test_image_mode_remove_drops_whole_image() -> None:
    data = corpus.scanned_image()
    marks = [area_mark((150, 100, 250, 180))]
    options = RedactOptions(images="remove")
    out, _, verification = _redact_and_verify(data, marks, options)
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert doc[0].get_image_info() == []
    assert verification.passed


def test_vector_graphics_covered_removed_and_crossing_warned() -> None:
    data = corpus.vector_graphics()
    marks = [area_mark((200, 170, 280, 230))]
    out, _, verification = _redact_and_verify(data, marks)
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        fills = [d.get("fill") for d in doc[0].get_drawings()]
    assert (1.0, 0.0, 0.0) not in fills  # fully covered red square is gone
    assert verification.passed
    assert _mark_check(verification).status == "warn"
    assert "vector path" in _mark_check(verification).message


def test_vector_graphics_touched_mode_removes_crossing_line() -> None:
    data = corpus.vector_graphics()
    marks = [area_mark((200, 170, 280, 230))]
    out, _, verification = _redact_and_verify(data, marks, RedactOptions(graphics="touched"))
    assert _mark_check(verification).status == "pass"


def _all_text_ignoring_cropbox(data: bytes) -> str:
    """MuPDF only extracts text inside the CropBox, so widen it to reveal hidden content."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        page = doc[0]
        page.set_cropbox(page.mediabox)
        return page.get_text()


def test_page_mark_removes_everything_including_outside_cropbox() -> None:
    data = corpus.cropbox_offset()
    assert "Outside crop" in _all_text_ignoring_cropbox(data)
    mark = Mark("p1", 0, "page", [], Appearance(overlay_text="WITHHELD"))
    out, _, verification = _redact_and_verify(data, [mark])
    assert "".join(_all_text_ignoring_cropbox(out).split()) == "WITHHELD"
    assert verification.passed


def test_incremental_revisions_are_dropped() -> None:
    data = corpus.incremental_update()
    assert raw_contains(data, "OLD-REVISION-SECRET")
    out, _, verification = _redact_and_verify(data, [text_mark(display_hits(data, SECRET))])
    assert not raw_contains(out, "OLD-REVISION-SECRET")
    assert out.count(b"startxref") == 1
    assert verification.checks[0].name == "single-revision"
    assert verification.checks[0].status == "pass"
    assert verify_bytes(data, []).checks[0].status == "fail"


def test_encrypted_input_stays_encrypted() -> None:
    data = corpus.encrypted()
    pw = corpus.USER_PASSWORD
    with pytest.raises(PermissionError):
        redact_bytes(data, [], password="wrong")
    hits = display_hits(data, SECRET, password=pw)
    out, _, verification = _redact_and_verify(data, [text_mark(hits)], password=pw)
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert doc.needs_pass
    _assert_gone(out, password=pw)
    assert verification.passed


def test_preexisting_redact_annotations_are_not_applied_implicitly() -> None:
    data = corpus.existing_redaction()
    # Foreign /Redact annotations are dropped from every page, whether or not it has marks.
    data = _with_blank_page(data)
    for page in (0, 1):
        marks = (
            [text_mark(display_hits(data, SECRET))] if page == 0 else [area_mark((0, 0, 9, 9), 1)]
        )
        out, _, _ = _redact_and_verify(data, marks)
        assert ABOVE in mupdf_text(out)
        with pymupdf.open(stream=out, filetype="pdf") as doc:
            assert not any(list(p.annots(types=[pymupdf.PDF_ANNOT_REDACT])) for p in doc)


def _with_blank_page(data: bytes) -> bytes:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        doc.new_page()
        return doc.tobytes()


def test_text_mark_without_glyphs_falls_back_to_area() -> None:
    data = corpus.scanned_image()
    marks = [text_mark([(150, 100, 250, 180)], mark_id="t-empty")]
    out, stats, verification = _redact_and_verify(data, marks)
    assert stats.text_marks_as_area == ["t-empty"]
    assert verification.passed


def test_verification_flags_unredacted_text() -> None:
    data = corpus.text_basic()
    marks = [text_mark(display_hits(data, SECRET))]
    result = verify_bytes(data, marks)
    assert not result.passed
    assert "text character" in _mark_check(result).message


def _search_marks(data: bytes, query: str, pages=None, overlay: str = ""):
    """Marks for every hit of `query`, as the UI makes them from search results, and hit texts."""
    marks, terms = [], []
    pattern = compile_query(query, "phrase", False)
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            if pages is not None and page.number not in pages:
                continue
            for i, hit in enumerate(find(page.number, page_text_payload(page)["lines"], pattern)):
                marks.append(text_mark(hit.rects, page.number, f"s{page.number}-{i}", overlay))
                terms.append(hit.text)
    return marks, terms


def _residual(verification):
    return [c for c in verification.checks if c.name == "residual-text"]


def test_residual_check_reports_unmarked_occurrences() -> None:
    data = corpus.personal_info()
    marks, terms = _search_marks(data, SECRET, pages={0})
    out, _ = redact_bytes(data, marks)
    result = verify_bytes(out, marks, search_terms=terms)
    assert result.passed
    [check] = _residual(result)
    assert check.status == "warn" and check.page == 1
    assert check.message == f"Marked search result “{SECRET}” still appears on page 2"

    marks, terms = _search_marks(data, SECRET)
    out, _ = redact_bytes(data, marks)
    [check] = _residual(verify_bytes(out, marks, search_terms=terms))
    assert check.status == "pass"
    assert check.message == "Marked search results appear nowhere else in the file (1 text checked)"
    assert not _residual(verify_bytes(out, marks))


def test_residual_check_handles_line_hyphenation() -> None:
    data = corpus.personal_info()
    marks, terms = _search_marks(data, "international")
    assert terms == ["inter- national"]
    [check] = _residual(verify_bytes(data, marks, search_terms=terms))
    assert check.status == "warn" and check.page == 0
    for term in ("international", "INTER-NATIONAL"):
        assert _residual(verify_bytes(data, [], search_terms=[term]))[0].status == "warn"

    out, _ = redact_bytes(data, marks)
    assert _residual(verify_bytes(out, marks, search_terms=terms))[0].status == "pass"


def test_residual_check_ignores_overlay_text() -> None:
    data = corpus.personal_info()
    marks, _ = _search_marks(data, SECRET, overlay="SECRET")
    out, _ = redact_bytes(data, marks)
    assert mupdf_text(out).count("SECRET") == 2
    assert _residual(verify_bytes(out, marks, search_terms=["Secret"]))[0].status == "pass"
    [check] = _residual(verify_bytes(out, [], search_terms=["Secret"]))
    assert check.message == "Marked search result “Secret” still appears on pages 1 and 2"


@pytest.mark.parametrize("name", sorted(set(corpus.FIXTURES) - {"encrypted"}))
def test_line_texts_match_extracted_lines(name: str) -> None:
    with pymupdf.open(stream=corpus.FIXTURES[name](), filetype="pdf") as doc:
        for page in doc:
            lines = ["".join(ch.c for ch in line) for line in extract_lines(page)]
            assert [t for t in line_texts(page) if t] == lines


def test_overlay_text_and_fill_colour() -> None:
    data = corpus.text_basic()
    mark = Mark(
        "m1",
        0,
        "area",
        [display_hits(data, SECRET)[0]],
        Appearance(fill=(1, 0, 0), text_color=(0, 0, 0), overlay_text="(b)(6)"),
    )
    out, _, verification = _redact_and_verify(data, [mark])
    assert "(b)(6)" in mupdf_text(out)
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert any(d.get("fill") == (1.0, 0.0, 0.0) for d in doc[0].get_drawings())
    assert verification.passed


def test_mark_on_missing_page_rejected() -> None:
    with pytest.raises(ValueError):
        redact_bytes(corpus.text_basic(), [area_mark((0, 0, 10, 10), page=5)])


def test_display_space_roundtrip_matches_rotation() -> None:
    data = corpus.rotated(90)
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        page = doc[0]
        assert page.rect.width == pytest.approx(842)  # A4 portrait shown landscape
        r = to_display(page, page.search_for(SECRET)[0])
        assert page.rect.contains(r)


def test_replacement_text_is_removed_from_redacted_pages() -> None:
    data = corpus.actual_text()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        hits = [tuple(to_display(doc[0], r)) for r in doc[0].search_for(SECRET)]
    assert len(hits) == 3
    marks = [area_mark(r, mark_id=f"a{i}") for i, r in enumerate(hits)]
    out, stats, verification = _redact_and_verify(data, marks)
    assert stats.replacement_text_removed >= 3
    assert verification.passed
    assert any(c.name == "replacement-text" and c.status == "pass" for c in verification.checks)
    _assert_gone(out)
    assert not leaks(out, SECRET)
    assert ABOVE in mupdf_text(out)


def test_leftover_replacement_text_fails_verification() -> None:
    data = corpus.actual_text()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        hit = tuple(to_display(doc[0], doc[0].search_for(SECRET)[0]))
    mark = area_mark(hit)
    # The untouched original still has /ActualText on the marked page.
    verification = verify_bytes(data, [mark])
    check = next(c for c in verification.checks if c.name == "replacement-text")
    assert check.status == "fail"
    assert not verification.passed


def test_form_field_under_a_mark_is_removed_with_its_value() -> None:
    data = corpus.form_fields()
    out, stats, verification = _redact_and_verify(data, [area_mark((100, 80, 320, 110))])
    assert stats.annotations_removed == 1
    assert verification.passed, verification.checks
    assert not leaks(out, SECRET)
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert not list(doc[0].widgets())
        assert "SSN:" in doc[0].get_text()


def test_field_value_is_cleared_only_when_every_widget_is_redacted() -> None:
    data = corpus.field_with_kids()
    out, stats, _ = _redact_and_verify(data, [area_mark((140, 80, 350, 110))])
    assert stats.annotations_removed == 1
    assert leaks(out, SECRET)  # the other widget still shows the value
    marks = [area_mark((140, 80, 350, 110)), area_mark((140, 280, 350, 310), mark_id="a2")]
    out, stats, verification = _redact_and_verify(data, marks)
    assert stats.annotations_removed == 2
    assert verification.passed, verification.checks
    assert not leaks(out, SECRET)


def test_annotations_and_links_under_a_mark_are_removed() -> None:
    doc = pymupdf.open(stream=corpus.annotations(), filetype="pdf")
    page = doc[0]
    hit = page.search_for(SECRET)[0]
    page.insert_link({"kind": pymupdf.LINK_URI, "from": hit, "uri": f"mailto:{SECRET}@x.org"})
    page.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(72, 400, 200, 420),
            "uri": "https://example.org",
        }
    )
    data = doc.tobytes()
    # The sticky note's icon sits on the secret; the free-text comment is elsewhere.
    out, stats, verification = _redact_and_verify(data, [area_mark(tuple(hit + (-2, -20, 2, 2)))])
    assert stats.annotations_removed >= 1  # MuPDF itself drops covered links
    assert verification.passed, verification.checks
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert [a.type[1] for a in doc[0].annots()] == ["FreeText"]
        assert [link["uri"] for link in doc[0].get_links()] == ["https://example.org"]
    assert not leaks(out, f"Note about {SECRET}")
    assert not leaks(out, f"mailto:{SECRET}")


def test_annotation_left_under_a_mark_fails_verification() -> None:
    data = corpus.annotations()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        hit = doc[0].search_for(SECRET)[0]
    verification = verify_bytes(data, [area_mark(tuple(hit + (-2, -20, 2, 2)))])
    check = _mark_check(verification)
    assert check.status == "fail"
    assert "annotation" in check.message


def test_page_mark_removes_text_outside_the_media_box() -> None:
    data = corpus.off_page_text()
    assert leaks(data, f"Above the page {SECRET}")
    page = Mark("p1", 0, "page", [])
    out, _, verification = _redact_and_verify(data, [page])
    assert verification.passed, verification.checks
    assert not leaks(out, SECRET)
    assert not leaks(out, "Visible line")
    # The untouched original fails the page mark's off-page check.
    check = _mark_check(verify_bytes(data, [page]))
    assert check.status == "fail"
    assert "off the page" in check.message
