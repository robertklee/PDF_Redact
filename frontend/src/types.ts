/** Rectangle [x0, y0, x1, y1] in display space: PDF points, top-left origin, page rotation applied.
 * This equals the PDF.js viewport at scale 1, so screen pixels = points × zoom. */
export type Rect = [number, number, number, number];

export type MarkKind = "text" | "area" | "page";
export type Align = "left" | "center" | "right";

export interface Appearance {
  fill: string | null;
  textColor: string;
  overlayText: string;
  fontSize: number | null; // null = auto-fit
  align: Align;
}

export interface Mark {
  id: string;
  page: number;
  kind: MarkKind;
  rects: Rect[];
  appearance: Appearance;
  /** Selected text, kept in the browser only for the marks list. Never sent to the server. */
  text?: string;
  /** Display-space writing angle of the marked text (0/90/180/270), for the overlay preview. */
  angle?: number;
  /** How the mark was made; search and detection marks also record what matched. */
  source?: MarkSource;
  category?: string;
  createdAt: string;
}

export type MarkSource = "manual" | "search" | "detect";

export interface PageInfo {
  index: number;
  width: number;
  height: number;
  rotation: number;
}

export interface Notice {
  code: string;
  level: "info" | "warning";
  message: string;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  size: number;
  sha256: string;
  needsPassword: boolean;
  pageCount: number;
  pages: PageInfo[];
  notices: Notice[];
}

export interface TextLine {
  bbox: Rect;
  chars: string[];
  boxes: Rect[];
  /** Display-space unit writing direction. */
  dir: [number, number];
}

export interface PageText {
  index: number;
  width: number;
  height: number;
  lines: TextLine[];
  hasText: boolean;
  unmappedChars: number;
}

export type ImageMode = "pixels" | "remove" | "none";
export type GraphicsMode = "covered" | "touched" | "none";

export interface ApplyOptions {
  images: ImageMode;
  graphics: GraphicsMode;
}

export interface Check {
  name: string;
  status: "pass" | "warn" | "fail";
  message: string;
  page: number | null;
  markId: string | null;
}

export interface OutputInfo {
  id: string;
  documentId: string;
  filename: string;
  size: number;
  sha256: string;
  stats: {
    marks: number;
    rects: number;
    pages: number[];
    glyphsRemoved: number;
    textMarksAsArea: string[];
    safetyPassGlyphs: number;
  };
  verification: {
    passed: boolean;
    counts: Record<"pass" | "warn" | "fail", number>;
    checks: Check[];
  };
}

export type SearchMode = "phrase" | "word" | "regex";

export interface SearchRequest {
  query: string;
  mode: SearchMode;
  caseSensitive: boolean;
  /** Zero-based pages to search; all pages if omitted. */
  pages?: number[];
}

export interface CustomPattern {
  name: string;
  pattern: string;
}

export interface DetectRequest {
  categories: string[];
  keywords: string[];
  patterns: CustomPattern[];
  pages?: number[];
}

/** A search or detection hit, with the geometry of a text mark covering it. */
export interface SearchMatch {
  page: number;
  rects: Rect[];
  text: string;
  angle: number | null;
  before: string;
  after: string;
  /** Detector id, "keyword" or "custom:<name>" (detection only). */
  category: string | null;
}

export interface SearchResponse {
  matches: SearchMatch[];
  truncated: boolean;
}

export interface Detector {
  id: string;
  label: string;
  short: string;
  description: string;
  default: boolean;
}
