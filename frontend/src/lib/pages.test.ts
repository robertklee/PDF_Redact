import { describe, expect, it } from "vitest";
import { formatPages, parsePageRanges } from "./pages";

describe("parsePageRanges", () => {
  it("parses lists, ranges and keywords", () => {
    expect(parsePageRanges("1, 4-6", 10).pages).toEqual([0, 3, 4, 5]);
    expect(parsePageRanges("3 - 4  8", 10).pages).toEqual([2, 3, 7]);
    expect(parsePageRanges("8-, -2", 10).pages).toEqual([0, 1, 7, 8, 9]);
    expect(parsePageRanges("odd", 5).pages).toEqual([0, 2, 4]);
    expect(parsePageRanges("even", 5).pages).toEqual([1, 3]);
    expect(parsePageRanges("all", 3).pages).toEqual([0, 1, 2]);
    expect(parsePageRanges("2–3", 3).pages).toEqual([1, 2]);
  });

  it("rejects invalid input", () => {
    expect(parsePageRanges("", 3).error).toBeDefined();
    expect(parsePageRanges("0", 3).error).toMatch(/from 1/);
    expect(parsePageRanges("4", 3).error).toMatch(/3 pages/);
    expect(parsePageRanges("3-1", 3).error).toMatch(/reversed/);
    expect(parsePageRanges("a", 3).error).toMatch(/not a page/);
    expect(parsePageRanges("-", 3).error).toMatch(/not a page/);
  });
});

describe("formatPages", () => {
  it("compacts runs", () => {
    expect(formatPages([5, 0, 1, 2, 9])).toBe("1–3, 6, 10");
    expect(formatPages([])).toBe("");
  });
});
