import { expect, type Page, test } from "@playwright/test";
import { marks, openPdf, pdfObjects, SECRET, selectText } from "./helpers.ts";

const dialog = (page: Page) => page.getByRole("dialog");

test("removes hidden information from a document without marks", async ({ page }, info) => {
  await openPdf(page, "kitchen_sink");
  await page.getByRole("button", { name: "Remove hidden information…" }).click();
  await expect(dialog(page).getByRole("heading")).toHaveText("Remove hidden information");
  await expect(dialog(page).getByText("Images under marks")).toHaveCount(0);
  await expect(dialog(page).getByRole("checkbox", { name: /^Document properties and metadata/ })).toBeChecked();
  await dialog(page).getByLabel("Comments and markup").selectOption("keep");
  await expect(dialog(page).getByText("What is removed (changed)")).toBeVisible();

  await dialog(page).getByRole("button", { name: "Remove hidden information", exact: true }).click();
  await expect(page.locator(".verdict")).toHaveText("Verified: the hidden information is no longer in the file.");
  await expect(page.locator(".stats")).toContainText(/Removed \d+ metadata entries/);
  await expect(page.locator(".stats")).not.toContainText("characters removed");

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /^Download/ }).click();
  const out = info.outputPath("sanitized.pdf");
  await (await download).saveAs(out);
  const result = pdfObjects(out);
  expect(result.author).toBe("");
  expect(result.xmp).toBe(false);
  expect(result.annotations).toBe(2); // comments were kept
});

test("remembers the choice to leave hidden information in place", async ({ page }, info) => {
  const text = await openPdf(page, "metadata");
  await selectText(page, 0, text, SECRET);
  await expect(marks(page)).toHaveCount(1);
  await page.getByRole("button", { name: "Apply 1 redaction…" }).click();
  const remove = dialog(page).getByRole("checkbox", { name: /^Also remove hidden information/ });
  await expect(remove).toBeChecked();
  await remove.uncheck();
  await expect(dialog(page).getByText("What is removed")).toHaveCount(0);

  await dialog(page).getByRole("button", { name: "Apply redactions" }).click();
  await expect(page.locator(".verdict")).toContainText("Verified");
  await expect(page.locator(".stats")).not.toContainText(/metadata|hidden information/);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /^Download/ }).click();
  const out = info.outputPath("not_sanitized.pdf");
  await (await download).saveAs(out);
  expect(pdfObjects(out).author).toBe(SECRET);

  await page.reload();
  const again = await openPdf(page, "metadata");
  await selectText(page, 0, again, SECRET);
  await page.getByRole("button", { name: "Apply 1 redaction…" }).click();
  await expect(remove).not.toBeChecked();
});
