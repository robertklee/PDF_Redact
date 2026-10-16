import { type MouseEvent, useEffect, useMemo, useRef } from "react";
import { useMarks } from "../marks";
import { useStore } from "../store";
import type { Mark } from "../types";

const EXCERPT_LENGTH = 60;

function describe(mark: Mark): string {
  if (mark.kind === "page") return "Whole page";
  if (mark.kind === "text") {
    const text = (mark.text ?? "").replace(/\s+/g, " ");
    return text.length > EXCERPT_LENGTH ? `“${text.slice(0, EXCERPT_LENGTH)}…”` : `“${text}”`;
  }
  const [x0, y0, x1, y1] = mark.rects[0];
  return `${Math.round(x1 - x0)} × ${Math.round(y1 - y0)} pt`;
}

const KIND_LABELS = { text: "Text", area: "Area", page: "Page" } as const;

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

  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [selection]);

  function onItemClick(e: MouseEvent, mark: Mark) {
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      select([mark.id], "toggle");
      return;
    }
    select([mark.id]);
    goToPage(mark.page, mark.kind === "page" ? undefined : mark.rects[0][1]);
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
          groups.map(([page, items]) => (
            <div key={page} className="mark-group">
              <h3>Page {page + 1}</h3>
              <ul role="listbox" aria-multiselectable="true" aria-label={`Marks on page ${page + 1}`}>
                {items.map((m) => (
                  <li
                    key={m.id}
                    role="option"
                    aria-selected={selected.has(m.id)}
                    className="mark-item"
                    onClick={(e) => onItemClick(e, m)}
                  >
                    <span className={`kind kind-${m.kind}`}>{KIND_LABELS[m.kind]}</span>
                    <span className="mark-desc" title={m.text}>
                      {describe(m)}
                    </span>
                    {m.appearance.overlayText.trim() && (
                      <span className="overlay-badge" title="Overlay text">
                        {m.appearance.overlayText.trim()}
                      </span>
                    )}
                    <button
                      className="icon"
                      title="Remove mark"
                      aria-label="Remove mark"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeMarks([m.id]);
                      }}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
