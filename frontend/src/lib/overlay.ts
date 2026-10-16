import type { Appearance, Rect } from "../types";

// Overlay text is drawn by the server in PDF Helvetica ("helv"); these mirror its metrics and
// fitting rules (backend/pdf_redact/core/redact.py) so the preview matches the output.
export const OVERLAY_LINE_HEIGHT = 1.4;
export const OVERLAY_PADDING = 1;
export const MIN_OVERLAY_FONT_SIZE = 4;
export const MAX_AUTO_FONT_SIZE = 24;
const ASCENDER = 1.075;
const DESCENDER = -0.299;

// Glyph widths per 1000 units, as reported by PyMuPDF for "helv".
// prettier-ignore
const ASCII_WIDTHS = [
  278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556,
  556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667,
  611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
  667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500,
  222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]; // U+0020–U+007E
// prettier-ignore
const LATIN1_WIDTHS = [
  278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333,
  333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667,
  1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778,
  722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556,
  278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556,
  500,
]; // U+00A0–U+00FF
const FALLBACK_WIDTH = 278;

function charWidth(code: number): number {
  if (code >= 0x20 && code <= 0x7e) return ASCII_WIDTHS[code - 0x20];
  if (code >= 0xa0 && code <= 0xff) return LATIN1_WIDTHS[code - 0xa0];
  return FALLBACK_WIDTH;
}

export function textWidth(text: string, size: number): number {
  let units = 0;
  for (const ch of text) units += charWidth(ch.codePointAt(0)!);
  return (units / 1000) * size;
}

/** Characters the overlay font cannot show. */
export function unsupportedChars(text: string): string[] {
  return [...new Set([...text].filter((ch) => {
    const code = ch.codePointAt(0)!;
    return !((code >= 0x20 && code <= 0x7e) || (code >= 0xa0 && code <= 0xff));
  }))];
}

const round2 = (v: number) => Math.round(v * 100) / 100;

/** Largest overlay font size (capped by `requested`) that fits on one line, else null. */
export function fitFontSize(
  text: string,
  width: number,
  height: number,
  requested: number | null,
): number | null {
  const unit = textWidth(text, 1);
  if (unit <= 0) return null;
  const fit = Math.min((width - 2 * OVERLAY_PADDING) / unit, height / OVERLAY_LINE_HEIGHT);
  const size = Math.min(fit, requested ?? MAX_AUTO_FONT_SIZE);
  return size >= MIN_OVERLAY_FONT_SIZE ? round2(size) : null;
}

/** Writing directions in display space, keyed by counter-clockwise angle (y points down). */
const DIRECTIONS: Record<number, [number, number]> = {
  0: [1, 0],
  90: [0, -1],
  180: [-1, 0],
  270: [0, 1],
};

export interface OverlayLayout {
  text: string;
  angle: number;
  size: number;
  /** Baseline start point in display space. */
  x: number;
  y: number;
}

/** Where the server will draw the overlay text of a box, or null if none fits. */
export function overlayLayout(
  rect: Rect,
  appearance: Appearance,
  textAngle?: number,
): OverlayLayout | null {
  const text = appearance.overlayText.trim();
  if (!text) return null;
  const w = rect[2] - rect[0];
  const h = rect[3] - rect[1];
  const fit = (a: number) =>
    a === 0 || a === 180
      ? fitFontSize(text, w, h, appearance.fontSize)
      : fitFontSize(text, h, w, appearance.fontSize);

  let angle: number;
  let size: number | null;
  if (textAngle !== undefined && textAngle in DIRECTIONS) {
    angle = textAngle;
    size = fit(angle);
  } else {
    const horizontal = fit(0);
    const vertical = fit(90);
    // Tall, narrow boxes read better with bottom-to-top text.
    if (vertical && (horizontal === null || vertical > 1.5 * horizontal)) {
      angle = 90;
      size = vertical;
    } else {
      angle = 0;
      size = horizontal;
    }
  }
  if (!size) return null;

  const [dx, dy] = DIRECTIONS[angle];
  const [ux, uy] = [dy, -dx];
  const textW = textWidth(text, size);
  const along = Math.abs(w * dx + h * dy);
  const shift = {
    left: -along / 2 + OVERLAY_PADDING,
    center: -textW / 2,
    right: along / 2 - OVERLAY_PADDING - textW,
  }[appearance.align];
  const drop = (size * (ASCENDER + DESCENDER)) / 2;
  const cx = (rect[0] + rect[2]) / 2;
  const cy = (rect[1] + rect[3]) / 2;
  return {
    text,
    angle,
    size,
    x: cx + dx * shift - ux * drop,
    y: cy + dy * shift - uy * drop,
  };
}
