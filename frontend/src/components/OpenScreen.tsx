import { openFilePicker } from "../lib/files";
import { useStore } from "../store";

export function OpenScreen() {
  const phase = useStore((s) => s.phase);
  const file = useStore((s) => s.file);
  return (
    <div className="open-screen">
      <div className="drop-zone">
        {phase === "opening" ? (
          <p>Opening {file?.name}…</p>
        ) : (
          <>
            <h1>Redact a PDF</h1>
            <p>Drop a PDF here, or</p>
            <button className="primary" onClick={openFilePicker}>
              Choose a file…
            </button>
            <p className="muted small">
              Files are processed on this computer by the local PDF Redact server and are never
              uploaded anywhere else. Redaction removes the marked text, image pixels and graphics
              from a new copy of the file.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
