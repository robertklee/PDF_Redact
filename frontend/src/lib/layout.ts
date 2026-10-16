import type { PageInfo } from "../types";

export const PAGE_GAP = 16;
export const PAGE_PADDING = 24;

export interface Layout {
  tops: number[];
  heights: number[];
  widths: number[];
  /** Total scroll height. */
  height: number;
  /** Widest page plus padding. */
  width: number;
}

export function computeLayout(pages: PageInfo[], zoom: number): Layout {
  const tops: number[] = [];
  const heights: number[] = [];
  const widths: number[] = [];
  let y = PAGE_PADDING;
  let widest = 0;
  for (const page of pages) {
    tops.push(y);
    heights.push(page.height * zoom);
    widths.push(page.width * zoom);
    widest = Math.max(widest, page.width * zoom);
    y += page.height * zoom + PAGE_GAP;
  }
  return {
    tops,
    heights,
    widths,
    height: pages.length ? y - PAGE_GAP + PAGE_PADDING : 0,
    width: widest + 2 * PAGE_PADDING,
  };
}

/** Index of the page at vertical offset `y` (the nearest one when `y` falls in a gap). */
export function pageAt(layout: Layout, y: number): number {
  const { tops, heights } = layout;
  if (!tops.length) return 0;
  let lo = 0;
  let hi = tops.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (tops[mid] <= y) lo = mid;
    else hi = mid - 1;
  }
  // In the gap below page `lo`? Pick whichever page edge is closer.
  if (lo + 1 < tops.length && y > tops[lo] + heights[lo]) {
    return y - (tops[lo] + heights[lo]) < tops[lo + 1] - y ? lo : lo + 1;
  }
  return lo;
}

/** Inclusive range of pages intersecting [y0, y1]. */
export function pagesInRange(layout: Layout, y0: number, y1: number): [number, number] {
  if (!layout.tops.length) return [0, -1];
  return [pageAt(layout, y0), pageAt(layout, y1)];
}

/** Zoom that fits the widest page (or the given page entirely) into the viewport. */
export function fitZoom(
  pages: PageInfo[],
  mode: "width" | "page",
  viewWidth: number,
  viewHeight: number,
  page = 0,
): number {
  const available = viewWidth - 2 * PAGE_PADDING;
  if (mode === "width") {
    const widest = Math.max(...pages.map((p) => p.width));
    return available / widest;
  }
  const p = pages[page] ?? pages[0];
  return Math.min(available / p.width, (viewHeight - 2 * PAGE_PADDING) / p.height);
}
