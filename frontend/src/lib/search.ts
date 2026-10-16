import type { CustomPattern, Detector, Mark, Rect, SearchMatch, SearchMode } from "../types";

/** Slack (points) when deciding whether a mark covers a hit, for rounding differences. */
const COVER_TOLERANCE = 0.5;

export function searchMode({ regex, wholeWord }: { regex: boolean; wholeWord: boolean }): SearchMode {
  return regex ? "regex" : wholeWord ? "word" : "phrase";
}

const inside = (inner: Rect, outer: Rect) =>
  inner[0] >= outer[0] - COVER_TOLERANCE &&
  inner[1] >= outer[1] - COVER_TOLERANCE &&
  inner[2] <= outer[2] + COVER_TOLERANCE &&
  inner[3] <= outer[3] + COVER_TOLERANCE;

/** Indexes of hits that existing marks already cover completely (so applying them redacts the hit). */
export function coveredHits(hits: SearchMatch[], marks: Mark[]): Set<number> {
  const byPage = new Map<number, Mark[]>();
  for (const m of marks) byPage.set(m.page, [...(byPage.get(m.page) ?? []), m]);
  const covered = new Set<number>();
  hits.forEach((hit, i) => {
    const onPage = byPage.get(hit.page);
    if (!onPage) return;
    if (onPage.some((m) => m.kind === "page")) covered.add(i);
    else if (hit.rects.every((r) => onPage.some((m) => m.rects.some((mr) => inside(r, mr))))) covered.add(i);
  });
  return covered;
}

/** Hit indexes grouped by page, in page order. */
export function groupByPage(hits: SearchMatch[]): [number, number[]][] {
  const groups = new Map<number, number[]>();
  hits.forEach((hit, i) => groups.set(hit.page, [...(groups.get(hit.page) ?? []), i]));
  return [...groups.entries()].sort((a, b) => a[0] - b[0]);
}

/** Short label for a detection category. */
export function categoryLabel(category: string | null | undefined, detectors: Detector[] | null): string {
  if (!category) return "";
  if (category === "keyword") return "Keyword";
  if (category.startsWith("custom:")) return category.slice("custom:".length);
  return detectors?.find((d) => d.id === category)?.short ?? category;
}

/** The end of the text before a hit, at most about `max` characters, starting at a word. */
export function leadingContext(before: string, max = 24): string {
  if (before.length <= max) return before;
  const tail = before.slice(-max);
  const space = tail.indexOf(" ");
  return `…${space >= 0 && space < tail.length - 1 ? tail.slice(space + 1) : tail}`;
}

/** One keyword or phrase per line; blank lines and duplicates are dropped. */
export function parseKeywords(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const kw = line.trim().replace(/\s+/g, " ");
    if (kw && !seen.has(kw.toLowerCase())) {
      seen.add(kw.toLowerCase());
      out.push(kw);
    }
  }
  return out;
}

export interface DetectList {
  keywords: string[];
  patterns: CustomPattern[];
}

/** Read a saved keyword/pattern list (as written by `serializeDetectList`). Throws if invalid. */
export function parseDetectList(json: string): DetectList {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    throw new Error("The file is not valid JSON.");
  }
  const obj = data as Partial<Record<keyof DetectList, unknown>>;
  const keywords = obj?.keywords ?? [];
  const patterns = obj?.patterns ?? [];
  if (
    !data ||
    typeof data !== "object" ||
    Array.isArray(data) ||
    !Array.isArray(keywords) ||
    !Array.isArray(patterns) ||
    !keywords.every((k) => typeof k === "string") ||
    !patterns.every(
      (p) => p && typeof p === "object" && typeof p.name === "string" && typeof p.pattern === "string",
    )
  ) {
    throw new Error("The file is not a keyword and pattern list.");
  }
  return {
    keywords: keywords as string[],
    patterns: (patterns as CustomPattern[]).map(({ name, pattern }) => ({ name, pattern })),
  };
}

export function serializeDetectList(list: DetectList): string {
  return JSON.stringify({ app: "pdf-redact", version: 1, ...list }, null, 2);
}
