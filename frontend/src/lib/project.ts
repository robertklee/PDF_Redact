import { DEFAULT_APPEARANCE, isAppearance } from "../marks";
import type { DocumentInfo, Mark, MarkKind, MarkSource, Rect } from "../types";

/** Unapplied marks saved next to the PDF, to carry on later. */
export const PROJECT_FORMAT = "pdf-redact-project";
export const PROJECT_VERSION = 1;
export const PROJECT_SUFFIX = ".redact.json";

const KINDS: MarkKind[] = ["text", "area", "page"];
const SOURCES: MarkSource[] = ["manual", "search", "detect", "import"];
const ANGLES = [0, 90, 180, 270];
const MAX_RECTS = 10_000;

export interface Project {
  format: typeof PROJECT_FORMAT;
  version: number;
  savedAt: string;
  document: { filename: string; sha256: string; pageCount: number };
  marks: Mark[];
}

export interface LoadedProject {
  marks: Mark[];
  /** Marks that could not be used (on pages the document lacks, or malformed). */
  skipped: number;
  /** The file the project was saved for, when it is not the open document. */
  otherFile: string | null;
}

export class ProjectError extends Error {}

export function projectFilename(pdfName: string): string {
  return pdfName.replace(/\.pdf$/i, "") + PROJECT_SUFFIX;
}

export function isProjectFile(file: File): boolean {
  return file.name.toLowerCase().endsWith(".json") || file.type === "application/json";
}

export function serializeProject(doc: DocumentInfo, marks: Mark[], now = new Date()): string {
  const project: Project = {
    format: PROJECT_FORMAT,
    version: PROJECT_VERSION,
    savedAt: now.toISOString(),
    document: { filename: doc.filename, sha256: doc.sha256, pageCount: doc.pageCount },
    marks,
  };
  return JSON.stringify(project, null, 2) + "\n";
}

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

function parseRect(value: unknown): Rect | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  if (!value.every((v) => typeof v === "number" && Number.isFinite(v))) return null;
  const [x0, y0, x1, y1] = value as number[];
  const rect: Rect = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
  return rect[2] > rect[0] && rect[3] > rect[1] ? rect : null;
}

/** A usable mark from the project file, or null. Missing details get defaults rather than losing the mark. */
function parseMark(value: unknown, doc: DocumentInfo, ids: Set<string>, now: string): Mark | null {
  if (!isObject(value)) return null;
  const { page, kind } = value;
  if (typeof page !== "number" || !Number.isInteger(page) || page < 0 || page >= doc.pageCount) return null;
  if (!KINDS.includes(kind as MarkKind)) return null;
  const rects: Rect[] = [];
  if (kind !== "page") {
    if (!Array.isArray(value.rects) || value.rects.length > MAX_RECTS) return null;
    for (const r of value.rects) {
      const rect = parseRect(r);
      if (rect) rects.push(rect);
    }
    if (!rects.length) return null;
  }

  let id = typeof value.id === "string" && value.id.length > 0 && value.id.length <= 100 ? value.id : "";
  if (!id || ids.has(id)) id = crypto.randomUUID();
  ids.add(id);
  const appearance = isObject(value.appearance) ? { ...DEFAULT_APPEARANCE, ...value.appearance } : null;
  const mark: Mark = {
    id,
    page,
    kind: kind as MarkKind,
    rects,
    appearance: isAppearance(appearance) ? appearance : { ...DEFAULT_APPEARANCE },
    source: SOURCES.includes(value.source as MarkSource) ? (value.source as MarkSource) : "manual",
    createdAt: typeof value.createdAt === "string" && value.createdAt.length <= 40 ? value.createdAt : now,
  };
  if (typeof value.text === "string") mark.text = value.text;
  if (ANGLES.includes(value.angle as number)) mark.angle = value.angle as number;
  if (typeof value.category === "string") mark.category = value.category.slice(0, 100);
  return mark;
}

/** Read a saved project for the open document. Throws ProjectError if it is not a usable project file. */
export function parseProject(text: string, doc: DocumentInfo, now = new Date()): LoadedProject {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ProjectError("The file is not a PDF Redact project (it is not valid JSON).");
  }
  if (!isObject(data) || data.format !== PROJECT_FORMAT || !Array.isArray(data.marks)) {
    throw new ProjectError("The file is not a PDF Redact project.");
  }
  if (typeof data.version !== "number" || data.version > PROJECT_VERSION) {
    throw new ProjectError("The project was saved by a newer version of PDF Redact.");
  }
  const saved = isObject(data.document) ? data.document : {};
  const otherFile =
    saved.sha256 === doc.sha256 ? null : typeof saved.filename === "string" ? saved.filename : "another file";

  const ids = new Set<string>();
  const marks: Mark[] = [];
  for (const item of data.marks) {
    const mark = parseMark(item, doc, ids, now.toISOString());
    if (mark) marks.push(mark);
  }
  return { marks, skipped: data.marks.length - marks.length, otherFile };
}

/** The document's own unapplied /Redact annotations, as marks. */
export function importedMarks(doc: DocumentInfo, now = new Date()): Mark[] {
  const createdAt = now.toISOString();
  return (doc.redactions ?? []).map((r) => ({
    id: r.id,
    page: r.page,
    kind: r.kind,
    rects: r.rects,
    appearance: r.appearance,
    text: r.text || undefined,
    angle: r.angle ?? undefined,
    source: "import",
    createdAt,
  }));
}
