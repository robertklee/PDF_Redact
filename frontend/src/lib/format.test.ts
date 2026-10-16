import { describe, expect, it } from "vitest";
import type { Mark } from "../types";
import { DEFAULT_APPEARANCE } from "../marks";
import { describeMark, formatBytes, plural } from "./format";

const mark = (over: Partial<Mark>): Mark => ({
  id: "m",
  page: 0,
  kind: "area",
  rects: [[10, 20, 110.4, 70]],
  appearance: DEFAULT_APPEARANCE,
  createdAt: "",
  ...over,
});

describe("format", () => {
  it("describes marks", () => {
    expect(describeMark(mark({}))).toBe("100 × 50 pt");
    expect(describeMark(mark({ kind: "page" }))).toBe("Whole page");
    expect(describeMark(mark({ kind: "text", text: "a\n  b" }))).toBe("“a b”");
    expect(describeMark(mark({ kind: "text", text: "x".repeat(70) }))).toBe(`“${"x".repeat(60)}…”`);
  });

  it("formats counts and sizes", () => {
    expect(plural(1, "mark")).toBe("1 mark");
    expect(plural(2, "check")).toBe("2 checks");
    expect(plural(3, "glyph", "glyphs")).toBe("3 glyphs");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});
