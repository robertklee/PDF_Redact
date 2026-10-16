import { expect, type Page, test } from "@playwright/test";
import { applyAndDownload, inspectPdf, marks, openPdf, SECRET } from "./helpers.ts";

const status = (page: Page) => page.locator(".results-header [role=status]");

/** Open the search panel with the keyboard and wait until typing goes into the search box. */
async function openSearch(page: Page) {
  await page.keyboard.press("ControlOrMeta+f");
  await expect(page.getByRole("searchbox", { name: "Find text" })).toBeFocused();
}

test("finds text on every page and redacts all hits", async ({ page }, info) => {
  await openPdf(page, "personal_info");
  await openSearch(page);
  await page.keyboard.type(SECRET.toLowerCase());
  await page.keyboard.press("Enter");
  await expect(status(page)).toHaveText("2 results on 2 pages");
  await expect(page.locator('.page[data-page="0"] .search-hit')).toHaveCount(1);

  await page.getByRole("button", { name: "Mark 2 selected" }).click();
  await expect(status(page)).toHaveText("2 results on 2 pages, 2 marked");
  await page.getByRole("tab", { name: /Marks/ }).click();
  await expect(marks(page)).toHaveCount(2);

  const out = info.outputPath("search.pdf");
  await applyAndDownload(page, out);
  const result = inspectPdf(out);
  expect(result.pages.join("\n")).not.toContain(SECRET);
  expect(result.pages[0]).toContain("Case reference");
  expect(result.pages[1]).toContain("Card on file");
});

test("warns when a marked search result still appears elsewhere", async ({ page }) => {
  await openPdf(page, "personal_info");
  await openSearch(page);
  await page.keyboard.type(SECRET);
  await page.keyboard.press("Enter");
  await page.getByRole("checkbox", { name: "Select results on page 2" }).uncheck();
  await page.getByRole("button", { name: "Mark 1 selected" }).click();

  await page.getByRole("button", { name: "Apply 1 redaction…" }).click();
  await page.getByRole("button", { name: "Apply redactions" }).click();
  await expect(page.locator(".verdict")).toHaveText("Marked text was removed. 1 warning to review.");
  await expect(page.locator(".check.warn")).toContainText(
    `Page 2Marked search result “${SECRET}” still appears on page 2`,
  );
  await expect(page.getByRole("button", { name: /^Download/ })).toBeEnabled();
});

test("matches a word hyphenated across lines", async ({ page }, info) => {
  await openPdf(page, "personal_info");
  await openSearch(page);
  await page.keyboard.type("international");
  await page.keyboard.press("Enter");
  await expect(status(page)).toHaveText("1 result on 1 page");
  await expect(page.locator(".search-hit")).toHaveCount(2);
  await page.getByRole("button", { name: "Mark 1 selected" }).click();

  const out = info.outputPath("hyphen.pdf");
  await applyAndDownload(page, out);
  const text = inspectPdf(out).pages[0];
  expect(text).not.toContain("inter-");
  expect(text).not.toContain("national");
  expect(text).toContain("review of the file.");
});

test("detects personal information and redacts the chosen hits", async ({ page }, info) => {
  await openPdf(page, "personal_info");
  await page.getByRole("tab", { name: /Search/ }).click();
  await page.getByRole("button", { name: "Personal info" }).click();
  await page.getByRole("textbox", { name: "Keywords" }).fill("Jane Q. Doe");
  await page.getByRole("button", { name: "Find", exact: true }).click();
  await expect(status(page)).toHaveText("8 results on 2 pages");
  await expect(page.locator(".hit .chip")).toHaveText([
    "Keyword",
    "SSN",
    "Phone",
    "Email",
    "Address",
    "Email",
    "Phone",
    "Card",
  ]);

  await page.getByRole("checkbox", { name: /Pennsylvania/ }).uncheck();
  await page.getByRole("button", { name: "Mark 7 selected" }).click();
  await expect(status(page)).toHaveText("8 results on 2 pages, 7 marked");

  const out = info.outputPath("pii.pdf");
  await applyAndDownload(page, out);
  const [first, second] = inspectPdf(out).pages;
  for (const value of ["Jane Q. Doe", "123-45-6789", "(202) 555-0143", "jane.doe@example.com"]) {
    expect(first).not.toContain(value);
  }
  for (const value of ["john.smith@example.org", "415-555-2671", "4111 1111 1111 1111"]) {
    expect(second).not.toContain(value);
  }
  expect(first).toContain("1600 Pennsylvania Avenue");
  expect(first).toContain("Applicant:");
});

test("reports invalid patterns and page ranges", async ({ page }) => {
  await openPdf(page, "personal_info");
  await openSearch(page);
  await page.getByRole("checkbox", { name: "Regex" }).check();
  await page.getByRole("searchbox", { name: "Find text" }).fill("[unclosed");
  await page.getByRole("searchbox", { name: "Find text" }).press("Enter");
  await expect(page.locator(".search-form .error")).toContainText("Invalid regular expression");

  await page.getByRole("combobox", { name: "Pages to search" }).selectOption("range");
  await page.getByRole("textbox", { name: "Page range" }).fill("3");
  await page.getByRole("button", { name: "Find", exact: true }).click();
  await expect(page.locator(".search-form .error")).toHaveText("Page 3 does not exist; the document has 2 pages");
});
