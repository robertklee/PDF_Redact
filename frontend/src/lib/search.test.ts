import { describe, expect, it } from "vitest";
import type { Mark, Rect, SearchMatch } from "../types";
import {
  categoryLabel,
  coveredHits,
  groupByPage,
  leadingContext,
  parseDetectList,
  parseKeywords,
  searchMode,
  searchTerms,
  serializeDetectList,
} from "./search";

const hit = (page: number, ...rects: Rect[]): SearchMatch => ({
  page,
  rects,
  text: "x",
  angle: 0,
  before: "",
  after: "",
  category: null,
});

const mark = (page: number, kind: Mark["kind"], ...rects: Rect[]): Mark => ({
  id: `${page}-${kind}-${rects.length}`,
  page,
  kind,
  rects,
  appearance: { fill: "#000000", textColor: "#ffffff", overlayText: "", fontSize: null, align: "center", font: "helv", repeat: false },
  createdAt: "",
});

describe("searchMode", () => {
  it("prefers regex over whole word", () => {
    expect(searchMode({ regex: false, wholeWord: false })).toBe("phrase");
    expect(searchMode({ regex: false, wholeWord: true })).toBe("word");
    expect(searchMode({ regex: true, wholeWord: true })).toBe("regex");
  });
});

describe("coveredHits", () => {
  const hits = [
    hit(0, [10, 10, 50, 20]),
    hit(0, [10, 30, 100, 40], [10, 44, 30, 54]),
    hit(1, [10, 10, 50, 20]),
    hit(2, [0, 0, 5, 5]),
  ];

  it("finds hits inside text and area marks, allowing for rounding", () => {
    const marks = [mark(0, "text", [10.2, 9.8, 50.3, 20]), mark(1, "area", [0, 0, 200, 200])];
    expect(coveredHits(hits, marks)).toEqual(new Set([0, 2]));
  });

  it("needs every rect of a multi-line hit covered", () => {
    expect(coveredHits(hits, [mark(0, "area", [0, 25, 200, 42])])).toEqual(new Set());
    const both = [mark(0, "area", [0, 25, 200, 42]), mark(0, "text", [10, 44, 30, 54])];
    expect(coveredHits(hits, both)).toEqual(new Set([1]));
  });

  it("treats page marks as covering everything on the page", () => {
    expect(coveredHits(hits, [mark(2, "page")])).toEqual(new Set([3]));
  });

  it("ignores partial overlap", () => {
    expect(coveredHits(hits, [mark(0, "area", [20, 0, 200, 200])])).toEqual(new Set());
  });
});

describe("searchTerms", () => {
  it("collects distinct texts of search and detection marks", () => {
    const marks: Mark[] = [
      { ...mark(0, "text", [0, 0, 1, 1]), text: "Jane Doe", source: "search" },
      { ...mark(1, "text", [0, 0, 1, 1]), text: " Jane Doe ", source: "detect" },
      { ...mark(1, "text", [0, 0, 1, 1]), text: "555-0143", source: "detect" },
      { ...mark(2, "text", [0, 0, 1, 1]), text: "selected by hand", source: "manual" },
      { ...mark(2, "text", [0, 0, 1, 1]), text: "legacy mark" },
      { ...mark(3, "text", [0, 0, 1, 1]), text: "  ", source: "search" },
    ];
    expect(searchTerms(marks)).toEqual(["Jane Doe", "555-0143"]);
  });
});

describe("groupByPage", () => {
  it("groups indexes by page in page order", () => {
    const hits = [hit(2), hit(0), hit(2), hit(1)];
    expect(groupByPage(hits)).toEqual([
      [0, [1]],
      [1, [3]],
      [2, [0, 2]],
    ]);
  });
});

describe("categoryLabel", () => {
  const detectors = [{ id: "ssn", label: "Social Security numbers", short: "SSN", description: "", default: true }];

  it("labels detectors, keywords and custom patterns", () => {
    expect(categoryLabel("ssn", detectors)).toBe("SSN");
    expect(categoryLabel("keyword", detectors)).toBe("Keyword");
    expect(categoryLabel("custom:Case no.", detectors)).toBe("Case no.");
    expect(categoryLabel("iban", null)).toBe("iban");
    expect(categoryLabel(null, detectors)).toBe("");
  });
});

describe("parseKeywords", () => {
  it("takes one trimmed phrase per line without duplicates", () => {
    expect(parseKeywords("  Jane  Doe \n\nACME\r\njane doe\nacme corp")).toEqual(["Jane Doe", "ACME", "acme corp"]);
  });
});

describe("detect lists", () => {
  it("round-trips", () => {
    const list = { keywords: ["Jane Doe"], patterns: [{ name: "Case", pattern: "C-\\d+" }] };
    expect(parseDetectList(serializeDetectList(list))).toEqual(list);
  });

  it("accepts partial lists and rejects other files", () => {
    expect(parseDetectList('{"keywords": ["a"]}')).toEqual({ keywords: ["a"], patterns: [] });
    expect(() => parseDetectList("nope")).toThrow("not valid JSON");
    expect(() => parseDetectList('{"keywords": [1]}')).toThrow("not a keyword");
    expect(() => parseDetectList('{"patterns": [{"name": "x"}]}')).toThrow("not a keyword");
    expect(() => parseDetectList("[]")).toThrow("not a keyword");
    expect(() => parseDetectList("null")).toThrow("not a keyword");
  });
});

describe("leadingContext", () => {
  it("keeps short context and trims long context at a word", () => {
    expect(leadingContext("SSN: ")).toBe("SSN: ");
    expect(leadingContext("…Jane Q. Doe SSN: 123-45-6789 Phone: ", 20)).toBe("…123-45-6789 Phone: ");
    expect(leadingContext("x".repeat(30), 10)).toBe("…xxxxxxxxxx");
  });
});
