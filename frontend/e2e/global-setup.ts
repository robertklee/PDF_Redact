import { execFileSync } from "node:child_process";
import { BACKEND_DIR, CORPUS_DIR, PYTHON } from "./env.ts";

/** Generate the synthetic PDF corpus the backend tests use. */
export default function globalSetup() {
  execFileSync(PYTHON, ["-m", "tests.corpus", CORPUS_DIR], { cwd: BACKEND_DIR, stdio: ["ignore", "ignore", "inherit"] });
}
