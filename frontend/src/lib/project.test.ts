import { describe, expect, it } from "vitest";
import { DEFAULT_APPEARANCE } from "../marks";
import type { DocumentInfo, Mark } from "../types";
import { importedMarks, parseProject, ProjectError, projectFilename, serializeProject } from "./project";

const doc: DocumentInfo = {
  id: "d1",
  filename: "case.pdf",
  size: 100,
  sha256: "abc",
  needsPassword: false,
  pageCount: 2,
  pages: [],
  notices: [],
  redactions: [],
};

const mark = (over: Partial<Mark> = {}): Mark => ({
  id: "m1",
  page: 0,
  kind: "text",
  rects: [[10, 20, 30, 40]],
  appearance: { ...DEFAULT_APPEARANCE, overlayText: "(b)(6)" },
  text: "secret",
  angle: 90,
  source: "detect",
  category: "SSN",
  createdAt: "2024-01-02T03:04:05.000Z",
  ...over,
});

const NOW = new Date("2024-06-01T00:00:00Z");

describe("project files", () => {
  it("names the file after the PDF", () => {
    expect(projectFilename("case.PDF")).toBe("case.redact.json");
    expect(projectFilename("notes")).toBe("notes.redact.json");
  });

  it("restores every mark it saved", () => {
    const marks = [mark(), mark({ id: "m2", kind: "page", rects: [], page: 1 }), mark({ id: "m3", kind: "area" })];
    const text = serializeProject(doc, marks, NOW);
    expect(JSON.parse(text)).toMatchObject({
      format: "pdf-redact-project",
      version: 1,
      savedAt: NOW.toISOString(),
      document: { filename: "case.pdf", sha256: "abc", pageCount: 2 },
    });
    expect(parseProject(text, doc)).toEqual({ marks, skipped: 0, otherFile: null });
  });

  it("rejects files that are not projects", () => {
    expect(() => parseProject("{oops", doc)).toThrow(ProjectError);
    expect(() => parseProject('{"marks": []}', doc)).toThrow(/not a PDF Redact project/);
    expect(() => parseProject(JSON.stringify({ format: "pdf-redact-project", version: 2, marks: [] }), doc)).toThrow(
      /newer version/,
    );
  });

  it("reports a project saved for another file", () => {
    const text = serializeProject({ ...doc, sha256: "other", filename: "old.pdf" }, [mark()]);
    expect(parseProject(text, doc).otherFile).toBe("old.pdf");
  });

  it("skips unusable marks and repairs the rest", () => {
    const project = JSON.parse(serializeProject(doc, []));
    project.marks = [
      mark({ page: 5 }), // no such page
      { ...mark(), kind: "circle" },
      { ...mark(), rects: [[1, 2, 3, Number.NaN as unknown as number]] },
      { ...mark(), rects: "nope" },
      "junk",
      { page: 0, kind: "area", rects: [[30, 40, 10, 20], [0, 0, 0, 5]], appearance: { fill: "red" } },
      mark({ id: "dup" }),
      mark({ id: "dup", angle: 45, source: "magic" as Mark["source"] }),
    ];
    const { marks, skipped } = parseProject(JSON.stringify(project), doc, NOW);
    expect(skipped).toBe(5);
    expect(marks).toHaveLength(3);
    const [repaired, first, second] = marks;
    expect(repaired.rects).toEqual([[10, 20, 30, 40]]);
    expect(repaired.appearance).toEqual(DEFAULT_APPEARANCE);
    expect(repaired.source).toBe("manual");
    expect(repaired.createdAt).toBe(NOW.toISOString());
    expect(repaired.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(first.id).toBe("dup");
    expect(second.id).not.toBe("dup");
    expect(second.angle).toBeUndefined();
    expect(second.source).toBe("manual");
  });

  it("turns the document's redaction annotations into marks", () => {
    const withAnnots: DocumentInfo = {
      ...doc,
      redactions: [
        {
          id: "a",
          page: 1,
          kind: "text",
          rects: [[1, 2, 3, 4]],
          appearance: DEFAULT_APPEARANCE,
          text: "Jane",
          angle: null,
          source: "import",
        },
        { id: "b", page: 0, kind: "area", rects: [[1, 2, 3, 4]], appearance: DEFAULT_APPEARANCE, text: "", angle: 0, source: "import" },
      ],
    };
    expect(importedMarks(withAnnots, NOW)).toEqual([
      {
        id: "a",
        page: 1,
        kind: "text",
        rects: [[1, 2, 3, 4]],
        appearance: DEFAULT_APPEARANCE,
        text: "Jane",
        angle: undefined,
        source: "import",
        createdAt: NOW.toISOString(),
      },
      {
        id: "b",
        page: 0,
        kind: "area",
        rects: [[1, 2, 3, 4]],
        appearance: DEFAULT_APPEARANCE,
        text: undefined,
        angle: 0,
        source: "import",
        createdAt: NOW.toISOString(),
      },
    ]);
  });
});
