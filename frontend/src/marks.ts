import { create } from "zustand";
import type { Appearance, Mark, MarkKind, MarkSource, Rect } from "./types";

export type Tool = "select" | "text" | "area";

const HISTORY_LIMIT = 200;
/** Changes with the same key closer together than this form one undo step (typing, dragging). */
const COALESCE_MS = 1000;
const DEFAULTS_KEY = "pdf-redact-defaults";

export const DEFAULT_APPEARANCE: Appearance = {
  fill: "#000000",
  textColor: "#ffffff",
  overlayText: "",
  fontSize: null,
  align: "center",
  font: "helv",
  repeat: false,
};

const HEX = /^#[0-9a-f]{6}$/i;

/** Whether `a` is a complete appearance the server accepts. */
export function isAppearance(a: unknown): a is Appearance {
  if (!a || typeof a !== "object") return false;
  const v = a as Record<string, unknown>;
  return (
    (v.fill === null || (typeof v.fill === "string" && HEX.test(v.fill))) &&
    typeof v.textColor === "string" &&
    HEX.test(v.textColor) &&
    typeof v.overlayText === "string" &&
    v.overlayText.length <= 200 &&
    (v.fontSize === null || (typeof v.fontSize === "number" && v.fontSize >= 4 && v.fontSize <= 72)) &&
    ["left", "center", "right"].includes(v.align as string) &&
    ["helv", "tiro", "cour"].includes(v.font as string) &&
    typeof v.repeat === "boolean"
  );
}

function loadDefaults(): Appearance {
  try {
    const saved = JSON.parse(localStorage.getItem(DEFAULTS_KEY) ?? "null");
    if (saved && typeof saved === "object") {
      const merged = { ...DEFAULT_APPEARANCE, ...saved };
      if (isAppearance(merged)) return merged;
    }
  } catch {
    /* ignore unreadable settings */
  }
  return DEFAULT_APPEARANCE;
}

export interface NewMark {
  page: number;
  kind: MarkKind;
  rects: Rect[];
  text?: string;
  angle?: number;
  appearance?: Appearance;
  source?: MarkSource;
  category?: string;
}

interface MarksState {
  marks: Mark[];
  selection: string[];
  past: Mark[][];
  future: Mark[][];
  lastChange: { key: string; at: number } | null;
  tool: Tool;
  defaults: Appearance;
  preview: boolean;
  /** Bumped on every change to the marks. */
  revision: number;
  /** Revision of the marks last applied, saved as a project or exported as annotations. */
  savedRevision: number;

  /** Add marks (selecting them), optionally replacing others in the same undo step.
   * Additions with the same `key` in quick succession form one undo step. */
  addMarks(items: NewMark[], replace?: string[], key?: string): Mark[];
  removeMarks(ids: string[]): void;
  /** Replace all marks: as one undo step, or as the document's starting point (no history). */
  load(marks: Mark[], undoable: boolean): void;
  /** Change marks; rapid changes with the same `key` form one undo step. */
  updateMarks(ids: string[], change: (mark: Mark) => Mark, key?: string): void;
  setAppearance(ids: string[], patch: Partial<Appearance>, key?: string): void;
  select(ids: string[], mode?: "replace" | "add" | "toggle"): void;
  undo(): void;
  redo(): void;
  setTool(tool: Tool): void;
  setDefaults(patch: Partial<Appearance>): void;
  togglePreview(): void;
  /** Record that the marks (as of `revision`, by default the current one) are safely kept. */
  markSaved(revision?: number): void;
  reset(): void;
}

const newId = () => crypto.randomUUID();

export const useMarks = create<MarksState>()((set, get) => {
  /** Record `next` as the new marks, pushing an undo step unless it continues the last change. */
  function commit(next: Mark[], key?: string) {
    const { marks, past, lastChange, revision } = get();
    const now = Date.now();
    const continues = key !== undefined && lastChange?.key === key && now - lastChange.at < COALESCE_MS;
    const ids = new Set(next.map((m) => m.id));
    set({
      marks: next,
      past: continues ? past : [...past, marks].slice(-HISTORY_LIMIT),
      future: [],
      lastChange: key === undefined ? null : { key, at: now },
      revision: revision + 1,
      selection: get().selection.filter((id) => ids.has(id)),
    });
  }

  function restore(marks: Mark[], past: Mark[][], future: Mark[][]) {
    const ids = new Set(marks.map((m) => m.id));
    set({
      marks,
      past,
      future,
      lastChange: null,
      revision: get().revision + 1,
      selection: get().selection.filter((id) => ids.has(id)),
    });
  }

  return {
    marks: [],
    selection: [],
    past: [],
    future: [],
    lastChange: null,
    tool: "text",
    defaults: loadDefaults(),
    preview: false,
    revision: 0,
    savedRevision: 0,

    addMarks(items, replace = [], key) {
      const createdAt = new Date().toISOString();
      const { defaults } = get();
      const created: Mark[] = items.map((item) => ({
        id: newId(),
        page: item.page,
        kind: item.kind,
        rects: item.rects,
        appearance: { ...(item.appearance ?? defaults) },
        text: item.text,
        angle: item.angle,
        source: item.source ?? "manual",
        category: item.category,
        createdAt,
      }));
      const drop = new Set(replace);
      commit([...get().marks.filter((m) => !drop.has(m.id)), ...created], key);
      set({ selection: created.map((m) => m.id) });
      return created;
    },

    removeMarks(ids) {
      const drop = new Set(ids);
      if (!get().marks.some((m) => drop.has(m.id))) return;
      commit(get().marks.filter((m) => !drop.has(m.id)));
    },

    load(marks, undoable) {
      if (undoable) {
        commit(marks);
        set({ selection: [] });
      } else {
        set({ marks, selection: [], past: [], future: [], lastChange: null, revision: 0, savedRevision: 0 });
      }
    },

    updateMarks(ids, change, key) {
      const targets = new Set(ids);
      if (!get().marks.some((m) => targets.has(m.id))) return;
      commit(
        get().marks.map((m) => (targets.has(m.id) ? change(m) : m)),
        key,
      );
    },

    setAppearance(ids, patch, key) {
      get().updateMarks(ids, (m) => ({ ...m, appearance: { ...m.appearance, ...patch } }), key);
    },

    select(ids, mode = "replace") {
      const current = get().selection;
      if (mode === "replace") set({ selection: [...new Set(ids)] });
      else if (mode === "add") set({ selection: [...new Set([...current, ...ids])] });
      else {
        const toggled = new Set(current);
        for (const id of ids) {
          if (toggled.has(id)) toggled.delete(id);
          else toggled.add(id);
        }
        set({ selection: [...toggled] });
      }
    },

    undo() {
      const { past, future, marks } = get();
      if (!past.length) return;
      restore(past[past.length - 1], past.slice(0, -1), [marks, ...future]);
    },

    redo() {
      const { past, future, marks } = get();
      if (!future.length) return;
      restore(future[0], [...past, marks], future.slice(1));
    },

    setTool(tool) {
      set({ tool });
    },

    setDefaults(patch) {
      const defaults = { ...get().defaults, ...patch };
      set({ defaults });
      try {
        localStorage.setItem(DEFAULTS_KEY, JSON.stringify(defaults));
      } catch {
        /* storage unavailable */
      }
    },

    togglePreview() {
      set({ preview: !get().preview });
    },

    markSaved(revision = get().revision) {
      set({ savedRevision: revision });
    },

    reset() {
      set({
        marks: [],
        selection: [],
        past: [],
        future: [],
        lastChange: null,
        revision: 0,
        savedRevision: 0,
      });
    },
  };
});

/** Marks exist that were changed since they were last applied. */
/** Whether closing would lose marks that were neither applied nor saved. */
export const hasUnsavedMarks = (s: Pick<MarksState, "marks" | "revision" | "savedRevision">) =>
  s.marks.length > 0 && s.revision !== s.savedRevision;
