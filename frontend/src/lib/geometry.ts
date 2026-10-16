import type { Rect } from "../types";

export interface Point {
  x: number;
  y: number;
}

export function normalize([x0, y0, x1, y1]: Rect): Rect {
  return [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
}

export function fromPoints(a: Point, b: Point): Rect {
  return normalize([a.x, a.y, b.x, b.y]);
}

export function union(rects: Rect[]): Rect {
  return [
    Math.min(...rects.map((r) => r[0])),
    Math.min(...rects.map((r) => r[1])),
    Math.max(...rects.map((r) => r[2])),
    Math.max(...rects.map((r) => r[3])),
  ];
}

export const width = (r: Rect) => r[2] - r[0];
export const height = (r: Rect) => r[3] - r[1];

export function contains(r: Rect, p: Point, tolerance = 0): boolean {
  return (
    p.x >= r[0] - tolerance &&
    p.x <= r[2] + tolerance &&
    p.y >= r[1] - tolerance &&
    p.y <= r[3] + tolerance
  );
}

export function intersects(a: Rect, b: Rect): boolean {
  return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
}

/** Distance from a point to a rectangle (0 inside). */
export function distance(r: Rect, p: Point): number {
  const dx = Math.max(r[0] - p.x, 0, p.x - r[2]);
  const dy = Math.max(r[1] - p.y, 0, p.y - r[3]);
  return Math.hypot(dx, dy);
}

export function translate(r: Rect, dx: number, dy: number): Rect {
  return [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy];
}

/** Move `r` by (dx, dy), limited so that it stays within `bounds` when it fits. */
export function clampedOffset(rects: Rect[], dx: number, dy: number, bounds: Rect): Point {
  const box = union(rects);
  const x = Math.min(Math.max(dx, bounds[0] - box[0]), bounds[2] - box[2]);
  const y = Math.min(Math.max(dy, bounds[1] - box[1]), bounds[3] - box[3]);
  return { x: width(box) > width(bounds) ? dx : x, y: height(box) > height(bounds) ? dy : y };
}

export function clamp(r: Rect, bounds: Rect): Rect {
  return [
    Math.min(Math.max(r[0], bounds[0]), bounds[2]),
    Math.min(Math.max(r[1], bounds[1]), bounds[3]),
    Math.min(Math.max(r[2], bounds[0]), bounds[2]),
    Math.min(Math.max(r[3], bounds[1]), bounds[3]),
  ];
}

/** Resize handles: which edges a handle moves. */
export type Handle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
export const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

export function handlePoint(r: Rect, h: Handle): Point {
  const cx = (r[0] + r[2]) / 2;
  const cy = (r[1] + r[3]) / 2;
  return {
    x: h.includes("w") ? r[0] : h.includes("e") ? r[2] : cx,
    y: h.includes("n") ? r[1] : h.includes("s") ? r[3] : cy,
  };
}

export function resize(r: Rect, h: Handle, p: Point): Rect {
  const next: Rect = [...r];
  if (h.includes("w")) next[0] = p.x;
  if (h.includes("e")) next[2] = p.x;
  if (h.includes("n")) next[1] = p.y;
  if (h.includes("s")) next[3] = p.y;
  return normalize(next);
}

/** Display-space angle (counter-clockwise, 0/90/180/270) of a unit direction, if axis-aligned. */
export function directionAngle([dx, dy]: [number, number]): number | undefined {
  if (dx > 0.999) return 0;
  if (dy < -0.999) return 90;
  if (dx < -0.999) return 180;
  if (dy > 0.999) return 270;
  return undefined;
}

export const round2 = (v: number) => Math.round(v * 100) / 100;

export const roundRect = (r: Rect): Rect => r.map(round2) as Rect;
