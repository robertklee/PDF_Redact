import { describe, expect, it } from "vitest";
import { DEFAULT_APPEARANCE } from "../marks";
import type { Appearance, Rect } from "../types";
import fixtures from "./overlay.fixtures.json";
import { FONT_OPTIONS, drawable, fitFontSize, overlayLayout, textWidth, unsupportedChars } from "./overlay";

interface Fixture {
  name: string;
  rect: number[];
  appearance: Pick<Appearance, "overlayText" | "fontSize" | "align" | "font" | "repeat">;
  angle: number | null;
  layout: { angle: number; size: number; lines: { text: string; x: number; y: number }[] } | null;
}

describe("overlayLayout", () => {
  // Layouts computed by the server (backend/tests/overlay_fixtures.py).
  it.each((fixtures as Fixture[]).map((f) => [f.name, f] as const))("matches the server: %s", (_, f) => {
    const layout = overlayLayout(f.rect as Rect, { ...DEFAULT_APPEARANCE, ...f.appearance }, f.angle ?? undefined);
    if (f.layout === null) {
      expect(layout).toBeNull();
      return;
    }
    expect(layout).not.toBeNull();
    expect(layout!.angle).toBe(f.layout.angle);
    expect(layout!.size).toBe(f.layout.size);
    expect(layout!.lines.map((l) => l.text)).toEqual(f.layout.lines.map((l) => l.text));
    layout!.lines.forEach((line, i) => {
      expect(line.x).toBeCloseTo(f.layout!.lines[i].x, 1);
      expect(line.y).toBeCloseTo(f.layout!.lines[i].y, 1);
    });
  });

  it("covers every font and repeat", () => {
    const cases = fixtures as Fixture[];
    for (const { value } of FONT_OPTIONS) expect(cases.some((f) => f.appearance.font === value)).toBe(true);
    expect(cases.some((f) => f.appearance.repeat && (f.layout?.lines.length ?? 0) > 1)).toBe(true);
  });
});

describe("fonts", () => {
  it("measures each font", () => {
    expect(textWidth("Hi", 10)).toBeCloseTo(7.22 + 2.22, 5);
    expect(textWidth("Hi", 10, "tiro")).toBeCloseTo(7.22 + 2.78, 5);
    expect(textWidth("Hi", 10, "cour")).toBeCloseTo(12, 5);
    expect(fitFontSize("Hi", 100, 100, 12)).toBe(12);
  });

  it("rounds sizes down so text never outgrows its box", () => {
    const size = fitFontSize("(b)(6)", 30, 100, null)!;
    expect(textWidth("(b)(6)", size)).toBeLessThanOrEqual(28);
  });

  it("measures characters it cannot show as the middle dot drawn instead", () => {
    expect(textWidth("中", 10)).toBeCloseTo(textWidth("\u00b7", 10), 5);
  });

  it("draws only what the fonts can show, like the server", () => {
    expect(drawable("  (b)(6) ")).toBe("(b)(6)");
    expect(drawable("Café – ✓\u00a0x")).toBe("Café \u00b7 \u00b7 x");
    expect(drawable("a\nb\x85c\td")).toBe("a b c d");
    expect(drawable(" \u2028 ")).toBe("\u00b7");
    expect(drawable("\x00 \x9f")).toBe("");
    expect(drawable("😀")).toBe("\u00b7");
  });

  it("reports characters outside Latin-1", () => {
    expect(unsupportedChars("Café € 中 €")).toEqual(["€", "中"]);
  });
});
