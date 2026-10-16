import { useStore } from "../store";

export function openFilePicker() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/pdf,.pdf";
  input.onchange = () => {
    const file = input.files?.[0];
    if (file) void useStore.getState().openFile(file);
  };
  input.click();
}
