import { useState } from "react";
import { type Tool, useMarks } from "../marks";
import { ApplyDialog } from "./ApplyDialog";
import { PageMarkDialog } from "./PageMarkDialog";

const TOOLS: { tool: Tool; label: string; key: string; title: string }[] = [
  { tool: "text", label: "Mark text", key: "T", title: "Select text to mark it; drag away from text to draw a box" },
  { tool: "area", label: "Mark area", key: "R", title: "Drag a box over any content" },
  { tool: "select", label: "Select", key: "V", title: "Select, move and resize marks" },
];

const isMac = typeof navigator !== "undefined" && /Mac|iP(hone|ad)/.test(navigator.platform);
const MOD = isMac ? "⌘" : "Ctrl+";

/** Tools for creating and reviewing redaction marks. */
export function RedactionBar() {
  const tool = useMarks((s) => s.tool);
  const setTool = useMarks((s) => s.setTool);
  const canUndo = useMarks((s) => s.past.length > 0);
  const canRedo = useMarks((s) => s.future.length > 0);
  const undo = useMarks((s) => s.undo);
  const redo = useMarks((s) => s.redo);
  const preview = useMarks((s) => s.preview);
  const togglePreview = useMarks((s) => s.togglePreview);
  const markCount = useMarks((s) => s.marks.length);
  const [dialog, setDialog] = useState<"pages" | "apply" | null>(null);
  const closeDialog = () => setDialog(null);

  return (
    <div className="toolbar redaction-bar" role="toolbar" aria-label="Redaction tools">
      <div className="group segmented" role="radiogroup" aria-label="Tool">
        {TOOLS.map((t) => (
          <button
            key={t.tool}
            role="radio"
            aria-checked={tool === t.tool}
            className={tool === t.tool ? "active" : undefined}
            title={`${t.title} (${t.key})`}
            onClick={() => setTool(t.tool)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <button onClick={() => setDialog("pages")} title="Mark whole pages">
        Mark pages…
      </button>
      <div className="group">
        <button onClick={undo} disabled={!canUndo} title={`Undo (${MOD}Z)`}>
          Undo
        </button>
        <button onClick={redo} disabled={!canRedo} title={`Redo (${isMac ? "⇧⌘Z" : "Ctrl+Y"})`}>
          Redo
        </button>
      </div>
      <label className="toggle" title="Show every mark as it will look once applied">
        <input type="checkbox" checked={preview} onChange={togglePreview} /> Preview
      </label>
      <span className="spacer" />
      <button
        className="danger"
        onClick={() => setDialog("apply")}
        disabled={!markCount}
        title="Remove the marked content and save a redacted copy"
      >
        Apply {markCount > 0 && `${markCount} `}redaction{markCount === 1 ? "" : "s"}…
      </button>
      {dialog === "pages" && <PageMarkDialog onClose={closeDialog} />}
      {dialog === "apply" && <ApplyDialog onClose={closeDialog} />}
    </div>
  );
}
