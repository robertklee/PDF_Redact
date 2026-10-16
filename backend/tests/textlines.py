"""Synthetic page-text payloads (as served by /pages/{n}/text) for search tests."""

from __future__ import annotations

CHAR_W = 6.0
LINE_H = 14.0


def make_lines(*texts: str, x: float = 72, y: float = 100, direction=(1, 0)) -> list[dict]:
    """One line per string, monospaced, left to right (or top to bottom if direction=(0, 1))."""
    lines = []
    for i, text in enumerate(texts):
        boxes = []
        for k, _ in enumerate(text):
            if direction == (1, 0):
                x0, y0 = x + k * CHAR_W, y + i * LINE_H
                boxes.append([x0, y0, x0 + CHAR_W, y0 + 10])
            else:
                x0, y0 = x - i * LINE_H, y + k * CHAR_W
                boxes.append([x0, y0, x0 + 10, y0 + CHAR_W])
        lines.append(
            {
                "bbox": [
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                ],
                "chars": list(text),
                "boxes": boxes,
                "dir": list(direction),
            }
        )
    return lines
