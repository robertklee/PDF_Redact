import { describe, expect, it } from "vitest";
import { applyOptions, DEFAULT_SANITIZE, DEFAULT_SETTINGS, isDefaultSanitize, parseSettings } from "./applySettings";

describe("parseSettings", () => {
  it("falls back to the defaults for missing or malformed data", () => {
    expect(parseSettings(null)).toEqual(DEFAULT_SETTINGS);
    expect(parseSettings("x")).toEqual(DEFAULT_SETTINGS);
    expect(parseSettings({ sanitize: [] })).toEqual(DEFAULT_SETTINGS);
  });

  it("keeps valid values and replaces invalid ones", () => {
    const parsed = parseSettings({
      images: "remove",
      graphics: "bogus",
      removeHidden: false,
      sanitize: { metadata: false, forms: "reset", annotations: "shred", bookmarks: "yes", extra: 1 },
    });
    expect(parsed.images).toBe("remove");
    expect(parsed.graphics).toBe("covered");
    expect(parsed.removeHidden).toBe(false);
    expect(parsed.sanitize).toEqual({ ...DEFAULT_SANITIZE, metadata: false, forms: "reset" });
  });
});

describe("applyOptions", () => {
  it("sends the sanitize options only when hidden information is to be removed", () => {
    expect(applyOptions(DEFAULT_SETTINGS, 2).sanitize).toEqual(DEFAULT_SANITIZE);
    const off = { ...DEFAULT_SETTINGS, removeHidden: false };
    expect(applyOptions(off, 2)).toEqual({ images: "pixels", graphics: "covered", sanitize: null });
    // Without marks, removing hidden information is the only thing to do.
    expect(applyOptions(off, 0).sanitize).toEqual(DEFAULT_SANITIZE);
  });
});

it("isDefaultSanitize", () => {
  expect(isDefaultSanitize({ ...DEFAULT_SANITIZE })).toBe(true);
  expect(isDefaultSanitize({ ...DEFAULT_SANITIZE, pageLabels: true })).toBe(false);
});
