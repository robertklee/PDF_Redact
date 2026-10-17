import { type FormEvent, useState } from "react";
import { formatPages, parsePageRanges } from "../lib/pages";
import { useMarks } from "../marks";
import { useStore } from "../store";
import { Modal } from "./Modal";

/** Mark whole pages, chosen by number or range. */
export function PageMarkDialog({ onClose }: { onClose: () => void }) {
  const doc = useStore((s) => s.doc)!;
  const currentPage = useStore((s) => s.currentPage);
  const [value, setValue] = useState(String(currentPage + 1));
  const [touched, setTouched] = useState(false);
  const result = parsePageRanges(value, doc.pageCount);

  const alreadyMarked = new Set(
    useMarks.getState().marks.filter((m) => m.kind === "page").map((m) => m.page),
  );
  const pages = result.pages?.filter((p) => !alreadyMarked.has(p)) ?? [];
  const skipped = (result.pages?.length ?? 0) - pages.length;

  function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (!pages.length) return;
    useMarks.getState().addMarks(
      pages.map((p) => {
        const { width, height } = doc.pages[p];
        return { page: p, kind: "page" as const, rects: [[0, 0, width, height]] };
      }),
    );
    onClose();
  }

  return (
    <Modal labelledBy="mark-pages-title" onDismiss={onClose}>
      <form className="modal" onSubmit={submit}>
        <h2 id="mark-pages-title">Mark pages</h2>
        <p>
          Redacts everything on the chosen pages, including content outside the visible page area.
        </p>
        <label className="field">
          <span>Pages (1–{doc.pageCount})</span>
          <input
            data-autofocus
            value={value}
            placeholder="e.g. 1, 4-7, odd, all"
            onChange={(e) => setValue(e.target.value)}
            onBlur={() => setTouched(true)}
          />
        </label>
        {result.error && touched && (
          <p className="error" role="alert">
            {result.error}
          </p>
        )}
        {result.pages && (
          <p className="muted">
            {pages.length
              ? `${pages.length} page${pages.length === 1 ? "" : "s"}: ${formatPages(pages)}`
              : "These pages are already marked."}
            {skipped > 0 && pages.length > 0 && ` (${skipped} already marked)`}
          </p>
        )}
        <div className="actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" type="submit" disabled={!pages.length}>
            Mark {pages.length || ""} page{pages.length === 1 ? "" : "s"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
