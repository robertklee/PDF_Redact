import { create } from "zustand";
import { api, ApiError } from "./api";
import { useMarks } from "./marks";
import { openPdf, type PDFDocumentProxy } from "./pdf";
import { useSearch } from "./search";
import type { DocumentInfo, PageText } from "./types";

export type Phase = "empty" | "opening" | "locked" | "ready";
export type FitMode = "width" | "page" | null;

export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 8;
export const ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 6, 8];

export interface ScrollRequest {
  page: number;
  /** Point (display space, PDF points) to bring into view; page top if omitted. */
  y?: number;
  seq: number;
}

interface State {
  phase: Phase;
  error: string | null;
  file: File | null;
  bytes: Uint8Array | null;
  doc: DocumentInfo | null;
  pdf: PDFDocumentProxy | null;

  zoom: number;
  fit: FitMode;
  currentPage: number;
  scrollRequest: ScrollRequest | null;
  showTextBoxes: boolean;
  pageText: Record<number, PageText | "loading" | "error">;

  openFile(file: File): Promise<void>;
  unlock(password: string): Promise<void>;
  closeDocument(): Promise<void>;
  setError(error: string | null): void;
  setZoom(zoom: number, fit?: FitMode): void;
  zoomBy(direction: 1 | -1): void;
  setCurrentPage(page: number): void;
  goToPage(page: number, y?: number): void;
  toggleTextBoxes(): void;
  loadPageText(page: number): Promise<PageText | null>;
}

const message = (err: unknown) =>
  err instanceof ApiError || err instanceof Error ? err.message : String(err);

const initialDocState = {
  phase: "empty" as Phase,
  file: null,
  bytes: null,
  doc: null,
  pdf: null,
  currentPage: 0,
  scrollRequest: null,
  pageText: {},
};

export const useStore = create<State>()((set, get) => ({
  ...initialDocState,
  error: null,
  zoom: 1,
  fit: "width",
  showTextBoxes: false,

  async openFile(file) {
    await get().closeDocument();
    set({ phase: "opening", error: null, file });
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const doc = await api.upload(file);
      if (doc.needsPassword) {
        set({ phase: "locked", doc, bytes });
        return;
      }
      const pdf = await openPdf(bytes);
      set({ phase: "ready", doc, bytes, pdf, fit: get().fit ?? "width" });
    } catch (err) {
      set({ ...initialDocState, error: message(err) });
    }
  },

  async unlock(password) {
    const { doc, bytes } = get();
    if (!doc || !bytes) return;
    const unlocked = await api.unlock(doc.id, password); // throws on a wrong password
    const pdf = await openPdf(bytes, password);
    set({ phase: "ready", doc: unlocked, pdf, error: null });
  },

  async closeDocument() {
    const { doc, pdf } = get();
    set({ ...initialDocState });
    useMarks.getState().reset();
    useSearch.getState().clearResults();
    await pdf?.loadingTask.destroy();
    if (doc) await api.close(doc.id).catch(() => undefined);
  },

  setError(error) {
    set({ error });
  },

  setZoom(zoom, fit = null) {
    set({ zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)), fit });
  },

  zoomBy(direction) {
    const { zoom } = get();
    const next =
      direction > 0
        ? (ZOOM_STEPS.find((z) => z > zoom + 1e-3) ?? MAX_ZOOM)
        : ([...ZOOM_STEPS].reverse().find((z) => z < zoom - 1e-3) ?? MIN_ZOOM);
    get().setZoom(next);
  },

  setCurrentPage(page) {
    if (page !== get().currentPage) set({ currentPage: page });
  },

  goToPage(page, y) {
    const count = get().doc?.pageCount ?? 0;
    if (!count) return;
    const target = Math.min(count - 1, Math.max(0, page));
    set({ scrollRequest: { page: target, y, seq: (get().scrollRequest?.seq ?? 0) + 1 } });
  },

  toggleTextBoxes() {
    set({ showTextBoxes: !get().showTextBoxes });
  },

  async loadPageText(page) {
    const { doc, pageText } = get();
    const cached = pageText[page];
    if (!doc || cached === "error") return null;
    if (cached && cached !== "loading") return cached;
    if (cached === "loading") return null;
    set({ pageText: { ...get().pageText, [page]: "loading" } });
    try {
      const text = await api.pageText(doc.id, page);
      if (get().doc?.id === doc.id) set({ pageText: { ...get().pageText, [page]: text } });
      return text;
    } catch {
      if (get().doc?.id === doc.id) set({ pageText: { ...get().pageText, [page]: "error" } });
      return null;
    }
  },
}));
