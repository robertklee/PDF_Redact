import type { Appearance, Mark, OverlayFont, Rect } from "../types";
import metrics from "./fontMetrics.json";

// Overlay text is drawn by the server (backend/pdf_redact/core/overlay.py). This mirrors its layout
// rules with the same font metrics, so the preview matches the output; overlay.test.ts compares
// both against layouts computed by the server. Regenerate fontMetrics.json and the fixtures with
// `python -m tests.overlay_fixtures` (in backend/) after changing the server's layout.
export const LINE_HEIGHT = 1.4;
export const PADDING = 1;
export const MIN_FONT_SIZE = 4;
export const MAX_AUTO_FONT_SIZE = 24;
const REPEAT_SEPARATOR = " ";

interface FontMetrics {
  label: string;
  ascender: number;
  descender: number;
  /** Advance widths in 1/1000 em for U+0020..U+00FF. */
  widths: number[];
}

const FONTS: Record<OverlayFont, FontMetrics> = metrics;

export const FONT_OPTIONS = (Object.keys(FONTS) as OverlayFont[]).map((value) => ({
  value,
  label: FONTS[value].label,
}));

/** Browser fonts that look like the PDF base-14 fonts the server uses. */
export const FONT_FAMILIES: Record<OverlayFont, string> = {
  helv: "Helvetica, Arial, sans-serif",
  tiro: '"Times New Roman", Times, serif',
  cour: '"Courier New", Courier, monospace',
};

/** Drawn in place of characters the fonts cannot show. */
export const MISSING = "\u00b7";

/**
 * Overlay text as it will be drawn: the fonts only cover Latin-1, so other characters become a
 * middle dot, and control characters a space.
 */
export function drawable(text: string): string {
  let out = "";
  for (const ch of text) {
    const code = ch.codePointAt(0)!;
    if ((code >= 0x21 && code <= 0x7e) || (code >= 0xa1 && code <= 0xff)) out += ch;
    else if (code <= 0x20 || (code >= 0x7f && code <= 0xa0)) out += " ";
    else out += MISSING;
  }
  return out.replace(/^ +| +$/g, "");
}

export function textWidth(text: string, size: number, font: OverlayFont = "helv"): number {
  const { widths } = FONTS[font];
  const missing = widths[MISSING.charCodeAt(0) - 0x20];
  let units = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0)!;
    units += code >= 0x20 && code <= 0xff ? widths[code - 0x20] : missing;
  }
  return (units / 1000) * size;
}

/** Characters the overlay fonts cannot show (drawn as a middle dot). */
export function unsupportedChars(text: string): string[] {
  return [...new Set([...text].filter((ch) => ch.codePointAt(0)! > 0xff))];
}

/** Largest font size (capped by `requested`) at which `text` fits on one line, else null. */
export function fitFontSize(
  text: string,
  width: number,
  height: number,
  requested: number | null,
  font: OverlayFont = "helv",
): number | null {
  const unit = textWidth(text, 1, font);
  if (unit <= 0) return null;
  const fit = Math.min((width - 2 * PADDING) / unit, height / LINE_HEIGHT);
  // Round down to 1/100 pt so the text never outgrows the box.
  const size = Math.floor(Math.min(fit, requested ?? MAX_AUTO_FONT_SIZE) * 100 + 1e-6) / 100;
  return size >= MIN_FONT_SIZE ? size : null;
}

/** Writing directions in display space, keyed by counter-clockwise angle (y points down). */
const DIRECTIONS: Record<number, [number, number]> = {
  0: [1, 0],
  90: [0, -1],
  180: [-1, 0],
  270: [0, 1],
};

export interface OverlayLine {
  text: string;
  /** Baseline start point in display space. */
  x: number;
  y: number;
}

export interface OverlayLayout {
  angle: number;
  size: number;
  lines: OverlayLine[];
}

const round2 = (v: number) => Math.round(v * 100) / 100;

/** Where the server will draw the overlay text of a box, or null if there is none or it cannot fit. */
export function overlayLayout(rect: Rect, appearance: Appearance, textAngle?: number): OverlayLayout | null {
  const text = drawable(appearance.overlayText);
  if (!text) return null;
  const { font } = appearance;
  const w = rect[2] - rect[0];
  const h = rect[3] - rect[1];
  const fit = (a: number) =>
    a === 0 || a === 180
      ? fitFontSize(text, w, h, appearance.fontSize, font)
      : fitFontSize(text, h, w, appearance.fontSize, font);

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
  const [along, across] = angle === 0 || angle === 180 ? [w, h] : [h, w];
  let rows = [text];
  if (appearance.repeat) {
    const unit = textWidth(text, size, font);
    const gap = textWidth(REPEAT_SEPARATOR, size, font);
    const perRow = Math.max(1, Math.floor((along - 2 * PADDING + gap) / (unit + gap) + 1e-9));
    const count = Math.max(1, Math.floor(across / (size * LINE_HEIGHT) + 1e-9));
    rows = Array<string>(count).fill(Array<string>(perRow).fill(text).join(REPEAT_SEPARATOR));
  }

  const { ascender, descender } = FONTS[font];
  // Baseline sits below the centre line by half the glyphs' ascender+descender height.
  const drop = (size * (ascender + descender)) / 2;
  const pitch = size * LINE_HEIGHT;
  const cx = (rect[0] + rect[2]) / 2;
  const cy = (rect[1] + rect[3]) / 2;
  const lines = rows.map((row, i) => {
    const width = textWidth(row, size, font);
    const shift = {
      left: -along / 2 + PADDING,
      center: -width / 2,
      right: along / 2 - PADDING - width,
    }[appearance.align];
    const rise = ((rows.length - 1) / 2 - i) * pitch - drop;
    return { text: row, x: round2(cx + dx * shift + ux * rise), y: round2(cy + dy * shift + uy * rise) };
  });
  return { angle, size, lines };
}

/** True if the mark has overlay text that the server will leave out of at least one of its boxes. */
export function overlayDoesNotFit(mark: Mark): boolean {
  if (!drawable(mark.appearance.overlayText)) return false;
  const angle = mark.kind === "text" ? mark.angle : undefined;
  return mark.rects.some((r) => overlayLayout(r, mark.appearance, angle) === null);
}
