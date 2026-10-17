import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { exportMarkedPdf, openProjectPicker, saveProject } from "../lib/files";
import { useMarks } from "../marks";

const MOD = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";

/** Save and load unapplied marks: as a project file, or as a PDF with redaction annotations. */
export function ProjectMenu() {
  const [open, setOpen] = useState(false);
  const count = useMarks((s) => s.marks.length);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLElement>('[role="menuitem"]:not(:disabled)')?.focus();
    const onPointerDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function onMenuKey(e: KeyboardEvent) {
    const items = [...(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)') ?? [])];
    const index = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(index + step + items.length) % items.length]?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
      return;
    } else {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }

  const run = (action: () => unknown) => () => {
    setOpen(false);
    void action();
  };

  return (
    <div className="menu" ref={root}>
      <button
        ref={button}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        title="Save the marks to finish later, or share them for review"
      >
        Project ▾
      </button>
      {open && (
        <div className="menu-popup" role="menu" aria-label="Project" onKeyDown={onMenuKey}>
          <button role="menuitem" onClick={run(saveProject)}>
            <span className="menu-label">
              Save project <kbd>{MOD}S</kbd>
            </span>
            <span className="menu-hint">The marks as a .redact.json file, to carry on later</span>
          </button>
          <button role="menuitem" onClick={run(openProjectPicker)}>
            <span className="menu-label">Load project…</span>
            <span className="menu-hint">Replace the marks with those saved for this PDF</span>
          </button>
          <hr />
          <button role="menuitem" onClick={run(exportMarkedPdf)} disabled={count === 0}>
            <span className="menu-label">Export marked PDF</span>
            <span className="menu-hint">
              An <strong>unredacted</strong> copy carrying the marks as redaction annotations, for review or applying
              in Acrobat and other tools
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
