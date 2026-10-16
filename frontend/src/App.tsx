import { type DragEvent, useEffect, useState } from "react";
import { NoticeBar } from "./components/NoticeBar";
import { OpenScreen } from "./components/OpenScreen";
import { PasswordDialog } from "./components/PasswordDialog";
import { Thumbnails } from "./components/Thumbnails";
import { Toolbar } from "./components/Toolbar";
import { Viewer } from "./components/Viewer";
import { useStore } from "./store";

function useGlobalShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const { phase, zoomBy, setZoom } = useStore.getState();
      if (phase !== "ready" || !(e.ctrlKey || e.metaKey)) return;
      if (e.key === "=" || e.key === "+") zoomBy(1);
      else if (e.key === "-") zoomBy(-1);
      else if (e.key === "0") setZoom(1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export default function App() {
  const phase = useStore((s) => s.phase);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const openFile = useStore((s) => s.openFile);
  const [dragging, setDragging] = useState(false);
  useGlobalShortcuts();

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = [...e.dataTransfer.files].find(
      (f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"),
    );
    if (file) void openFile(file);
    else if (e.dataTransfer.files.length) setError("Only PDF files can be opened.");
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
      {error && (
        <div className="notice-bar error" role="alert">
          <span>{error}</span>
          <button className="link" onClick={() => setError(null)} aria-label="Dismiss">
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
          </main>
        </>
      ) : (
        <OpenScreen />
      )}
      {phase === "locked" && <PasswordDialog />}
    </div>
  );
}
