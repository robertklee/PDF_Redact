import { describe, expect, it } from "vitest";
import type { PageInfo } from "../types";
import { computeLayout, fitZoom, PAGE_GAP, PAGE_PADDING, pageAt, pagesInRange } from "./layout";

const page = (index: number, width = 600, height = 800): PageInfo => ({
  index,
  width,
  height,
  rotation: 0,
});

describe("layout", () => {
  const pages = [page(0), page(1, 800, 600), page(2)];
  const layout = computeLayout(pages, 0.5);

  it("stacks pages with padding and gaps", () => {
    expect(layout.tops).toEqual([PAGE_PADDING, PAGE_PADDING + 400 + PAGE_GAP, PAGE_PADDING + 700 + 2 * PAGE_GAP]);
    expect(layout.height).toBe(PAGE_PADDING * 2 + 400 + 300 + 400 + 2 * PAGE_GAP);
    expect(layout.width).toBe(400 + 2 * PAGE_PADDING);
  });

  it("finds the page at an offset", () => {
    expect(pageAt(layout, 0)).toBe(0);
    expect(pageAt(layout, layout.tops[1] + 10)).toBe(1);
    expect(pageAt(layout, layout.tops[1] - 2)).toBe(1); // in the gap, nearer page 1
    expect(pageAt(layout, layout.tops[0] + layout.heights[0] + 2)).toBe(0);
    expect(pageAt(layout, 1e9)).toBe(2);
    expect(pagesInRange(layout, 0, layout.tops[1] + 1)).toEqual([0, 1]);
  });

  it("handles an empty document", () => {
    const empty = computeLayout([], 1);
    expect(empty.height).toBe(0);
    expect(pagesInRange(empty, 0, 100)).toEqual([0, -1]);
  });

  it("fits width and page", () => {
    expect(fitZoom(pages, "width", 800 + 2 * PAGE_PADDING, 500)).toBe(1);
    expect(fitZoom(pages, "page", 2000, 400 + 2 * PAGE_PADDING, 0)).toBe(0.5);
  });
});
