import { type DragEvent, useEffect, useState } from "react";
import { NoticeBar } from "./components/NoticeBar";
import { OpenScreen } from "./components/OpenScreen";
import { PasswordDialog } from "./components/PasswordDialog";
import { RedactionBar } from "./components/RedactionBar";
import { Sidebar } from "./components/Sidebar";
import { Thumbnails } from "./components/Thumbnails";
import { Toolbar } from "./components/Toolbar";
import { Viewer } from "./components/Viewer";
import { confirmDiscard, loadProjectFile, saveProject } from "./lib/files";
import { clampedOffset, roundRect, translate } from "./lib/geometry";
import { isProjectFile } from "./lib/project";
import { hasUnsavedMarks, useMarks } from "./marks";
import { openSearch } from "./search";
import { useStore } from "./store";
import type { Rect } from "./types";

const TOOL_KEYS = { v: "select", t: "text", r: "area" } as const;
const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** Move the selected area marks by a few points, keeping them on their pages. */
function nudge(dx: number, dy: number): boolean {
  const { marks, selection, updateMarks } = useMarks.getState();
  const pages = useStore.getState().doc?.pages ?? [];
  const ids = new Set(selection);
  const targets = marks.filter((m) => ids.has(m.id) && m.kind === "area");
  if (!targets.length) return false;
  const offsets = new Map<string, { x: number; y: number }>();
  for (const m of targets) {
    const { width, height } = pages[m.page];
    const bounds: Rect = [0, 0, width, height];
    offsets.set(m.id, clampedOffset(m.rects, dx, dy, bounds));
  }
  updateMarks(
    targets.map((m) => m.id),
    (m) => {
      const off = offsets.get(m.id)!;
      return { ...m, rects: m.rects.map((r) => roundRect(translate(r, off.x, off.y))) };
    },
    `nudge:${selection.join(",")}`,
  );
  return true;
}

function useGlobalShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const { phase, zoomBy, setZoom } = useStore.getState();
      // Handled already (e.g. by the marks list), or a dialog is open.
      if (e.defaultPrevented || phase !== "ready" || document.querySelector(".modal")) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (mod && !e.altKey && !e.shiftKey && key === "f") {
        e.preventDefault();
        openSearch();
        return;
      }
      if (mod && !e.altKey && !e.shiftKey && key === "s") {
        e.preventDefault();
        saveProject();
        return;
      }
      if (isEditable(e.target)) return;
      const marks = useMarks.getState();
      if (mod) {
        if (key === "=" || key === "+") zoomBy(1);
        else if (key === "-") zoomBy(-1);
        else if (key === "0") setZoom(1);
        else if (key === "z" && !e.shiftKey) marks.undo();
        else if ((key === "z" && e.shiftKey) || key === "y") marks.redo();
        else if (key === "a") marks.select(marks.marks.map((m) => m.id));
        else return;
      } else if (e.altKey) {
        return;
      } else if (key in TOOL_KEYS) {
        marks.setTool(TOOL_KEYS[key as keyof typeof TOOL_KEYS]);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        if (!marks.selection.length) return;
        marks.removeMarks(marks.selection);
      } else if (e.key === "Escape") {
        marks.select([]);
      } else if (e.key in ARROWS) {
        const [dx, dy] = ARROWS[e.key];
        const step = e.shiftKey ? 10 : 1;
        if (!nudge(dx * step, dy * step)) return;
      } else {
        return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function useUnloadGuard() {
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasUnsavedMarks(useMarks.getState())) e.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);
}

export default function App() {
  const phase = useStore((s) => s.phase);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const status = useStore((s) => s.status);
  const setStatus = useStore((s) => s.setStatus);
  const openFile = useStore((s) => s.openFile);
  const [dragging, setDragging] = useState(false);
  useGlobalShortcuts();
  useUnloadGuard();

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = [...e.dataTransfer.files];
    const file = files.find((f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"));
    const project = files.find(isProjectFile);
    if (file) {
      if (confirmDiscard()) void openFile(file);
    } else if (project && phase === "ready") {
      void loadProjectFile(project);
    } else if (files.length) {
      setError(
        project ? "Open the PDF first, then load its project." : "Only PDF files and PDF Redact projects can be opened.",
      );
    }
  };

  return (
    <div
      className={`app${dragging ? " dragging" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragging(false);
      }}
      onDrop={onDrop}
    >
      <Toolbar />
      {phase === "ready" && <RedactionBar />}
      {error && (
        <div className="notice-bar error" role="alert">
          <span>{error}</span>
          <button className="link" onClick={() => setError(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
      {status && (
        <div className="notice-bar info status" role="status">
          <span>{status}</span>
          <button className="link" onClick={() => setStatus(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
      {phase === "ready" ? (
        <>
          <NoticeBar />
          <main className="workspace">
            <Thumbnails />
            <Viewer />
            <Sidebar />
          </main>
        </>
      ) : (
        <OpenScreen />
      )}
      {phase === "locked" && <PasswordDialog />}
    </div>
  );
}
