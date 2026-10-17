import { expect, test } from "@playwright/test";
import { openPdf, SECRET } from "./helpers.ts";

// Searching and applying on 400 pages take long enough to watch their progress and cancel them.
test("long searches and redactions show progress and can be cancelled", async ({ page }) => {
  test.setTimeout(120_000);
  await openPdf(page, "large");
  await page.keyboard.press("ControlOrMeta+f");
  await page.keyboard.type(SECRET);
  await page.keyboard.press("Enter");

  const searching = page.locator(".search-form .job-progress");
  await expect(searching.getByRole("status")).toHaveText(/^(Reading the text|Searching)…$/);
  await expect(searching.getByRole("progressbar")).toBeVisible();
  await searching.getByRole("button", { name: "Cancel" }).click();
  await expect(searching).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Find" })).toBeEnabled();
  await expect(page.locator(".results-header")).toHaveCount(0);

  await page.getByRole("button", { name: "Find" }).click();
  await expect(page.locator(".results-header [role=status]")).toHaveText("80 results on 80 pages", { timeout: 60_000 });
  await page.getByRole("button", { name: "Mark 80 selected" }).click();

  await page.getByRole("button", { name: "Apply 80 redactions…" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Apply redactions" }).click();
  const applying = dialog.locator(".job-progress");
  await expect(applying.getByRole("status")).toHaveText(/^Applying redactions…$/);
  await expect(applying.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expect(applying.getByText(/^\d+%$/)).toBeVisible();
  await page.keyboard.press("Escape");

  // Back to the confirmation, with no error and the dialog still open.
  await expect(dialog.getByRole("button", { name: "Apply redactions" })).toBeEnabled();
  await expect(applying).toHaveCount(0);
  await expect(dialog.getByRole("alert")).toHaveCount(0);
});
