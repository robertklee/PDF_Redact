import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { BACKEND_DIR, CORPUS_DIR, PYTHON } from "./env.ts";

/** Generate the synthetic PDF corpus the backend tests use, plus a long document. */
export default function globalSetup() {
  const run = (args: string[]) => execFileSync(PYTHON, args, { cwd: BACKEND_DIR, stdio: ["ignore", "ignore", "inherit"] });
  run(["-m", "tests.corpus", CORPUS_DIR]);
  const large = "import sys; from tests.bench import large_document; open(sys.argv[1], 'wb').write(large_document(400))";
  run(["-c", large, join(CORPUS_DIR, "large.pdf")]);
}
