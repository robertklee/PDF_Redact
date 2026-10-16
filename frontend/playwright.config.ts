import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import { E2E_PORT, E2E_TOKEN, PYTHON } from "./e2e/env.ts";

const BACKEND = fileURLToPath(new URL("../backend", import.meta.url));
const DIST = fileURLToPath(new URL("./dist", import.meta.url));

/** End-to-end tests run the built UI against a real backend, as a user would. */
export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  workers: 2,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${E2E_PORT}`,
    viewport: { width: 1400, height: 900 },
    acceptDownloads: true,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } } }],
  webServer: {
    command: `npm run build && "${PYTHON}" -m pdf_redact.main --no-browser --port ${E2E_PORT}`,
    url: `http://127.0.0.1:${E2E_PORT}/`,
    env: { PDF_REDACT_TOKEN: E2E_TOKEN, PDF_REDACT_STATIC: DIST, PYTHONPATH: BACKEND },
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
