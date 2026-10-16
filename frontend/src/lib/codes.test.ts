import { describe, expect, it } from "vitest";
import {
  BUILT_IN_SETS,
  codeSetProblem,
  hasCode,
  parseCodeSets,
  serializeCodeSets,
  splitCodes,
  toggleCode,
  uniqueName,
} from "./codes";
import { drawable } from "./overlay";

const FOIA = BUILT_IN_SETS[0].codes.map((c) => c.code);

describe("toggleCode", () => {
  it("adds and removes codes in the set's order", () => {
    let text = toggleCode("", "(b)(7)(C)", true, FOIA);
    expect(text).toBe("(b)(7)(C)");
    text = toggleCode(text, "(b)(6)", true, FOIA);
    expect(text).toBe("(b)(6), (b)(7)(C)");
    expect(toggleCode(text, "(b)(6)", false, FOIA)).toBe("(b)(7)(C)");
    expect(toggleCode(text, "(b)(6)", true, FOIA)).toBe(text);
  });

  it("keeps other labels first and tidies separators", () => {
    expect(toggleCode("Withheld ,(b)(7)(C),", "(b)(6)", true, FOIA)).toBe("Withheld, (b)(6), (b)(7)(C)");
    expect(toggleCode("Withheld", "X1", true)).toBe("Withheld, X1");
  });

  it("only matches whole codes", () => {
    expect(hasCode("(b)(7)(C)", "(b)(7)")).toBe(false);
    expect(hasCode("(b)(6), (b)(7)(C)", "(b)(7)(C)")).toBe(true);
    expect(splitCodes(" , a,,b ")).toEqual(["a", "b"]);
  });
});

describe("code sets", () => {
  it("ships valid built-in sets the overlay fonts can draw", () => {
    for (const set of BUILT_IN_SETS) {
      expect(codeSetProblem(set)).toBeNull();
      for (const { code } of set.codes) expect(drawable(code)).toBe(code);
    }
  });

  it("explains what is wrong with a set", () => {
    const codes = (...list: string[]) => list.map((code) => ({ code, description: "" }));
    expect(codeSetProblem({ name: " ", codes: [] })).toMatch(/name/);
    expect(codeSetProblem({ name: "A", codes: codes("x", " ") })).toMatch(/needs a code/);
    expect(codeSetProblem({ name: "A", codes: codes("x", " x ") })).toMatch(/more than once/);
    expect(codeSetProblem({ name: "A", codes: codes("a,b") })).toMatch(/commas/);
    expect(codeSetProblem({ name: "A", codes: [] })).toBeNull();
  });

  it("picks names that are not taken", () => {
    expect(uniqueName("Mine", ["Other"])).toBe("Mine");
    expect(uniqueName("Mine", ["mine", "Mine (2)"])).toBe("Mine (3)");
  });

  it("round-trips through JSON", () => {
    const sets = [{ name: " Agency ", codes: [{ code: " A1 ", description: "First " }] }];
    expect(parseCodeSets(serializeCodeSets(sets))).toEqual([
      { name: "Agency", codes: [{ code: "A1", description: "First" }] },
    ]);
  });

  it("reads a bare set or list of sets", () => {
    const set = { name: "S", codes: [{ code: "C" }] };
    expect(parseCodeSets(JSON.stringify(set))).toEqual([{ name: "S", codes: [{ code: "C", description: "" }] }]);
    expect(parseCodeSets(JSON.stringify([set, set]))).toHaveLength(2);
  });

  it("rejects files that are not code sets", () => {
    expect(() => parseCodeSets("{")).toThrow(/not valid JSON/);
    expect(() => parseCodeSets("{}")).toThrow(/does not contain/);
    expect(() => parseCodeSets(JSON.stringify({ sets: [{ name: "S", codes: [{ code: 1 }] }] }))).toThrow(
      /Code set 1/,
    );
    expect(() =>
      parseCodeSets(JSON.stringify({ sets: [{ name: "S", codes: [{ code: "A" }, { code: "A" }] }] })),
    ).toThrow(/S: .*more than once/);
  });
});
