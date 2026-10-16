import type { PageText, Rect, TextLine } from "../types";
import { directionAngle, distance, type Point, union } from "./geometry";

/** A position between characters: before `chars[index]` of `lines[line]`. */
export interface Caret {
  line: number;
  index: number;
}

/** Characters [start, end) of one line. */
export interface LineRange {
  line: number;
  start: number;
  end: number;
}

export interface TextSelection {
  rects: Rect[];
  text: string;
  /** Display-space writing angle of most of the selected text, if axis-aligned. */
  angle?: number;
}

const isSpace = (c: string) => c.trim() === "";
const LEADING_PUNCTUATION = new Set([..."([{<\"'“‘«"]);
const TRAILING_PUNCTUATION = new Set([...".,;:!?)]}>\"'”’»"]);

function centreAlong(line: TextLine, i: number): number {
  const b = line.boxes[i];
  return ((b[0] + b[2]) / 2) * line.dir[0] + ((b[1] + b[3]) / 2) * line.dir[1];
}

/**
 * How far `p` is from a line, mostly across it: dragging past the end of a line should stay on
 * that line rather than jump to a longer neighbour.
 */
function lineScore(line: TextLine, p: Point): number {
  const [x0, y0, x1, y1] = line.bbox;
  const outX = Math.max(x0 - p.x, 0, p.x - x1);
  const outY = Math.max(y0 - p.y, 0, p.y - y1);
  const horizontal = Math.abs(line.dir[0]) >= Math.abs(line.dir[1]);
  return horizontal ? outY + 0.1 * outX : outX + 0.1 * outY;
}

/** Index of the line nearest to `p`; among lines containing it, the smallest. */
export function nearestLine(lines: TextLine[], p: Point): number | null {
  let best: number | null = null;
  let bestScore = Infinity;
  let bestArea = Infinity;
  lines.forEach((line, i) => {
    const d = lineScore(line, p);
    const area = (line.bbox[2] - line.bbox[0]) * (line.bbox[3] - line.bbox[1]);
    if (d < bestScore - 1e-6 || (Math.abs(d - bestScore) <= 1e-6 && area < bestArea)) {
      best = i;
      bestScore = d;
      bestArea = area;
    }
  });
  return best;
}

/** Whether `p` is on, or within `slop` points of, any text. */
export function nearText(lines: TextLine[], p: Point, slop: number): boolean {
  return lines.some((line) => distance(line.bbox, p) <= slop);
}

function nearestChar(line: TextLine, p: Point): number {
  const a = p.x * line.dir[0] + p.y * line.dir[1];
  let best = 0;
  let bestDistance = Infinity;
  for (let i = 0; i < line.chars.length; i++) {
    const d = Math.abs(centreAlong(line, i) - a);
    if (d < bestDistance) {
      best = i;
      bestDistance = d;
    }
  }
  return best;
}

export function caretAt(lines: TextLine[], p: Point): Caret | null {
  const li = nearestLine(lines, p);
  if (li === null) return null;
  const line = lines[li];
  const i = nearestChar(line, p);
  const a = p.x * line.dir[0] + p.y * line.dir[1];
  return { line: li, index: a < centreAlong(line, i) ? i : i + 1 };
}

const before = (a: Caret, b: Caret) => a.line < b.line || (a.line === b.line && a.index <= b.index);

/** Line ranges between two carets, in reading order. */
export function rangesBetween(lines: TextLine[], a: Caret, b: Caret): LineRange[] {
  const [from, to] = before(a, b) ? [a, b] : [b, a];
  const ranges: LineRange[] = [];
  for (let li = from.line; li <= to.line; li++) {
    const start = li === from.line ? from.index : 0;
    const end = li === to.line ? to.index : lines[li].chars.length;
    if (end > start) ranges.push({ line: li, start, end });
  }
  return ranges;
}

function trimRange(line: TextLine, { start, end, ...rest }: LineRange): LineRange {
  while (start < end && isSpace(line.chars[start])) start++;
  while (end > start && isSpace(line.chars[end - 1])) end--;
  return { ...rest, start, end };
}

/** The word under `p` (a run of non-space characters, without enclosing punctuation). */
export function wordAt(lines: TextLine[], p: Point, slop: number): LineRange | null {
  const li = nearestLine(lines, p);
  if (li === null || distance(lines[li].bbox, p) > slop) return null;
  const line = lines[li];
  const i = nearestChar(line, p);
  if (isSpace(line.chars[i])) return null;
  let start = i;
  let end = i + 1;
  while (start > 0 && !isSpace(line.chars[start - 1])) start--;
  while (end < line.chars.length && !isSpace(line.chars[end])) end++;
  let s = start;
  let e = end;
  while (s < e && LEADING_PUNCTUATION.has(line.chars[s])) s++;
  while (e > s && TRAILING_PUNCTUATION.has(line.chars[e - 1])) e--;
  return s < e ? { line: li, start: s, end: e } : { line: li, start, end };
}

export function lineAt(lines: TextLine[], p: Point, slop: number): LineRange | null {
  const li = nearestLine(lines, p);
  if (li === null || distance(lines[li].bbox, p) > slop) return null;
  return { line: li, start: 0, end: lines[li].chars.length };
}

/** Mark geometry for the given ranges: one rectangle per line, whitespace trimmed. */
export function selectionFromRanges(lines: TextLine[], ranges: LineRange[]): TextSelection | null {
  const rects: Rect[] = [];
  const parts: string[] = [];
  const votes = new Map<number | undefined, number>();
  for (const range of ranges) {
    const line = lines[range.line];
    const { start, end } = trimRange(line, range);
    if (end <= start) continue;
    const angle = directionAngle(line.dir);
    const boxes = line.boxes.slice(start, end);
    if (angle === undefined) {
      // Slanted text: the union of its boxes would cover neighbouring lines.
      boxes.forEach((box, k) => {
        if (!isSpace(line.chars[start + k])) rects.push(box);
      });
    } else {
      rects.push(union(boxes));
    }
    parts.push(line.chars.slice(start, end).join(""));
    votes.set(angle, (votes.get(angle) ?? 0) + (end - start));
  }
  if (!rects.length) return null;
  const angle = [...votes.entries()].sort((x, y) => y[1] - x[1])[0][0];
  return { rects, text: parts.join(" "), angle };
}

export function selectBetween(text: PageText, a: Caret, b: Caret): TextSelection | null {
  return selectionFromRanges(text.lines, rangesBetween(text.lines, a, b));
}
