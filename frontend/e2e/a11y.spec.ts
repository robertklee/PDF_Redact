import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "./env.ts";
import { chooseFile, openPdf, SECRET } from "./helpers.ts";

/** Fail on any WCAG 2.1 A/AA violation in what is on screen. */
async function checkA11y(page: Page, state: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const summary = violations.map((v) => `${v.id}: ${v.help}\n  ${v.nodes.map((n) => n.target.join(" ")).join("\n  ")}`);
  expect.soft(summary, `accessibility violations in ${state}`).toEqual([]);
}

test("the open screen and the password prompt are accessible", async ({ page }) => {
  await page.goto(`/#token=${E2E_TOKEN}`);
  await checkA11y(page, "the open screen");
  await chooseFile(page, "encrypted");
  await expect(page.getByRole("dialog", { name: "Password required" })).toBeVisible();
  await checkA11y(page, "the password prompt");
});

test("the workspace, search, dialogs and results are accessible", async ({ page }) => {
  await openPdf(page, "personal_info");
  await checkA11y(page, "the workspace");

  await page.keyboard.press("ControlOrMeta+f");
  await page.keyboard.type(SECRET);
  await page.keyboard.press("Enter");
  await expect(page.locator(".results-header [role=status]")).toHaveText("2 results on 2 pages");
  await checkA11y(page, "search results");
  await page.getByRole("button", { name: "Mark 2 selected" }).click();
  await page.getByRole("button", { name: "Personal info" }).click();
  await checkA11y(page, "the personal info search");

  await page.getByRole("tab", { name: /Marks/ }).click();
  await page.locator(".mark-item").first().click();
  await checkA11y(page, "a selected mark");

  await page.getByRole("button", { name: "Manage…" }).click();
  await expect(page.getByRole("dialog", { name: "Code sets" })).toBeVisible();
  await checkA11y(page, "the code sets dialog");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Mark pages…" }).click();
  await expect(page.getByRole("dialog", { name: "Mark pages" })).toBeVisible();
  await checkA11y(page, "the mark pages dialog");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Project ▾" }).click();
  await checkA11y(page, "the project menu");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: /^Apply \d+ redactions?…$/ }).click();
  await expect(page.getByRole("dialog", { name: "Apply redactions" })).toBeVisible();
  await checkA11y(page, "the apply dialog");
  await page.getByRole("button", { name: "Apply redactions" }).click();
  await expect(page.locator(".verdict")).toContainText("Verified");
  await checkA11y(page, "the verification result");
});

test("dialogs keep and restore the focus, and the marks list works from the keyboard", async ({ page }) => {
  await openPdf(page, "many_pages");
  const markPages = page.getByRole("button", { name: "Mark pages…" });
  await markPages.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Mark pages" });
  await expect(dialog.getByRole("textbox", { name: /^Pages/ })).toBeFocused();
  for (let i = 0; i < 5; i++) await page.keyboard.press("Tab");
  await expect(dialog.locator(":focus")).toHaveCount(1); // the focus never leaves the dialog
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(markPages).toBeFocused();

  await page.keyboard.press("Enter");
  await page.keyboard.type("1-3");
  await page.keyboard.press("Enter");
  await expect(markPages).toBeFocused();

  const list = page.getByRole("listbox", { name: "Marks" });
  const options = list.getByRole("option");
  await expect(options).toHaveCount(3);
  await options.first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(options.nth(1)).toBeFocused();
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Shift+ArrowDown");
  await expect(list.locator('[aria-selected="true"]')).toHaveCount(2);
  await page.keyboard.press("Delete");
  await expect(options).toHaveCount(1);
  await expect(options.first()).toBeFocused();
  await expect(list.getByRole("group", { name: "Page 1" })).toBeVisible();
});
