import { hasUnappliedMarks, useMarks } from "../marks";
import { useStore } from "../store";

/** Ask before closing a document whose marks have not been applied. */
export function confirmDiscard(): boolean {
  const marks = useMarks.getState();
  if (!hasUnappliedMarks(marks)) return true;
  const n = marks.marks.length;
  return window.confirm(
    `${n} redaction mark${n === 1 ? " has" : "s have"} not been applied and will be lost. Continue?`,
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
