import { create } from "zustand";
import { api } from "./api";
import { parseKeywords, searchMode } from "./lib/search";
import type { CustomPattern, Detector, SearchMatch } from "./types";

export type SidebarTab = "marks" | "search";
export type SearchKind = "text" | "detect";
export type Scope = "all" | "current" | "range";

const SETTINGS_KEY = "pdf-redact-detect";

/** Search form fields. */
export interface SearchForm {
  kind: SearchKind;
  query: string;
  wholeWord: boolean;
  caseSensitive: boolean;
  regex: boolean;
  scope: Scope;
  range: string;
  /** Enabled detectors; null until the user changes them (then the detectors' defaults apply). */
  categories: string[] | null;
  /** Keywords, one per line. Kept in memory only, since they are often names. */
  keywords: string;
  patterns: CustomPattern[];
}

interface Saved {
  categories: string[] | null;
  patterns: CustomPattern[];
}

function loadSaved(): Saved {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "null");
    const categories = Array.isArray(saved?.categories)
      ? saved.categories.filter((c: unknown) => typeof c === "string")
      : null;
    const patterns = Array.isArray(saved?.patterns)
      ? saved.patterns
          .filter((p: CustomPattern) => typeof p?.name === "string" && typeof p?.pattern === "string")
          .map(({ name, pattern }: CustomPattern) => ({ name, pattern }))
      : [];
    return { categories, patterns };
  } catch {
    return { categories: null, patterns: [] };
  }
}

function save(saved: Saved) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(saved));
  } catch {
    /* storage unavailable */
  }
}

interface SearchState extends SearchForm {
  tab: SidebarTab;
  detectors: Detector[] | null;

  status: "idle" | "running" | "done";
  error: string | null;
  hits: SearchMatch[];
  truncated: boolean;
  /** Kind of the search that produced the hits. */
  resultKind: SearchKind;
  /** Indexes of hits ticked for marking. */
  checked: Set<number>;
  /** Hit last jumped to, highlighted on the page. */
  active: number | null;
  seq: number;

  update(patch: Partial<SearchForm>): void;
  setTab(tab: SidebarTab): void;
  loadDetectors(): Promise<void>;
  /** Detectors that will run: the user's choice, or the defaults. */
  enabledCategories(): string[];
  run(documentId: string, pages?: number[]): Promise<void>;
  setChecked(indexes: number[], checked: boolean): void;
  setActive(index: number | null): void;
  clearResults(): void;
}

const emptyResults = {
  status: "idle" as const,
  error: null,
  hits: [],
  truncated: false,
  checked: new Set<number>(),
  active: null,
};

export const useSearch = create<SearchState>()((set, get) => ({
  kind: "text",
  query: "",
  wholeWord: false,
  caseSensitive: false,
  regex: false,
  scope: "all",
  range: "",
  keywords: "",
  ...loadSaved(),
  tab: "marks",
  detectors: null,
  resultKind: "text",
  seq: 0,
  ...emptyResults,

  update(patch) {
    set(patch);
    if ("categories" in patch || "patterns" in patch) {
      const { categories, patterns } = get();
      save({ categories, patterns });
    }
  },

  setTab(tab) {
    set({ tab });
  },

  async loadDetectors() {
    if (get().detectors) return;
    try {
      set({ detectors: await api.detectors() });
    } catch {
      /* shown as an error when searching */
    }
  },

  enabledCategories() {
    const { categories, detectors } = get();
    const known = detectors?.map((d) => d.id) ?? [];
    if (categories) return categories.filter((c) => known.includes(c));
    return detectors?.filter((d) => d.default).map((d) => d.id) ?? [];
  },

  async run(documentId, pages) {
    const seq = get().seq + 1;
    const form = get();
    set({ seq, status: "running", error: null });
    try {
      let response;
      if (form.kind === "text") {
        response = await api.search(documentId, {
          query: form.query,
          mode: searchMode(form),
          caseSensitive: form.caseSensitive,
          pages,
        });
      } else {
        const categories = form.enabledCategories();
        const keywords = parseKeywords(form.keywords);
        const patterns = form.patterns.filter((p) => p.name.trim() && p.pattern);
        if (!categories.length && !keywords.length && !patterns.length) {
          throw new Error("Choose at least one kind of information, keyword or pattern to find.");
        }
        response = await api.detect(documentId, { categories, keywords, patterns, pages });
      }
      if (get().seq !== seq) return;
      set({
        status: "done",
        hits: response.matches,
        truncated: response.truncated,
        resultKind: form.kind,
        checked: new Set(response.matches.map((_, i) => i)),
        active: null,
      });
    } catch (err) {
      if (get().seq !== seq) return;
      set({ ...emptyResults, error: err instanceof Error ? err.message : String(err) });
    }
  },

  setChecked(indexes, checked) {
    const next = new Set(get().checked);
    for (const i of indexes) {
      if (checked) next.add(i);
      else next.delete(i);
    }
    set({ checked: next });
  },

  setActive(index) {
    set({ active: index });
  },

  clearResults() {
    set({ ...emptyResults, seq: get().seq + 1 });
  },
}));

/** Show the text search and focus its input (Ctrl/Cmd+F). */
export function openSearch() {
  const search = useSearch.getState();
  search.update({ kind: "text" });
  search.setTab("search");
  requestAnimationFrame(() => {
    const input = document.getElementById("search-query");
    if (input instanceof HTMLInputElement) {
      input.focus();
      input.select();
    }
  });
}
