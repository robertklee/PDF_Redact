import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { expect, type Page } from "@playwright/test";
import type { PageText, Rect } from "../src/types.ts";
import { CORPUS_DIR, E2E_TOKEN, PYTHON } from "./env.ts";

export const SECRET = "TOPSECRET-4471";

/** Load the app with the session token, as the link printed by the server does, and pick a corpus PDF. */
export async function chooseFile(page: Page, name: string) {
  await page.goto(`/#token=${E2E_TOKEN}`);
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose a file…" }).click();
  await (await chooser).setFiles(join(CORPUS_DIR, `${name}.pdf`));
}

/** Open a corpus PDF and return the text of `textPage` as the UI received it. */
export async function openPdf(page: Page, name: string, textPage = 0): Promise<PageText> {
  const text = page.waitForResponse((r) => r.url().endsWith(`/pages/${textPage}/text`));
  await chooseFile(page, name);
  await expect(page.locator(".page canvas").first()).toBeVisible();
  return (await text).json();
}

export const marks = (page: Page) => page.locator(".mark-item");

/** Convert a display-space point (PDF points) on a page to viewport pixels. */
export async function toScreen(page: Page, index: number, x: number, y: number) {
  const pageBox = (await page.locator(`.page[data-page="${index}"]`).boundingBox())!;
  const viewBox = await page.locator(`.page[data-page="${index}"] svg.mark-layer`).getAttribute("viewBox");
  const zoom = pageBox.width / Number(viewBox!.split(" ")[2]);
  return { x: pageBox.x + x * zoom, y: pageBox.y + y * zoom };
}

export async function drag(page: Page, from: { x: number; y: number }, to: { x: number; y: number }) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 8 });
  await page.mouse.up();
}

/** Character boxes of the first occurrence of `needle` on the page. */
export function findText(text: PageText, needle: string): Rect[] {
  for (const line of text.lines) {
    const at = line.chars.join("").indexOf(needle);
    if (at >= 0) return line.boxes.slice(at, at + needle.length);
  }
  throw new Error(`"${needle}" not found`);
}

/** Select text by dragging along the reading direction from its first to its last character. */
export async function selectText(page: Page, index: number, text: PageText, needle: string) {
  const boxes = findText(text, needle);
  const line = text.lines.find((l) => l.chars.join("").includes(needle))!;
  const [dx, dy] = line.dir;
  const edge = (b: Rect, sign: number) => {
    const cx = (b[0] + b[2]) / 2;
    const cy = (b[1] + b[3]) / 2;
    const half = Math.abs(dx) * (b[2] - b[0]) * 0.45 + Math.abs(dy) * (b[3] - b[1]) * 0.45;
    return [cx + sign * dx * half, cy + sign * dy * half] as const;
  };
  const from = await toScreen(page, index, ...edge(boxes[0], -1));
  const to = await toScreen(page, index, ...edge(boxes[boxes.length - 1], 1));
  await drag(page, from, to);
}

export interface PdfSummary {
  encrypted: boolean;
  pages: string[];
}

/** Inspect a PDF with PyMuPDF, independently of the app: is it encrypted, and the text per page. */
export function inspectPdf(path: string, password = ""): PdfSummary {
  const script = [
    "import json, sys, pymupdf",
    "d = pymupdf.open(sys.argv[1])",
    "encrypted = d.is_encrypted",
    "encrypted and d.authenticate(sys.argv[2])",
    "print(json.dumps({'encrypted': encrypted, 'pages': [p.get_text() for p in d]}))",
  ].join("\n");
  return JSON.parse(execFileSync(PYTHON, ["-c", script, path, password], { encoding: "utf8" }));
}

export interface Span {
  page: number;
  text: string;
  font: string;
  size: number;
}

/** Text spans with their fonts, read with PyMuPDF. */
export function textSpans(path: string): Span[] {
  const script = [
    "import json, sys, pymupdf",
    "d = pymupdf.open(sys.argv[1])",
    "print(json.dumps([{'page': p.number, 'text': s['text'], 'font': s['font'], 'size': s['size']}",
    "  for p in d for b in p.get_text('dict')['blocks'] for l in b.get('lines', []) for s in l['spans']]))",
  ].join("\n");
  return JSON.parse(execFileSync(PYTHON, ["-c", script, path], { encoding: "utf8" }));
}

export interface PdfObjects {
  author: string;
  xmp: boolean;
  annotations: number;
}

/** Document metadata and annotation count, read with PyMuPDF. */
export function pdfObjects(path: string): PdfObjects {
  const script = [
    "import json, sys, pymupdf",
    "d = pymupdf.open(sys.argv[1])",
    "print(json.dumps({'author': d.metadata['author'], 'xmp': bool(d.get_xml_metadata()),",
    "  'annotations': sum(len(list(p.annots())) for p in d)}))",
  ].join("\n");
  return JSON.parse(execFileSync(PYTHON, ["-c", script, path], { encoding: "utf8" }));
}

/** Apply all marks with default options, check verification passed and save the download. */
export async function applyAndDownload(page: Page, path: string) {
  await page.getByRole("button", { name: /^Apply \d+ redactions?…$/ }).click();
  await page.getByRole("button", { name: "Apply redactions" }).click();
  await expect(page.locator(".verdict")).toContainText("Verified");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /^Download/ }).click();
  await (await download).saveAs(path);
  await page.getByRole("button", { name: "Done" }).click();
}
