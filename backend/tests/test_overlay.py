from __future__ import annotations

import itertools
from dataclasses import replace

import pymupdf
import pytest

from pdf_redact.core.overlay import (
    FONTS,
    LINE_HEIGHT,
    MIN_FONT_SIZE,
    Appearance,
    Layout,
    drawable,
    fit_font_size,
    layout_overlay,
    text_width,
)
from pdf_redact.core.redact import Mark, redact_bytes
from pdf_redact.core.verify import verify_bytes
from tests import corpus
from tests.overlay_fixtures import LIB, expected_files

CODE = Appearance(overlay_text="(b)(6)")
FONT_NAMES = {"helv": "Helvetica", "tiro": "Times-Roman", "cour": "Courier"}


@pytest.mark.skipif(not LIB.is_dir(), reason="frontend sources not available")
def test_generated_frontend_files_are_current() -> None:
    for path, content in expected_files().items():
        assert path.read_text(encoding="utf-8") == content, (
            f"{path.name} is out of date: run `python -m tests.overlay_fixtures`"
        )


def test_fit_font_size() -> None:
    assert fit_font_size("(b)(6)", 100, 14, None) == pytest.approx(14 / 1.4, abs=0.01)
    assert fit_font_size("(b)(6)", 100, 100, None) == 24
    assert fit_font_size("(b)(6)", 100, 100, 8) == 8
    assert fit_font_size("(b)(6)", 8, 14, None) is None
    # Courier is wider than Helvetica, so it needs a smaller size in a narrow box.
    assert fit_font_size("(b)(6)", 30, 14, None, "cour") < fit_font_size("(b)(6)", 30, 14, None)


def _line_box(layout: Layout, font: str, index: int) -> pymupdf.Rect:
    """Display-space extent of a laid-out line: advance width x (descender..ascender)."""
    line = layout.lines[index]
    metrics = pymupdf.Font(font)
    dx, dy = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}[layout.angle]
    ux, uy = dy, -dx
    width = text_width(line.text, font, layout.size)
    points = [
        (line.x + dx * a + ux * b, line.y + dy * a + uy * b)
        for a in (0, width)
        for b in (metrics.descender * layout.size, metrics.ascender * layout.size)
    ]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))


SIZES = [6, 10, 14, 20, 40, 75, 150, 400]


@pytest.mark.parametrize("font", list(FONTS))
@pytest.mark.parametrize("repeat", [False, True])
def test_layout_is_legible_and_inside_the_box(font: str, repeat: bool) -> None:
    for (w, h), angle, align, text in itertools.product(
        itertools.product(SIZES, SIZES),
        [None, 0, 90, 180, 270],
        ["left", "center", "right"],
        ["(b)(6)", "(b)(6), (b)(7)(C)", "Withheld"],
    ):
        rect = pymupdf.Rect(20, 30, 20 + w, 30 + h)
        appearance = replace(CODE, overlay_text=text, font=font, repeat=repeat, align=align)
        layout = layout_overlay(rect, appearance, angle)
        if layout is None:
            continue
        assert layout.size >= MIN_FONT_SIZE
        rows = len(layout.lines)
        across = h if layout.angle in (0, 180) else w
        assert rows * layout.size * LINE_HEIGHT <= across + 1e-6
        for i, line in enumerate(layout.lines):
            assert text in line.text
            box = _line_box(layout, font, i)
            assert (rect + (-0.01, -0.01, 0.01, 0.01)).contains(box), (w, h, angle, align, line)
        if not repeat:
            assert rows == 1


def test_repeat_fills_the_box() -> None:
    rect = pymupdf.Rect(0, 0, 300, 200)
    layout = layout_overlay(rect, replace(CODE, repeat=True, font_size=10), None)
    assert layout is not None and layout.size == 10
    assert len(layout.lines) == int(200 / 14)
    copies = layout.lines[0].text.count("(b)(6)")
    unit, gap = text_width("(b)(6)", "helv", 10), text_width(" ", "helv", 10)
    assert copies * unit + (copies - 1) * gap <= 298 < (copies + 1) * unit + copies * gap
    # Rows are evenly spaced and centred as a block.
    ys = [line.y for line in layout.lines]
    assert {round(b - a, 2) for a, b in itertools.pairwise(ys)} == {14.0}


def _overlay_spans(out: bytes, needle: str) -> tuple[pymupdf.Page, list[dict]]:
    doc = pymupdf.open(stream=out, filetype="pdf")
    page = doc[0]
    spans = [
        span
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
        if needle in span["text"]
    ]
    return page, spans


@pytest.mark.parametrize("rotation", [0, 90, 270])
@pytest.mark.parametrize("font", list(FONTS))
def test_repeated_overlay_in_output(rotation: int, font: str) -> None:
    data = corpus.rotated(rotation)
    region = (40.0, 40.0, 260.0, 120.0)
    appearance = replace(CODE, overlay_text="(k)(5)", repeat=True, font=font, align="left")
    mark = Mark("a1", 0, "area", [region], appearance)
    out, stats = redact_bytes(data, [mark])
    assert stats.overlays_skipped == []
    assert verify_bytes(out, [mark]).passed

    layout = layout_overlay(region, appearance, None)
    assert layout is not None and len(layout.lines) > 1
    page, spans = _overlay_spans(out, "(k)(5)")
    expected = sum(line.text.count("(k)(5)") for line in layout.lines)
    assert sum(s["text"].count("(k)(5)") for s in spans) == expected
    for span in spans:
        assert span["font"] == FONT_NAMES[font]
        assert span["size"] == pytest.approx(layout.size, abs=0.01)
        shown = pymupdf.Rect(span["bbox"]) * page.rotation_matrix
        assert (pymupdf.Rect(region) + (-0.5, -0.5, 0.5, 0.5)).contains(shown), (span, shown)
    # Each row starts where the layout put it.
    origins = sorted(
        tuple(round(c, 1) for c in pymupdf.Point(s["origin"]) * page.rotation_matrix) for s in spans
    )
    assert origins == sorted((round(line.x, 1), round(line.y, 1)) for line in layout.lines)


def test_drawable_text() -> None:
    assert drawable("  (b)(6) ") == "(b)(6)"
    assert drawable("Café – ✓\u00a0x") == "Café \u00b7 \u00b7 x"
    assert drawable("a\nb\x85c\td") == "a b c d"
    assert drawable(" \u2028 ") == "\u00b7"
    assert drawable("\x00 \x9f") == ""
    assert drawable("😀") == "\u00b7"


@pytest.mark.parametrize("font", list(FONTS))
def test_text_width_counts_every_character(font: str) -> None:
    text = "Ünïcødé (b)(6)"
    assert text_width(text, font, 10) == pytest.approx(sum(text_width(c, font, 10) for c in text))
    assert text_width("é", font, 1000) == pytest.approx(
        pymupdf.get_text_length("é", fontname=font, fontsize=1000), abs=0.5
    )


@pytest.mark.parametrize("font", list(FONTS))
def test_latin1_overlay_in_output(font: str) -> None:
    blank = pymupdf.open()
    blank.new_page()
    data = blank.tobytes()
    region = (40.0, 40.0, 300.0, 70.0)
    appearance = replace(CODE, overlay_text="Ünïcødé – (b)(6) ✓", font=font, align="left")
    mark = Mark("a1", 0, "area", [region], appearance)
    out, stats = redact_bytes(data, [mark])
    assert stats.overlays_skipped == []
    assert verify_bytes(out, [mark]).passed

    layout = layout_overlay(region, appearance, None)
    assert layout is not None
    (line,) = layout.lines
    assert line.text == "Ünïcødé \u00b7 (b)(6) \u00b7"
    doc = pymupdf.open(stream=out, filetype="pdf")
    chars = [
        c
        for block in doc[0].get_text("rawdict")["blocks"]
        for tl in block.get("lines", [])
        for span in tl["spans"]
        if span["font"] == FONT_NAMES[font]
        for c in span["chars"]
    ]
    assert "".join(c["c"] for c in chars) == line.text
    drawn = chars[-1]["bbox"][2] - chars[0]["origin"][0]
    assert drawn == pytest.approx(text_width(line.text, font, layout.size), abs=0.05)


def test_overlay_that_does_not_fit_is_reported() -> None:
    data = corpus.text_basic()
    tiny = Mark("tiny", 0, "area", [(10, 10, 16, 16)], replace(CODE))
    blank = Mark("blank", 0, "area", [(10, 30, 16, 36)], replace(CODE, overlay_text=" "))
    roomy = Mark("roomy", 0, "area", [(10, 50, 200, 80)], replace(CODE))
    _, stats = redact_bytes(data, [tiny, blank, roomy])
    assert stats.overlays_skipped == ["tiny"]
