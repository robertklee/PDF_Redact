import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const assets = new URL("pdfjs/", document.baseURI).href;

export type { PDFDocumentProxy, PDFPageProxy };

/** Open a PDF for rendering only. The server does all text extraction and redaction. */
export function openPdf(data: Uint8Array, password?: string): Promise<PDFDocumentProxy> {
  return pdfjs.getDocument({
    // PDF.js transfers the buffer to its worker, so give it a copy.
    data: data.slice(),
    password,
    cMapUrl: `${assets}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${assets}standard_fonts/`,
    wasmUrl: `${assets}wasm/`,
    iccUrl: `${assets}iccs/`,
    enableXfa: false,
  }).promise;
}

/**
 * Stop drawing the file's own unapplied /Redact annotations on these pages: they are shown (and
 * edited, or removed) as marks instead.
 */
export async function hideRedactAnnotations(pdf: PDFDocumentProxy, pages: Iterable<number>) {
  for (const index of new Set(pages)) {
    const page = await pdf.getPage(index + 1);
    for (const annot of await page.getAnnotations()) {
      if (annot.subtype === "Redact") pdf.annotationStorage.setValue(annot.id, { noView: true });
    }
  }
}

/** Largest canvas we allocate per page, in device pixels (browsers cap canvas memory). */
const MAX_CANVAS_PIXELS = 4096 * 4096;

export function outputScale(width: number, height: number, zoom: number): number {
  const ratio = window.devicePixelRatio || 1;
  const pixels = width * height * zoom * zoom * ratio * ratio;
  return pixels > MAX_CANVAS_PIXELS ? ratio * Math.sqrt(MAX_CANVAS_PIXELS / pixels) : ratio;
}

/** Render a page into a fresh canvas sized for `zoom` (CSS pixels per point). */
export function renderPage(page: PDFPageProxy, zoom: number) {
  const base = page.getViewport({ scale: 1 });
  const scale = outputScale(base.width, base.height, zoom);
  const viewport = page.getViewport({ scale: zoom * scale });
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(viewport.width));
  canvas.height = Math.max(1, Math.floor(viewport.height));
  // With storage, so that annotations hidden by `hideRedactAnnotations` stay hidden.
  const task = page.render({ canvas, viewport, annotationMode: pdfjs.AnnotationMode.ENABLE_STORAGE });
  return { canvas, task };
}
