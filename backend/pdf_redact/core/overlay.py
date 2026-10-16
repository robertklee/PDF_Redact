"""Overlay text: appearance settings and where the text goes inside a redaction box.

The UI preview mirrors the layout in ``frontend/src/lib/overlay.ts``. It reads font metrics from a
file generated from this module and is tested against layouts computed here; regenerate both with
``python -m tests.overlay_fixtures`` after changing the layout rules or fonts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import pymupdf

Color = tuple[float, float, float]
FontName = Literal["helv", "tiro", "cour"]
Align = Literal["left", "center", "right"]

# PDF base-14 fonts: always available to viewers, nothing is embedded.
FONTS: dict[str, str] = {"helv": "Helvetica", "tiro": "Times", "cour": "Courier"}
_FONT_OBJECTS = {name: pymupdf.Font(name) for name in FONTS}

# Line pitch as a multiple of the font size, which also leaves a little room around one line.
LINE_HEIGHT = 1.4
PADDING = 1.0
MIN_FONT_SIZE = 4.0
MAX_AUTO_FONT_SIZE = 24.0
REPEAT_SEPARATOR = " "

# Writing directions in display space, keyed by counter-clockwise angle (y points down).
DIRECTIONS: dict[int, tuple[float, float]] = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}


@dataclass
class Appearance:
    fill: Color | None = (0.0, 0.0, 0.0)
    text_color: Color = (1.0, 1.0, 1.0)
    overlay_text: str = ""
    font_size: float | None = None  # None = auto-fit to the box
    align: Align = "center"
    font: FontName = "helv"
    repeat: bool = False  # fill the box with copies of the overlay text


@dataclass
class Line:
    text: str
    x: float  # baseline start, display space
    y: float


@dataclass
class Layout:
    angle: int  # display-space writing angle
    size: float
    lines: list[Line]


# Drawn in place of characters the fonts cannot show (insert_text does the same).
MISSING = "\u00b7"


def drawable(text: str) -> str:
    """Overlay text as it will be drawn: the fonts only cover Latin-1, so other characters become
    a middle dot, and control characters (which insert_text may treat as line breaks) a space."""
    out = []
    for c in text:
        code = ord(c)
        if 0x21 <= code <= 0x7E or 0xA1 <= code <= 0xFF:
            out.append(c)
        elif code <= 0x20 or 0x7F <= code <= 0xA0:
            out.append(" ")
        else:
            out.append(MISSING)
    return "".join(out).strip(" ")


# Advance widths in 1/1000 em for U+0020..U+00FF, measured one character at a time:
# pymupdf.get_text_length skips the character after any non-ASCII one in longer strings.
_WIDTHS = {
    name: [
        round(pymupdf.get_text_length(chr(c), fontname=name, fontsize=1000))
        for c in range(0x20, 0x100)
    ]
    for name in FONTS
}


def text_width(text: str, font: str, size: float) -> float:
    widths = _WIDTHS[font]
    missing = widths[ord(MISSING) - 0x20]
    units = sum(widths[ord(c) - 0x20] if 0x20 <= ord(c) <= 0xFF else missing for c in text)
    return units / 1000 * size


def fit_font_size(
    text: str, width: float, height: float, requested: float | None, font: str = "helv"
) -> float | None:
    """Largest font size (capped by `requested`) at which `text` fits on one line, else None."""
    unit = text_width(text, font, 1)
    if unit <= 0:
        return None
    fit = min((width - 2 * PADDING) / unit, height / LINE_HEIGHT)
    # Round down to 1/100 pt so the text never outgrows the box.
    size = math.floor(min(fit, requested or MAX_AUTO_FONT_SIZE) * 100 + 1e-6) / 100
    return size if size >= MIN_FONT_SIZE else None


def layout_overlay(
    rect: pymupdf.Rect | tuple[float, float, float, float],
    appearance: Appearance,
    angle: int | None = None,
) -> Layout | None:
    """Lines of overlay text for a display-space box, or None if there is none or it cannot fit.

    `angle` is the writing direction of the redacted text; without it, tall narrow boxes get
    bottom-to-top text when that allows a clearly larger font.
    """
    text = drawable(appearance.overlay_text)
    if not text:
        return None
    box = pymupdf.Rect(rect)
    font = appearance.font

    def fit(a: int) -> float | None:
        along, across = (box.width, box.height) if a in (0, 180) else (box.height, box.width)
        return fit_font_size(text, along, across, appearance.font_size, font)

    if angle is not None:
        size = fit(angle)
    else:
        horizontal, vertical = fit(0), fit(90)
        if vertical and (horizontal is None or vertical > 1.5 * horizontal):
            angle, size = 90, vertical
        else:
            angle, size = 0, horizontal
    if size is None:
        return None

    dx, dy = DIRECTIONS[angle]
    ux, uy = dy, -dx  # "up" for the text
    along, across = (box.width, box.height) if angle in (0, 180) else (box.height, box.width)
    rows = [text]
    if appearance.repeat:
        unit, gap = text_width(text, font, size), text_width(REPEAT_SEPARATOR, font, size)
        per_row = max(1, math.floor((along - 2 * PADDING + gap) / (unit + gap) + 1e-9))
        count = max(1, math.floor(across / (size * LINE_HEIGHT) + 1e-9))
        rows = [REPEAT_SEPARATOR.join([text] * per_row)] * count

    metrics = _FONT_OBJECTS[font]
    # Baseline sits below the centre line by half the glyphs' ascender+descender height.
    drop = size * (metrics.ascender + metrics.descender) / 2
    pitch = size * LINE_HEIGHT
    cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    lines = []
    for i, row in enumerate(rows):
        width = text_width(row, font, size)
        shift = {
            "left": -along / 2 + PADDING,
            "center": -width / 2,
            "right": along / 2 - PADDING - width,
        }[appearance.align]
        rise = ((len(rows) - 1) / 2 - i) * pitch - drop
        x = cx + dx * shift + ux * rise
        y = cy + dy * shift + uy * rise
        lines.append(Line(row, round(x, 2), round(y, 2)))
    return Layout(angle, size, lines)


def font_metrics() -> dict:
    """Metrics the UI needs to lay out overlay text exactly as `layout_overlay` does."""
    out = {}
    for name, label in FONTS.items():
        font = _FONT_OBJECTS[name]
        out[name] = {
            "label": label,
            "ascender": round(font.ascender, 4),
            "descender": round(font.descender, 4),
            "widths": _WIDTHS[name],
        }
    return out
