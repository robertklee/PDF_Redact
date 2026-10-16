import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import {
  applyAndDownload,
  drag,
  inspectPdf,
  marks,
  openPdf,
  SECRET,
  selectText,
  textSpans,
  toScreen,
} from "./helpers.ts";

const overlayText = (page: Page) => page.getByRole("textbox", { name: "Overlay text" });
const dialog = (page: Page) => page.getByRole("dialog", { name: "Code sets" });

test("labels redactions with codes in the chosen font and repeats them", async ({ page }, info) => {
  const text = await openPdf(page, "text_basic");
  await selectText(page, 0, text, SECRET);
  await expect(marks(page)).toHaveCount(1);
  const foia = page.getByRole("group", { name: "FOIA" });
  await foia.getByRole("button", { name: "(b)(7)(C)" }).click();
  await foia.getByRole("button", { name: "(b)(6)" }).click();
  await expect(overlayText(page)).toHaveValue("(b)(6), (b)(7)(C)");
  await expect(foia.getByRole("button", { name: "(b)(6)" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("combobox", { name: "Font", exact: true }).selectOption("Times");

  await page.keyboard.press("r");
  await drag(page, await toScreen(page, 0, 300, 300), await toScreen(page, 0, 500, 380));
  await page.getByRole("combobox", { name: "Code set" }).selectOption("Privacy Act");
  await page.getByRole("group", { name: "Privacy Act" }).getByRole("button", { name: "(k)(5)" }).click();
  await page.getByLabel("Fill each box with the text").check();
  await expect(overlayText(page)).toHaveValue("(k)(5)");

  // Both marks selected: (b)(6) is on one of them only.
  await marks(page).first().click();
  await marks(page).nth(1).click({ modifiers: ["Shift"] });
  await page.getByRole("combobox", { name: "Code set" }).selectOption("FOIA");
  await expect(foia.getByRole("button", { name: "(b)(6)" })).toHaveAttribute("aria-pressed", "mixed");
  await expect(overlayText(page)).toHaveAttribute("placeholder", "Mixed");

  await page.getByLabel("Preview").check();
  await expect(page.locator(".mark-overlay").filter({ hasText: "(k)(5) (k)(5)" }).first()).toBeVisible();
  expect(await page.locator(".mark-overlay").count()).toBeGreaterThan(2);
  await page.getByLabel("Preview").uncheck();

  const out = info.outputPath("codes.pdf");
  await applyAndDownload(page, out);
  expect(inspectPdf(out).pages[0]).not.toContain(SECRET);
  const spans = textSpans(out);
  expect(spans).toContainEqual(expect.objectContaining({ text: "(b)(6), (b)(7)(C)", font: "Times-Roman" }));
  const repeated = spans.filter((s) => s.text.startsWith("(k)(5) (k)(5)"));
  expect(repeated.length).toBeGreaterThan(1);
  expect(repeated.every((s) => s.font === "Helvetica")).toBe(true);
});

test("creates, exports, imports and deletes custom code sets", async ({ page }, info) => {
  await openPdf(page, "text_basic");
  await page.getByRole("button", { name: "Manage…" }).click();
  await dialog(page).getByRole("button", { name: "New set" }).click();
  await dialog(page).getByRole("textbox", { name: "Name" }).fill("Agency codes");
  await dialog(page).getByRole("button", { name: "+ Add code" }).click();
  await dialog(page).getByRole("textbox", { name: "Code 1" }).fill("EX-1");
  await dialog(page).getByRole("textbox", { name: "Description 1" }).fill("Internal only");
  await dialog(page).getByRole("button", { name: "+ Add code" }).click();
  await dialog(page).getByRole("textbox", { name: "Code 2" }).fill("EX-1");
  await expect(dialog(page).getByRole("alert")).toHaveText("“EX-1” appears more than once.");
  await expect(dialog(page).getByRole("button", { name: "Save" })).toBeDisabled();
  await dialog(page).getByRole("textbox", { name: "Code 2" }).fill("EX-2");
  await dialog(page).getByRole("button", { name: "Save" }).click();

  // Unsaved changes are kept unless the user agrees to drop them.
  await dialog(page).getByRole("textbox", { name: "Name" }).fill("Renamed");
  page.once("dialog", (d) => void d.dismiss());
  await dialog(page).getByRole("button", { name: "Close" }).click();
  await expect(dialog(page)).toBeVisible();
  await dialog(page).getByRole("button", { name: "Revert" }).click();
  await expect(dialog(page).getByRole("textbox", { name: "Name" })).toHaveValue("Agency codes");

  const download = page.waitForEvent("download");
  await dialog(page).getByRole("button", { name: "Export…" }).click();
  const file = info.outputPath("agency.codes.json");
  await (await download).saveAs(file);
  expect(JSON.parse(readFileSync(file, "utf8")).sets).toEqual([
    {
      name: "Agency codes",
      codes: [
        { code: "EX-1", description: "Internal only" },
        { code: "EX-2", description: "" },
      ],
    },
  ]);
  await dialog(page).getByRole("button", { name: "Close" }).click();

  const picker = page.getByRole("group", { name: "Agency codes" });
  await picker.getByRole("button", { name: "EX-2" }).click();
  await expect(overlayText(page)).toHaveValue("EX-2");

  await page.reload();
  await openPdf(page, "text_basic");
  await expect(page.getByRole("combobox", { name: "Code set" })).toHaveValue(/.+/);
  await expect(picker.getByRole("button", { name: "EX-1" })).toBeVisible();
  await page.getByRole("button", { name: "Manage…" }).click();
  page.once("dialog", (d) => void d.accept());
  await dialog(page).getByRole("button", { name: "Delete" }).click();
  await expect(dialog(page).getByRole("listbox", { name: "Code sets" }).getByRole("option")).toHaveText([
    "FOIA",
    "Privacy Act",
  ]);

  await dialog(page).locator("input[type=file]").setInputFiles(file);
  await expect(dialog(page).getByRole("status")).toHaveText("Imported 1 code set.");
  await expect(dialog(page).getByRole("textbox", { name: "Code 2" })).toHaveValue("EX-2");
  await dialog(page).locator("input[type=file]").setInputFiles({
    name: "bad.json",
    mimeType: "application/json",
    buffer: Buffer.from('{"sets": [{"name": "Bad", "codes": [{"code": "a,b"}]}]}'),
  });
  await expect(dialog(page).getByRole("alert")).toHaveText("Bad: “a,b”: codes cannot contain commas.");
});
