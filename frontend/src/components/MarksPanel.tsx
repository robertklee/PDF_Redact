import { type KeyboardEvent, type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMarks } from "../marks";
import { useStore } from "../store";
import { describeMark, KIND_LABELS } from "../lib/format";
import type { Mark } from "../types";

/** Top-to-bottom, then left-to-right position of a mark on its page. */
const position = (m: Mark) => (m.kind === "page" ? [-1, -1] : [m.rects[0][1], m.rects[0][0]]);

export function MarksPanel() {
  const marks = useMarks((s) => s.marks);
  const selection = useMarks((s) => s.selection);
  const select = useMarks((s) => s.select);
  const removeMarks = useMarks((s) => s.removeMarks);
  const goToPage = useStore((s) => s.goToPage);
  const list = useRef<HTMLDivElement>(null);
  const selected = useMemo(() => new Set(selection), [selection]);
  const [focusId, setFocusId] = useState<string | null>(null);

  const groups = useMemo(() => {
    const byPage = new Map<number, Mark[]>();
    for (const m of marks) byPage.set(m.page, [...(byPage.get(m.page) ?? []), m]);
    return [...byPage.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([page, items]) => {
        items.sort((a, b) => {
          const [ay, ax] = position(a);
          const [by, bx] = position(b);
          return ay - by || ax - bx;
        });
        return [page, items] as const;
      });
  }, [marks]);
  const ordered = useMemo(() => groups.flatMap(([, items]) => items), [groups]);
  // The one mark in the list reached with Tab; the arrow keys move between marks.
  const tabStop = ordered.find((m) => m.id === focusId) ?? ordered.find((m) => selected.has(m.id)) ?? ordered[0];

  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [selection]);

  function show(mark: Mark) {
    goToPage(mark.page, mark.kind === "page" ? undefined : mark.rects[0][1]);
  }

  function onItemClick(e: MouseEvent, mark: Mark) {
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      select([mark.id], "toggle");
      return;
    }
    select([mark.id]);
    show(mark);
  }

  function focusMark(id: string) {
    setFocusId(id);
    list.current?.querySelector<HTMLElement>(`[data-mark-id="${id}"]`)?.focus();
  }

  /** The listbox keys: arrows, Home and End move (Shift adds to the selection), Delete removes. */
  function onListKey(e: KeyboardEvent) {
    const at = ordered.findIndex((m) => m.id === (e.target as HTMLElement).dataset.markId);
    if (at < 0 || e.altKey) return;
    const mark = ordered[at];
    let next: number;
    if (e.key === "ArrowDown") next = Math.min(at + 1, ordered.length - 1);
    else if (e.key === "ArrowUp") next = Math.max(at - 1, 0);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = ordered.length - 1;
    else if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey || e.metaKey || e.ctrlKey) select([mark.id], "toggle");
      else {
        select([mark.id]);
        show(mark);
      }
      return;
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      const ids = new Set(selected.has(mark.id) ? selection : [mark.id]);
      const kept = (m: Mark) => !ids.has(m.id);
      const after = ordered.slice(at + 1).find(kept) ?? ordered.slice(0, at).reverse().find(kept);
      if (after) focusMark(after.id);
      removeMarks([...ids]);
      return;
    } else return;
    e.preventDefault();
    const target = ordered[next];
    focusMark(target.id);
    select([target.id], e.shiftKey ? "add" : "replace");
    show(target);
  }

  function clearAll() {
    if (window.confirm(`Remove all ${marks.length} marks? You can undo this.`)) {
      removeMarks(marks.map((m) => m.id));
    }
  }

  return (
    <section className="panel marks-panel" aria-label="Marks">
      <header className="panel-header">
        <h2>Marks</h2>
        {marks.length > 0 && (
          <>
            <span className="muted">
              {marks.length} on {groups.length} page{groups.length === 1 ? "" : "s"}
            </span>
            <button className="link" onClick={clearAll}>
              Clear all
            </button>
          </>
        )}
      </header>
      <div className="panel-body" ref={list}>
        {marks.length === 0 ? (
          <p className="empty">
            Select text or drag a box on the page to mark it for redaction. Nothing is removed until
            you apply the marks.
          </p>
        ) : (
          <div
            role="listbox"
            aria-multiselectable="true"
            aria-label="Marks"
            aria-describedby="marks-keys"
            onKeyDown={onListKey}
          >
            <p id="marks-keys" hidden>
              Arrow keys move between marks, Shift adds to the selection, Delete removes.
            </p>
            {groups.map(([page, items]) => (
              <div key={page} className="mark-group" role="group" aria-label={`Page ${page + 1}`}>
                <div className="mark-group-title" aria-hidden="true">
                  Page {page + 1}
                </div>
                {items.map((m) => (
                  <div
                    key={m.id}
                    role="option"
                    aria-selected={selected.has(m.id)}
                    className="mark-item"
                    data-mark-id={m.id}
                    tabIndex={m === tabStop ? 0 : -1}
                    onFocus={() => setFocusId(m.id)}
                    onClick={(e) => onItemClick(e, m)}
                  >
                    <span className={`kind kind-${m.kind}`}>{KIND_LABELS[m.kind]}</span>
                    <span className="mark-desc" title={m.text}>
                      {describeMark(m)}
                    </span>
                    {m.appearance.overlayText.trim() && (
                      <span className="overlay-badge" title="Overlay text">
                        {m.appearance.overlayText.trim()}
                      </span>
                    )}
                    {/* For the mouse; from the keyboard, Delete removes the mark. */}
                    <span
                      className="icon remove"
                      title="Remove mark"
                      aria-hidden="true"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeMarks([m.id]);
                      }}
                    >
                      ✕
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
