import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const VENV = fileURLToPath(new URL("../../backend/.venv", import.meta.url));

export const E2E_PORT = Number(process.env.E2E_PORT ?? 8799);
export const E2E_TOKEN = "e2e-token";
/** Python with the backend installed; used to run the server and to inspect output PDFs. */
export const PYTHON =
  process.env.PDF_REDACT_PYTHON ??
  (process.platform === "win32" ? join(VENV, "Scripts", "python.exe") : join(VENV, "bin", "python"));
export const BACKEND_DIR = fileURLToPath(new URL("../../backend", import.meta.url));
export const CORPUS_DIR = join(tmpdir(), "pdf-redact-e2e-corpus");
