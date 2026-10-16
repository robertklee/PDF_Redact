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
  createdAt: string;
}

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
