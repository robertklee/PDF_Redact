import { describe, expect, it } from "vitest";
import type { Align, Rect } from "../types";
import { fitFontSize, overlayLayout, textWidth, unsupportedChars } from "./overlay";

// Reference values computed by the server's overlay code (pdf_redact.core.redact).
const SERVER: [string, Rect, Align, number | null, number | undefined, number, number, number, number][] = [
  ["REDACTED", [100, 200, 300, 220], "center", null, undefined, 0, 14.29, 160.702, 215.545],
  ["(b)(6)", [50, 50, 70, 250], "center", null, undefined, 90, 14.29, 65.545, 167.462],
  ["(b)(6)", [50, 50, 70, 250], "left", 10, 270, 270, 10, 56.12, 51.0],
  ["Withheld", [10, 10, 60, 22], "right", null, 180, 180, 8.57, 44.337, 12.675],
];

describe("overlayLayout", () => {
  it.each(SERVER)("matches the server for %s in %j (%s)", (text, rect, align, fontSize, textAngle, angle, size, x, y) => {
    const layout = overlayLayout(rect, { fill: "#000000", textColor: "#ffffff", overlayText: text, fontSize, align }, textAngle);
    expect(layout).not.toBeNull();
    expect(layout!.angle).toBe(angle);
    expect(layout!.size).toBeCloseTo(size, 2);
    expect(layout!.x).toBeCloseTo(x, 2);
    expect(layout!.y).toBeCloseTo(y, 2);
  });

  it("returns null when the text does not fit or is blank", () => {
    const appearance = { fill: "#000000", textColor: "#ffffff", overlayText: "X", fontSize: null, align: "center" as const };
    expect(overlayLayout([0, 0, 3, 3], appearance)).toBeNull();
    expect(overlayLayout([0, 0, 300, 300], { ...appearance, overlayText: "  " })).toBeNull();
  });
});

describe("fonts", () => {
  it("measures Helvetica", () => {
    expect(textWidth("Hi", 10)).toBeCloseTo(7.22 + 2.22, 5);
    expect(fitFontSize("Hi", 100, 100, 12)).toBe(12);
  });

  it("reports characters outside Latin-1", () => {
    expect(unsupportedChars("Café € 中 €")).toEqual(["€", "中"]);
  });
});
