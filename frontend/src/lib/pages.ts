export type PageRangeResult = { pages: number[]; error?: undefined } | { pages?: undefined; error: string };

/**
 * Parse a page list such as "1, 4-7, 10-" (1-based, inclusive) into sorted 0-based indices.
 * Also accepts "all", "odd" and "even", and open ranges like "-3" or "8-".
 */
export function parsePageRanges(input: string, pageCount: number): PageRangeResult {
  const tokens = input
    .toLowerCase()
    .replace(/[–—]/g, "-")
    .replace(/\s*-\s*/g, "-")
    .split(/[\s,;]+/)
    .filter(Boolean);
  if (!tokens.length) return { error: "Enter one or more pages, for example 1, 4-7" };

  const pages = new Set<number>();
  const add = (from: number, to: number, step = 1) => {
    for (let p = from; p <= to; p += step) pages.add(p - 1);
  };
  for (const token of tokens) {
    if (token === "all") add(1, pageCount);
    else if (token === "odd") add(1, pageCount, 2);
    else if (token === "even") add(2, pageCount, 2);
    else {
      const m = /^(\d*)(-?)(\d*)$/.exec(token);
      if (!m || (!m[1] && !m[3]) || (!m[2] && !m[1])) return { error: `"${token}" is not a page or range` };
      const from = m[1] ? Number(m[1]) : 1;
      const to = m[2] ? (m[3] ? Number(m[3]) : pageCount) : from;
      if (from < 1 || to < 1) return { error: "Pages are numbered from 1" };
      if (from > pageCount || to > pageCount) {
        return {
          error: `Page ${Math.max(from, to)} does not exist; the document has ${pageCount} page${pageCount === 1 ? "" : "s"}`,
        };
      }
      if (from > to) return { error: `"${token}" is a reversed range` };
      add(from, to);
    }
  }
  return { pages: [...pages].sort((a, b) => a - b) };
}

/** Compact 1-based description of 0-based pages, e.g. [0,1,2,5] → "1–3, 6". */
export function formatPages(pages: number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    parts.push(j === i ? `${sorted[i] + 1}` : `${sorted[i] + 1}–${sorted[j] + 1}`);
    i = j + 1;
  }
  return parts.join(", ");
}
