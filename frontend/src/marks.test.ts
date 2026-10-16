import { beforeEach, describe, expect, it, vi } from "vitest";
import { hasUnappliedMarks, useMarks } from "./marks";

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

  it("tracks whether marks changed since they were applied", () => {
    expect(hasUnappliedMarks(store())).toBe(false);
    const [a] = store().addMarks([area()]);
    expect(hasUnappliedMarks(store())).toBe(true);
    store().markApplied();
    expect(hasUnappliedMarks(store())).toBe(false);
    store().removeMarks([a.id]);
    expect(hasUnappliedMarks(store())).toBe(false); // nothing left to lose
  });
});
