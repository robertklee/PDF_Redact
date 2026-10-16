"""Files that keep the UI's overlay preview identical to the engine's output.

Writes ``frontend/src/lib/fontMetrics.json`` (used at runtime) and
``frontend/src/lib/overlay.fixtures.json`` (layouts the frontend tests compare against)::

    python -m tests.overlay_fixtures
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from pdf_redact.core.overlay import Appearance, font_metrics, layout_overlay

LIB = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib"
METRICS_FILE = LIB / "fontMetrics.json"
FIXTURES_FILE = LIB / "overlay.fixtures.json"

LINE = (72.0, 90.0, 160.0, 104.0)  # one line of 12 pt text
AREA = (50.0, 50.0, 350.0, 250.0)
CODE = Appearance(overlay_text="(b)(6)")

# (description, display-space rect, appearance, text angle)
CASES: list[tuple[str, tuple[float, float, float, float], Appearance, int | None]] = [
    ("text line, centred", LINE, CODE, 0),
    ("text line, left", LINE, replace(CODE, align="left"), 0),
    ("text line, right", LINE, replace(CODE, align="right"), 0),
    ("Times", LINE, replace(CODE, font="tiro"), 0),
    ("Courier", LINE, replace(CODE, font="cour"), 0),
    ("several codes", AREA, replace(CODE, overlay_text="(b)(6), (b)(7)(C)", font="tiro"), None),
    ("area, auto size capped", AREA, CODE, None),
    ("requested size", AREA, replace(CODE, font_size=10), None),
    ("requested size too large", LINE, replace(CODE, font_size=40), 0),
    ("tall narrow box turns text", (10.0, 10.0, 30.0, 200.0), CODE, None),
    ("text written downwards", (100.0, 50.0, 114.0, 150.0), CODE, 270),
    ("upside-down text", LINE, CODE, 180),
    ("small box turns text", (0.0, 0.0, 8.0, 14.0), CODE, None),
    ("too small", (0.0, 0.0, 6.0, 6.0), CODE, None),
    ("blank text", LINE, replace(CODE, overlay_text="   "), 0),
    ("Latin-1 and fallback characters", AREA, replace(CODE, overlay_text="Ünïcødé — ✓"), None),
    ("repeat in an area", AREA, replace(CODE, repeat=True), None),
    ("repeat, 10 pt, left", AREA, replace(CODE, repeat=True, font_size=10, align="left"), None),
    ("repeat, Courier, right", AREA, replace(CODE, repeat=True, font="cour", align="right"), None),
    ("repeat along a text line", (72.0, 90.0, 300.0, 104.0), replace(CODE, repeat=True), 0),
    ("repeat, vertical", (10.0, 10.0, 30.0, 200.0), replace(CODE, repeat=True), None),
    ("repeat, one copy only", (0.0, 0.0, 40.0, 14.0), replace(CODE, repeat=True), 0),
]

_APPEARANCE_KEYS = {
    "overlay_text": "overlayText",
    "font_size": "fontSize",
    "align": "align",
    "font": "font",
    "repeat": "repeat",
}


def fixtures() -> list[dict]:
    out = []
    for name, rect, appearance, angle in CASES:
        layout = layout_overlay(rect, appearance, angle)
        out.append(
            {
                "name": name,
                "rect": list(rect),
                "appearance": {
                    camel: getattr(appearance, key) for key, camel in _APPEARANCE_KEYS.items()
                },
                "angle": angle,
                "layout": asdict(layout) if layout else None,
            }
        )
    return out


def render(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render_metrics(metrics: dict) -> str:
    """One line per font: the width tables are long and not meant to be read."""
    body = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in metrics.items())
    return "{\n" + body + "\n}\n"


def expected_files() -> dict[Path, str]:
    return {METRICS_FILE: render_metrics(font_metrics()), FIXTURES_FILE: render(fixtures())}


if __name__ == "__main__":
    for path, content in expected_files().items():
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path}")
