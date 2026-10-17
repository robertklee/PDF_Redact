import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { marks, openPdf, SECRET, selectText } from "./helpers.ts";

async function saveDownload(page: Page, button: string, path: string) {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: button, exact: true }).click();
  const file = await download;
  await file.saveAs(path);
  return { name: file.suggestedFilename(), text: readFileSync(path, "utf8") };
}

test("downloads the report and audit log of an application", async ({ page }, info) => {
  const text = await openPdf(page, "text_basic");
  await selectText(page, 0, text, SECRET);
  await expect(marks(page)).toHaveCount(1);
  await page.getByRole("button", { name: "Apply 1 redaction…" }).click();
  await page.getByRole("button", { name: "Apply redactions" }).click();
  await expect(page.locator(".verdict")).toContainText("Verified");

  const html = await saveDownload(page, "Report", info.outputPath("report.html"));
  expect(html.name).toBe("text_basic_redaction_report.html");
  expect(html.text).toContain("Redaction report");
  expect(html.text).not.toContain(SECRET);
  await page.screenshot({ path: info.outputPath("dialog.png") });

  const csv = await saveDownload(page, "CSV", info.outputPath("log.csv"));
  expect(csv.name).toBe("text_basic_redaction_log.csv");
  expect(csv.text.split("\r\n")[0]).toContain("id,page,kind,source");

  await page.getByLabel("Removed text in reports").selectOption("plain");
  await expect(page.getByText("Reports will contain the redacted text")).toBeVisible();
  const log = await saveDownload(page, "Audit log", info.outputPath("log.json"));
  expect(log.name).toBe("text_basic_redaction_log.json");
  const audit = JSON.parse(log.text);
  expect(audit.textInReport).toBe("plain");
  expect(audit.marks).toHaveLength(1);
  expect(audit.marks[0]).toMatchObject({ page: 1, kind: "text", source: "manual", text: SECRET, status: "pass" });
  expect(Date.parse(audit.marks[0].createdAt)).toBeLessThanOrEqual(Date.parse(audit.appliedAt) + 1000);
});
