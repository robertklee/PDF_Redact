import { expect, test } from "@playwright/test";
import {
  applyAndDownload,
  chooseFile,
  drag,
  findText,
  inspectPdf,
  marks,
  openPdf,
  SECRET,
  selectText,
  toScreen,
} from "./helpers.ts";

test("redacts selected text with an overlay and verifies the download", async ({ page }, info) => {
  const text = await openPdf(page, "text_basic");
  await selectText(page, 0, text, SECRET);
  await expect(marks(page)).toHaveCount(1);
  await expect(marks(page).first()).toContainText(SECRET);

  await page.getByLabel("Overlay text").fill("(b)(6)");
  await page.getByLabel("Overlay text").blur();
  const out = info.outputPath("text_basic_redacted.pdf");
  await applyAndDownload(page, out);

  const result = inspectPdf(out);
  expect(result.pages[0]).not.toContain(SECRET);
  expect(result.pages[0]).toContain("Visible line above");
  expect(result.pages[0]).toContain("Visible line below");
  expect(result.pages[0]).toContain("(b)(6)");

  // Everything was applied and downloaded, so closing does not ask for confirmation.
  page.on("dialog", () => {
    throw new Error("unexpected confirmation");
  });
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("button", { name: "Choose a file…" })).toBeVisible();
});

test("marks areas, words and lines with undo, redo and delete", async ({ page }) => {
  const text = await openPdf(page, "text_basic");

  await page.keyboard.press("r");
  await drag(page, await toScreen(page, 0, 300, 300), await toScreen(page, 0, 400, 360));
  await expect(marks(page)).toHaveCount(1);
  await expect(marks(page).first()).toContainText("100 × 60 pt");

  await page.keyboard.press("t");
  const word = findText(text, "Visible line above")[2];
  const wordAt = await toScreen(page, 0, (word[0] + word[2]) / 2, (word[1] + word[3]) / 2);
  await page.mouse.dblclick(wordAt.x, wordAt.y);
  await expect(marks(page).filter({ hasText: "“Visible”" })).toHaveCount(1);

  const line = findText(text, "Visible line below")[3];
  const lineAt = await toScreen(page, 0, (line[0] + line[2]) / 2, (line[1] + line[3]) / 2);
  await page.mouse.click(lineAt.x, lineAt.y, { clickCount: 3, delay: 30 });
  await expect(marks(page).filter({ hasText: "“Visible line below”" })).toHaveCount(1);
  await expect(marks(page)).toHaveCount(3);

  // Double- then triple-clicking is one undo step.
  await page.keyboard.press("ControlOrMeta+z");
  await expect(marks(page)).toHaveCount(2);
  await expect(marks(page).filter({ hasText: "Visible line below" })).toHaveCount(0);
  await page.keyboard.press("ControlOrMeta+Shift+z");
  await expect(marks(page)).toHaveCount(3);
  await expect(marks(page).filter({ hasText: "“Visible line below”" })).toHaveCount(1);

  await marks(page).filter({ hasText: "100 × 60 pt" }).click();
  await page.keyboard.press("Delete");
  await expect(marks(page)).toHaveCount(2);
  await expect(page.locator(".thumb-badge").first()).toHaveText("2");
});

test("moves and resizes an area mark with the select tool", async ({ page }) => {
  await openPdf(page, "text_basic");
  await page.keyboard.press("r");
  await drag(page, await toScreen(page, 0, 300, 300), await toScreen(page, 0, 400, 360));
  await page.keyboard.press("v");
  await drag(page, await toScreen(page, 0, 350, 330), await toScreen(page, 0, 380, 350));
  await drag(page, await toScreen(page, 0, 430, 380), await toScreen(page, 0, 470, 400));
  await expect(marks(page).first()).toContainText("140 × 80 pt");
  await page.keyboard.press("ControlOrMeta+z");
  await expect(marks(page).first()).toContainText("100 × 60 pt");
});

test("marks whole pages, previews and removes their content", async ({ page }, info) => {
  await openPdf(page, "many_pages");
  await page.getByRole("button", { name: "Mark pages…" }).click();
  await page.getByRole("textbox", { name: /^Pages/ }).fill("2-3, 50");
  await page.getByRole("button", { name: "Mark 3 pages" }).click();
  await expect(marks(page)).toHaveCount(3);

  await page.getByLabel("Preview").check();
  await expect(page.locator('.page[data-page="1"] .mark-final')).toBeVisible();
  await page.getByLabel("Preview").uncheck();

  const out = info.outputPath("many_pages_redacted.pdf");
  await applyAndDownload(page, out);
  const result = inspectPdf(out);
  expect(result.pages).toHaveLength(50);
  for (const i of [1, 2, 49]) expect(result.pages[i].trim()).toBe("");
  expect(result.pages[0]).toContain(SECRET);
  expect(result.pages[3]).toContain(SECRET);
});

test("redacts text on a rotated page", async ({ page }, info) => {
  const text = await openPdf(page, "rotated_90");
  await selectText(page, 0, text, SECRET);
  await expect(marks(page).first()).toContainText(SECRET);
  const out = info.outputPath("rotated_redacted.pdf");
  await applyAndDownload(page, out);
  const result = inspectPdf(out);
  expect(result.pages[0]).not.toContain(SECRET);
  expect(result.pages[0]).toContain("Visible line above");
});

test("unlocks an encrypted PDF and keeps its protection", async ({ page }, info) => {
  await chooseFile(page, "encrypted");

  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.locator(".modal .error")).toBeVisible();

  const textResponse = page.waitForResponse((r) => r.url().endsWith("/pages/0/text"));
  await page.getByLabel("Password").fill("user-pw");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  const text = await (await textResponse).json();
  await selectText(page, 0, text, SECRET);

  const out = info.outputPath("encrypted_redacted.pdf");
  await applyAndDownload(page, out);
  const result = inspectPdf(out, "user-pw");
  expect(result.encrypted).toBe(true);
  expect(result.pages[0]).not.toContain(SECRET);
  expect(result.pages[0]).toContain("Visible line below");
});

test("asks before discarding marks that were not applied", async ({ page }) => {
  await openPdf(page, "text_basic");
  await page.keyboard.press("r");
  await drag(page, await toScreen(page, 0, 100, 300), await toScreen(page, 0, 200, 360));

  page.once("dialog", (d) => void d.dismiss());
  await page.getByRole("button", { name: "Close" }).click();
  await expect(marks(page)).toHaveCount(1);

  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("button", { name: "Choose a file…" })).toBeVisible();
});
