import { beforeEach, describe, expect, it, vi } from "vitest";
import { hasUnsavedMarks, isAppearance, useMarks } from "./marks";

const store = () => useMarks.getState();
const area = (page = 0) => ({ page, kind: "area" as const, rects: [[0, 0, 10, 10]] as [number, number, number, number][] });

describe("marks store", () => {
  beforeEach(() => store().reset());

  it("adds marks with the default appearance and selects them", () => {
    const [mark] = store().addMarks([area()]);
    expect(store().marks).toHaveLength(1);
    expect(store().selection).toEqual([mark.id]);
    expect(mark.appearance).toEqual(store().defaults);
    expect(mark.appearance).not.toBe(store().defaults);
  });

  it("undoes and redoes changes and keeps the selection valid", () => {
    const [a] = store().addMarks([area()]);
    const [b] = store().addMarks([area(1)]);
    store().select([a.id, b.id]);
    store().undo();
    expect(store().marks.map((m) => m.id)).toEqual([a.id]);
    expect(store().selection).toEqual([a.id]);
    store().redo();
    expect(store().marks.map((m) => m.id)).toEqual([a.id, b.id]);
    store().removeMarks([a.id]);
    expect(store().future).toEqual([]);
    store().undo();
    expect(store().marks).toHaveLength(2);
  });

  it("merges rapid changes with the same key into one step", () => {
    vi.useFakeTimers();
    try {
      const [a] = store().addMarks([area()]);
      for (const text of ["W", "Wi", "Wit"]) store().setAppearance([a.id], { overlayText: text }, "text");
      expect(store().past).toHaveLength(2);
      vi.advanceTimersByTime(1500);
      store().setAppearance([a.id], { overlayText: "With" }, "text");
      expect(store().past).toHaveLength(3);
      store().undo();
      expect(store().marks[0].appearance.overlayText).toBe("Wit");
      store().undo();
      expect(store().marks[0].appearance.overlayText).toBe("");
    } finally {
      vi.useRealTimers();
    }
  });

  it("replaces marks in a single step", () => {
    const [word] = store().addMarks([area()]);
    const [line] = store().addMarks([area()], [word.id]);
    expect(store().marks.map((m) => m.id)).toEqual([line.id]);
    store().undo();
    expect(store().marks.map((m) => m.id)).toEqual([word.id]);
  });

  it("merges keyed additions, such as a word mark widened to its line", () => {
    const [word] = store().addMarks([area()], [], "click:1");
    const [line] = store().addMarks([area()], [word.id], "click:1");
    expect(store().marks.map((m) => m.id)).toEqual([line.id]);
    store().undo();
    expect(store().marks).toEqual([]);
  });

  it("toggles selection", () => {
    const [a, b] = store().addMarks([area(), area()]);
    store().select([a.id]);
    store().select([a.id, b.id], "toggle");
    expect(store().selection).toEqual([b.id]);
  });

  it("loads marks as an undo step or as the starting point", () => {
    const [a] = store().addMarks([area()]);
    const loaded = { ...a, id: "loaded" };
    store().load([loaded], true);
    expect(store().marks).toEqual([loaded]);
    expect(store().selection).toEqual([]);
    expect(hasUnsavedMarks(store())).toBe(true);
    store().undo();
    expect(store().marks).toEqual([a]);

    store().load([loaded], false);
    expect(store().marks).toEqual([loaded]);
    expect(store().past).toEqual([]);
    expect(hasUnsavedMarks(store())).toBe(false); // the marks are still in the file
    store().setAppearance(["loaded"], { fill: null });
    expect(hasUnsavedMarks(store())).toBe(true);
  });

  it("tracks whether marks changed since they were applied or saved", () => {
    expect(hasUnsavedMarks(store())).toBe(false);
    const [a] = store().addMarks([area()]);
    expect(hasUnsavedMarks(store())).toBe(true);
    store().markSaved();
    expect(hasUnsavedMarks(store())).toBe(false);
    store().removeMarks([a.id]);
    expect(hasUnsavedMarks(store())).toBe(false); // nothing left to lose
  });
});

describe("isAppearance", () => {
  const ok = useMarks.getState().defaults;
  it("accepts complete appearances", () => {
    expect(isAppearance(ok)).toBe(true);
    expect(isAppearance({ ...ok, fill: null, fontSize: 12 })).toBe(true);
  });
  it("rejects malformed ones", () => {
    expect(isAppearance(null)).toBe(false);
    expect(isAppearance({ ...ok, fill: "black" })).toBe(false);
    expect(isAppearance({ ...ok, fontSize: 100 })).toBe(false);
    expect(isAppearance({ ...ok, font: "comic" })).toBe(false);
    expect(isAppearance({ ...ok, overlayText: "x".repeat(201) })).toBe(false);
    const { repeat: _, ...partial } = ok;
    expect(isAppearance(partial)).toBe(false);
  });
});
