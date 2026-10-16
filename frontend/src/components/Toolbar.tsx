import { useState } from "react";
import { confirmDiscard, openFilePicker } from "../lib/files";
import { useStore, ZOOM_STEPS } from "../store";

function PageNavigator() {
  const currentPage = useStore((s) => s.currentPage);
  const pageCount = useStore((s) => s.doc?.pageCount ?? 0);
  const goToPage = useStore((s) => s.goToPage);
  // Text being typed; otherwise the input shows the current page.
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? String(currentPage + 1);

  return (
    <div className="group">
      <button onClick={() => goToPage(currentPage - 1)} disabled={currentPage === 0} title="Previous page">
        ‹
      </button>
      <input
        className="page-input"
        aria-label="Page number"
        value={value}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            const n = Number.parseInt(value, 10);
            if (Number.isFinite(n)) goToPage(n - 1);
            (e.target as HTMLInputElement).blur();
          }
        }}
        onBlur={() => setDraft(null)}
      />
      <span className="muted">/ {pageCount}</span>
      <button
        onClick={() => goToPage(currentPage + 1)}
        disabled={currentPage >= pageCount - 1}
        title="Next page"
      >
        ›
      </button>
    </div>
  );
}

function ZoomControl() {
  const zoom = useStore((s) => s.zoom);
  const fit = useStore((s) => s.fit);
  const setZoom = useStore((s) => s.setZoom);
  const zoomBy = useStore((s) => s.zoomBy);
  const selected = fit ?? (ZOOM_STEPS.some((z) => Math.abs(z - zoom) < 1e-3) ? String(zoom) : "custom");

  return (
    <div className="group">
      <button onClick={() => zoomBy(-1)} title="Zoom out (Ctrl+-)">
        −
      </button>
      <select
        aria-label="Zoom"
        value={selected}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "width" || v === "page") setZoom(zoom, v);
          else setZoom(Number(v));
        }}
      >
        {selected === "custom" && <option value="custom">{Math.round(zoom * 100)}%</option>}
        <option value="width">Fit width</option>
        <option value="page">Fit page</option>
        {ZOOM_STEPS.map((z) => (
          <option key={z} value={String(z)}>
            {Math.round(z * 100)}%
          </option>
        ))}
      </select>
      <button onClick={() => zoomBy(1)} title="Zoom in (Ctrl+=)">
        +
      </button>
    </div>
  );
}

export function Toolbar() {
  const doc = useStore((s) => s.doc);
  const phase = useStore((s) => s.phase);
  const closeDocument = useStore((s) => s.closeDocument);
  const showTextBoxes = useStore((s) => s.showTextBoxes);
  const toggleTextBoxes = useStore((s) => s.toggleTextBoxes);
  const ready = phase === "ready";

  return (
    <header className="toolbar">
      <strong className="brand">PDF Redact</strong>
      <div className="group">
        <button onClick={openFilePicker}>Open…</button>
        {doc && <button onClick={() => confirmDiscard() && void closeDocument()}>Close</button>}
      </div>
      {doc && <span className="filename" title={doc.filename}>{doc.filename}</span>}
      {ready && (
        <>
          <span className="spacer" />
          <PageNavigator />
          <ZoomControl />
          <label className="toggle" title="Show the text geometry used for selection">
            <input type="checkbox" checked={showTextBoxes} onChange={toggleTextBoxes} /> Text boxes
          </label>
        </>
      )}
    </header>
  );
}
