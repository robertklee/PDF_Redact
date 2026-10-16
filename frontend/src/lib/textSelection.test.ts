import { describe, expect, it } from "vitest";
import type { Rect, TextLine } from "../types";
import { caretAt, lineAt, nearText, selectBetween, selectionFromRanges, wordAt } from "./textSelection";

/** A horizontal line of 10pt-wide characters starting at (x, y). */
function hline(text: string, x: number, y: number): TextLine {
  const boxes: Rect[] = [...text].map((_, i) => [x + i * 10, y, x + i * 10 + 10, y + 12]);
  return { bbox: [x, y, x + text.length * 10, y + 12], chars: [...text], boxes, dir: [1, 0] };
}

/** A bottom-to-top line (90°) of 10pt-tall characters starting at the bottom (x, y). */
function vline(text: string, x: number, y: number): TextLine {
  const boxes: Rect[] = [...text].map((_, i) => [x, y - i * 10 - 10, x + 12, y - i * 10]);
  return { bbox: [x, y - text.length * 10, x + 12, y], chars: [...text], boxes, dir: [0, -1] };
}

const page = (lines: TextLine[]) => ({ index: 0, width: 600, height: 800, lines, hasText: true, unmappedChars: 0 });

describe("text selection", () => {
  const lines = [hline("Hello world", 100, 100), hline("(secret) data.", 100, 120)];

  it("places carets between characters", () => {
    expect(caretAt(lines, { x: 104, y: 105 })).toEqual({ line: 0, index: 0 });
    expect(caretAt(lines, { x: 106, y: 105 })).toEqual({ line: 0, index: 1 });
    expect(caretAt(lines, { x: 500, y: 105 })).toEqual({ line: 0, index: 11 });
    expect(caretAt(lines, { x: 150, y: 125 })).toEqual({ line: 1, index: 5 });
  });

  it("selects across lines with one trimmed rect per line", () => {
    const sel = selectBetween(page(lines), { line: 1, index: 3 }, { line: 0, index: 5 })!;
    expect(sel.rects).toEqual([
      [160, 100, 210, 112],
      [100, 120, 130, 132],
    ]);
    expect(sel.text).toBe("world (se");
    expect(sel.angle).toBe(0);
  });

  it("returns null for an empty or whitespace-only selection", () => {
    expect(selectBetween(page(lines), { line: 0, index: 5 }, { line: 0, index: 6 })).toBeNull();
    expect(selectBetween(page(lines), { line: 0, index: 2 }, { line: 0, index: 2 })).toBeNull();
  });

  it("finds words without enclosing punctuation", () => {
    const word = wordAt(lines, { x: 135, y: 125 }, 2)!;
    expect(selectionFromRanges(lines, [word])!.text).toBe("secret");
    const last = wordAt(lines, { x: 205, y: 125 }, 2)!;
    expect(selectionFromRanges(lines, [last])!.text).toBe("data");
    expect(wordAt(lines, { x: 155, y: 105 }, 2)).toBeNull(); // the space
    expect(wordAt(lines, { x: 400, y: 400 }, 2)).toBeNull();
  });

  it("selects whole lines", () => {
    const line = lineAt(lines, { x: 120, y: 125 }, 2)!;
    expect(selectionFromRanges(lines, [line])!.text).toBe("(secret) data.");
  });

  it("detects text near a point", () => {
    expect(nearText(lines, { x: 99, y: 99 }, 2)).toBe(true);
    expect(nearText(lines, { x: 90, y: 99 }, 2)).toBe(false);
  });

  it("follows the writing direction of rotated text", () => {
    const rotated = [vline("ABCDEF", 300, 500)];
    // Characters run upwards: A is at the bottom.
    expect(caretAt(rotated, { x: 306, y: 498 })).toEqual({ line: 0, index: 0 });
    expect(caretAt(rotated, { x: 306, y: 478 })).toEqual({ line: 0, index: 2 });
    const sel = selectBetween(page(rotated), { line: 0, index: 1 }, { line: 0, index: 3 })!;
    expect(sel.rects).toEqual([[300, 470, 312, 490]]);
    expect(sel.text).toBe("BC");
    expect(sel.angle).toBe(90);
  });

  it("uses per-character rects for slanted text", () => {
    const slanted: TextLine = { ...hline("ab c", 0, 0), dir: [0.7071, 0.7071] };
    const sel = selectionFromRanges([slanted], [{ line: 0, start: 0, end: 4 }])!;
    expect(sel.rects).toHaveLength(3);
    expect(sel.angle).toBeUndefined();
  });
});
