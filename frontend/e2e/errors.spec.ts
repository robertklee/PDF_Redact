import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { CORPUS_DIR, E2E_TOKEN } from "./env.ts";

async function choose(page: Page, file: string | { name: string; mimeType: string; buffer: Buffer }) {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose a file…" }).click();
  await (await chooser).setFiles(file);
}

test("explains why a file can't be opened, and opens the next one", async ({ page }) => {
  await page.goto(`/#token=${E2E_TOKEN}`);
  await choose(page, { name: "notes.pdf", mimeType: "application/pdf", buffer: Buffer.from("Just some notes") });
  await expect(page.getByRole("alert")).toHaveText(/The file is not a PDF/);

  await choose(page, join(CORPUS_DIR, "many_pages.pdf"));
  await expect(page.locator(".page canvas").first()).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("says when the server can't be reached", async ({ page }) => {
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.route("**/api/**", (route) => route.abort("connectionrefused"));
  await choose(page, join(CORPUS_DIR, "many_pages.pdf"));
  await expect(page.getByRole("alert")).toHaveText(/Cannot reach the PDF Redact server/);

  await page.unroute("**/api/**");
  await choose(page, join(CORPUS_DIR, "many_pages.pdf"));
  await expect(page.locator(".page canvas").first()).toBeVisible();
});

test("asks for the link with the session token when it is missing", async ({ page }) => {
  await page.goto("/");
  await choose(page, join(CORPUS_DIR, "many_pages.pdf"));
  await expect(page.getByRole("alert")).toHaveText(/Session expired\. Reopen the link printed by the server\./);
});
