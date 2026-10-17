import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { drag, inspectPdf, marks, openPdf, SECRET, selectText, toScreen } from "./helpers.ts";

async function download(page: Page, path: string, action: () => Promise<void>) {
  const pending = page.waitForEvent("download");
  await action();
  const file = await pending;
  await file.saveAs(path);
  return file.suggestedFilename();
}

async function menu(page: Page, item: string) {
  await page.getByRole("button", { name: "Project ▾" }).click();
  await page.getByRole("menuitem", { name: item }).click();
}

/** Open a PDF or project file through the toolbar or the Project menu. */
async function pick(page: Page, path: string, action: () => Promise<void>) {
  const chooser = page.waitForEvent("filechooser");
  await action();
  await (await chooser).setFiles(path);
}

test("saves the marks to a project and restores every one", async ({ page }, info) => {
  const text = await openPdf(page, "text_basic");
  await selectText(page, 0, text, SECRET);
  await drag(page, await toScreen(page, 0, 300, 400), await toScreen(page, 0, 400, 450));
  await expect(marks(page)).toHaveCount(2);

  const path = info.outputPath("text_basic.redact.json");
  const name = await download(page, path, () => page.keyboard.press("ControlOrMeta+s"));
  expect(name).toBe("text_basic.redact.json");
  const saved = JSON.parse(readFileSync(path, "utf8"));
  expect(saved).toMatchObject({ format: "pdf-redact-project", version: 1, document: { filename: "text_basic.pdf" } });
  expect(saved.marks).toHaveLength(2);

  // Saved marks are not lost by closing, so there is nothing to confirm.
  page.on("dialog", (d) => {
    throw new Error(`unexpected dialog: ${d.message()}`);
  });
  await page.getByRole("button", { name: "Close" }).click();
  await openPdf(page, "text_basic");
  await expect(marks(page)).toHaveCount(0);

  await pick(page, path, () => menu(page, "Load project…"));
  await expect(marks(page)).toHaveCount(2);
  await expect(page.getByRole("status")).toContainText("Loaded 2 marks from text_basic.redact.json");
  await expect(page.locator(".mark-item").first()).toContainText(SECRET);

  const again = info.outputPath("again.redact.json");
  await download(page, again, () => menu(page, "Save project"));
  expect(JSON.parse(readFileSync(again, "utf8")).marks).toEqual(saved.marks);
});

test("asks before loading a project saved for another file", async ({ page }, info) => {
  const text = await openPdf(page, "text_basic");
  await selectText(page, 0, text, SECRET);
  const path = info.outputPath("text_basic.redact.json");
  await download(page, path, () => menu(page, "Save project"));

  await page.getByRole("button", { name: "Close" }).click();
  await openPdf(page, "rotated_90");
  const dialog = page.waitForEvent("dialog");
  await pick(page, path, () => menu(page, "Load project…"));
  const confirm = await dialog;
  expect(confirm.message()).toContain("saved for “text_basic.pdf”");
  await confirm.dismiss();
  await expect(marks(page)).toHaveCount(0);
});

test("exports a marked PDF whose marks come back when it is opened", async ({ page }, info) => {
  const text = await openPdf(page, "text_basic");
  await selectText(page, 0, text, SECRET);
  await expect(marks(page)).toHaveCount(1);

  const path = info.outputPath("text_basic_marked.pdf");
  const name = await download(page, path, () => menu(page, "Export marked PDF"));
  expect(name).toBe("text_basic_marked.pdf");
  expect(inspectPdf(path).pages[0]).toContain(SECRET); // marked, not redacted

  await page.getByRole("button", { name: "Close" }).click();
  await pick(page, path, () => page.getByRole("button", { name: "Choose a file…" }).click());
  await expect(marks(page)).toHaveCount(1);
  await expect(marks(page).first()).toContainText(SECRET);
  await expect(page.locator(".notice-bar.info")).toContainText("added to the marks list");

  await page.getByRole("button", { name: "Apply 1 redaction…" }).click();
  await page.getByRole("button", { name: "Apply redactions" }).click();
  await expect(page.locator(".verdict")).toContainText("Verified");
});

/** Count strongly red pixels of the rendered page canvas inside a display-space rect. */
async function redPixels(page: Page, rect: number[]) {
  return page.locator('.page[data-page="0"] canvas').evaluate((canvas: HTMLCanvasElement, [x0, y0, x1, y1]) => {
    const scale = canvas.width / Number(canvas.closest(".page")!.querySelector("svg")!.getAttribute("viewBox")!.split(" ")[2]);
    const data = canvas.getContext("2d")!.getImageData(x0 * scale - 2, y0 * scale - 2, (x1 - x0) * scale + 4, (y1 - y0) * scale + 4).data;
    let red = 0;
    for (let i = 0; i < data.length; i += 4) if (data[i] > 180 && data[i + 1] < 90 && data[i + 2] < 90) red++;
    return red;
  }, rect);
}

test("opens a file's existing redaction annotations as marks", async ({ page }) => {
  await openPdf(page, "existing_redaction");
  await expect(marks(page)).toHaveCount(1);
  const box = page.locator(".mark .mark-box").first();
  const rect = await Promise.all(["x", "y", "width", "height"].map(async (a) => Number(await box.getAttribute(a))));
  rect[2] += rect[0];
  rect[3] += rect[1];
  await expect(page.getByRole("status").first()).toContainText("1 unapplied redaction mark");
  // The page canvas doesn't draw the annotation's red outline: the mark (in the SVG layer) stands for it.
  expect(await redPixels(page, rect)).toBe(0);
  // Nothing has changed, so closing needs no confirmation.
  page.on("dialog", (d) => {
    throw new Error(`unexpected dialog: ${d.message()}`);
  });
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("button", { name: "Choose a file…" })).toBeVisible();
});
