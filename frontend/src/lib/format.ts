import type { Mark } from "../types";

const EXCERPT_LENGTH = 60;

export const KIND_LABELS = { text: "Text", area: "Area", page: "Page" } as const;

/** Short human description of a mark: its text, its size, or "Whole page". */
export function describeMark(mark: Mark): string {
  if (mark.kind === "page") return "Whole page";
  if (mark.kind === "text") {
    const text = (mark.text ?? "").replace(/\s+/g, " ");
    return text.length > EXCERPT_LENGTH ? `“${text.slice(0, EXCERPT_LENGTH)}…”` : `“${text}”`;
  }
  const [x0, y0, x1, y1] = mark.rects[0];
  return `${Math.round(x1 - x0)} × ${Math.round(y1 - y0)} pt`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
