import { create } from "zustand";
import { BUILT_IN_SETS, codeSetProblem, type CodeSet } from "./lib/codes";

const STORAGE_KEY = "pdf-redact-code-sets";

interface Saved {
  custom: CodeSet[];
  activeId: string;
}

function load(): Saved {
  const fallback = { custom: [], activeId: BUILT_IN_SETS[0].id };
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (!saved || typeof saved !== "object") return fallback;
    const custom: CodeSet[] = (Array.isArray(saved.custom) ? saved.custom : [])
      .filter(
        (s: CodeSet) =>
          typeof s?.id === "string" &&
          typeof s.name === "string" &&
          Array.isArray(s.codes) &&
          s.codes.every((c) => typeof c?.code === "string" && typeof c.description === "string") &&
          codeSetProblem(s) === null,
      )
      .map(({ id, name, codes }: CodeSet) => ({
        id,
        name,
        codes: codes.map(({ code, description }) => ({ code, description })),
      }));
    const ids = new Set([...BUILT_IN_SETS, ...custom].map((s) => s.id));
    return { custom, activeId: ids.has(saved.activeId) ? saved.activeId : fallback.activeId };
  } catch {
    return fallback;
  }
}

interface CodeSetsState extends Saved {
  setActive(id: string): void;
  /** Add a custom set and make it active; returns its id. */
  add(set: Pick<CodeSet, "name" | "codes">): string;
  update(id: string, set: Pick<CodeSet, "name" | "codes">): void;
  remove(id: string): void;
}

export const useCodeSets = create<CodeSetsState>()((set, get) => {
  function save(next: Partial<Saved>) {
    set(next);
    const { custom, activeId } = get();
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ custom, activeId }));
    } catch {
      /* storage unavailable */
    }
  }

  return {
    ...load(),

    setActive(activeId) {
      save({ activeId });
    },

    add({ name, codes }) {
      const id = crypto.randomUUID();
      save({ custom: [...get().custom, { id, name, codes }], activeId: id });
      return id;
    },

    update(id, { name, codes }) {
      save({ custom: get().custom.map((s) => (s.id === id ? { id, name, codes } : s)) });
    },

    remove(id) {
      const custom = get().custom.filter((s) => s.id !== id);
      save({ custom, activeId: get().activeId === id ? BUILT_IN_SETS[0].id : get().activeId });
    },
  };
});

export function allCodeSets(custom: CodeSet[]): CodeSet[] {
  return [...BUILT_IN_SETS, ...custom];
}

export function activeCodeSet({ custom, activeId }: Saved): CodeSet {
  return allCodeSets(custom).find((s) => s.id === activeId) ?? BUILT_IN_SETS[0];
}
