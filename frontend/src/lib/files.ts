import { api } from "../api";
import { hasUnsavedMarks, useMarks } from "../marks";
import { useStore } from "../store";
import { plural } from "./format";
import { parseProject, PROJECT_SUFFIX, ProjectError, projectFilename, serializeProject } from "./project";

/** Ask before closing a document whose marks were neither applied nor saved. */
export function confirmDiscard(): boolean {
  const marks = useMarks.getState();
  if (!hasUnsavedMarks(marks)) return true;
  const n = marks.marks.length;
  return window.confirm(
    `${n} redaction mark${n === 1 ? " has" : "s have"} not been applied or saved and will be lost. Continue?`,
  );
}

export function openFilePicker() {
  if (!confirmDiscard()) return;
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/pdf,.pdf";
  input.onchange = () => {
    const file = input.files?.[0];
    if (file) void useStore.getState().openFile(file);
  };
  input.click();
}

/** Offer `text` as a file download. */
export function saveTextFile(filename: string, text: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Save the marks to a project file next to the PDF. */
export function saveProject() {
  const { doc } = useStore.getState();
  if (!doc) return;
  const marks = useMarks.getState();
  saveTextFile(projectFilename(doc.filename), serializeProject(doc, marks.marks));
  marks.markSaved();
}

export function openProjectPicker() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = `${PROJECT_SUFFIX},.json,application/json`;
  input.onchange = () => {
    const file = input.files?.[0];
    if (file) void loadProjectFile(file);
  };
  input.click();
}

/** Replace the marks with those of a saved project, after checking it belongs to this document. */
export async function loadProjectFile(file: File) {
  const { doc, setError, setStatus } = useStore.getState();
  if (!doc) return;
  let project;
  try {
    project = parseProject(await file.text(), doc);
  } catch (err) {
    setError(err instanceof ProjectError ? err.message : "The project file could not be read.");
    return;
  }
  if (
    project.otherFile !== null &&
    !window.confirm(
      `This project was saved for “${project.otherFile}”, not for this file (or for a different version of it). ` +
        "The marks may not line up with the content. Load it anyway?",
    )
  ) {
    return;
  }
  const marks = useMarks.getState();
  const current = marks.marks.length;
  if (
    current > 0 &&
    !window.confirm(
      `Replace the ${plural(current, "current mark")} with the ${plural(project.marks.length, "mark")} ` +
        "from the project? You can undo this.",
    )
  ) {
    return;
  }
  marks.load(project.marks, true);
  marks.markSaved();
  setError(null);
  let status = `Loaded ${plural(project.marks.length, "mark")} from ${file.name}.`;
  if (project.skipped) {
    status += ` ${plural(project.skipped, "mark")} could not be used: on pages this document does not have, or damaged.`;
  }
  setStatus(status);
}

/** Download the original with the marks as unapplied redaction annotations. */
export async function exportMarkedPdf() {
  const { doc, setError } = useStore.getState();
  if (!doc) return;
  const { marks, revision, markSaved } = useMarks.getState();
  try {
    await api.exportMarked(doc.id, doc.filename, marks);
    markSaved(revision);
  } catch (err) {
    setError(`The marked copy could not be created: ${err instanceof Error ? err.message : String(err)}`);
  }
}
