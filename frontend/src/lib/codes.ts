/** Redaction codes: short labels such as FOIA "(b)(6)" written as a mark's overlay text. */

export interface Code {
  code: string;
  description: string;
}

export interface CodeSet {
  id: string;
  name: string;
  codes: Code[];
  builtIn?: boolean;
}

const LAW_ENFORCEMENT = "Law enforcement records whose release";

export const BUILT_IN_SETS: CodeSet[] = [
  {
    id: "foia",
    name: "FOIA",
    builtIn: true,
    codes: [
      { code: "(b)(1)", description: "Classified national defence or foreign policy information" },
      { code: "(b)(2)", description: "Internal personnel rules and practices of an agency" },
      { code: "(b)(3)", description: "Information that another statute exempts from disclosure" },
      { code: "(b)(4)", description: "Trade secrets and confidential commercial or financial information" },
      { code: "(b)(5)", description: "Privileged inter-agency or intra-agency memoranda and letters" },
      { code: "(b)(6)", description: "Personnel, medical and similar files: unwarranted invasion of personal privacy" },
      { code: "(b)(7)(A)", description: `${LAW_ENFORCEMENT} could interfere with enforcement proceedings` },
      { code: "(b)(7)(B)", description: `${LAW_ENFORCEMENT} would deprive a person of a fair trial` },
      { code: "(b)(7)(C)", description: `${LAW_ENFORCEMENT} could be an unwarranted invasion of personal privacy` },
      { code: "(b)(7)(D)", description: `${LAW_ENFORCEMENT} could disclose a confidential source` },
      { code: "(b)(7)(E)", description: `${LAW_ENFORCEMENT} would disclose techniques, procedures or guidelines` },
      { code: "(b)(7)(F)", description: `${LAW_ENFORCEMENT} could endanger someone's life or physical safety` },
      { code: "(b)(8)", description: "Reports about the regulation or supervision of financial institutions" },
      { code: "(b)(9)", description: "Geological and geophysical information about wells" },
    ],
  },
  {
    id: "privacy-act",
    name: "Privacy Act",
    builtIn: true,
    codes: [
      { code: "(j)(1)", description: "Records maintained by the Central Intelligence Agency" },
      { code: "(j)(2)", description: "Records of agencies whose main function is criminal law enforcement" },
      { code: "(k)(1)", description: "Classified information, as in FOIA exemption (b)(1)" },
      { code: "(k)(2)", description: "Investigatory material compiled for law enforcement purposes" },
      { code: "(k)(3)", description: "Records kept to provide protective services to the President and others" },
      { code: "(k)(4)", description: "Records required by statute to be used only as statistical records" },
      { code: "(k)(5)", description: "Investigatory material on suitability for federal employment, contracts or access to classified information, where it would reveal a confidential source" },
      { code: "(k)(6)", description: "Testing or examination material for appointment or promotion in the federal service" },
      { code: "(k)(7)", description: "Material for evaluating promotion in the armed services, where it would reveal a confidential source" },
    ],
  },
];

export const CODE_SEPARATOR = ", ";
export const MAX_CODE_LENGTH = 40;
const MAX_SET_NAME = 100;
const MAX_DESCRIPTION = 500;
const MAX_CODES = 500;

/** The comma-separated codes (or other labels) in an overlay text. */
export function splitCodes(text: string): string[] {
  return text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/**
 * Overlay text with `code` added or removed. Codes from `order` (the active set) are kept in that
 * order after any other labels, so "(b)(6), (b)(7)(C)" reads the same however it was picked.
 */
export function toggleCode(text: string, code: string, on: boolean, order: string[] = []): string {
  const tokens = splitCodes(text).filter((t) => t !== code);
  if (on) tokens.push(code);
  const rank = new Map(order.map((c, i) => [c, i]));
  const others = tokens.filter((t) => !rank.has(t));
  const known = tokens.filter((t) => rank.has(t)).sort((a, b) => rank.get(a)! - rank.get(b)!);
  return [...new Set([...others, ...known])].join(CODE_SEPARATOR);
}

export function hasCode(text: string, code: string): boolean {
  return splitCodes(text).includes(code);
}

/** "Copy of X", "Copy of X (2)", … — the first name not already taken. */
export function uniqueName(name: string, taken: Iterable<string>): string {
  const used = new Set([...taken].map((n) => n.toLowerCase()));
  if (!used.has(name.toLowerCase())) return name;
  for (let i = 2; ; i++) {
    const candidate = `${name} (${i})`;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
}

/** Problems that stop a code set from being saved, or null if it is fine. */
export function codeSetProblem(set: Pick<CodeSet, "name" | "codes">): string | null {
  if (!set.name.trim()) return "Give the set a name.";
  if (set.name.length > MAX_SET_NAME) return `Use a name of at most ${MAX_SET_NAME} characters.`;
  if (set.codes.length > MAX_CODES) return `A set can hold at most ${MAX_CODES} codes.`;
  const seen = new Set<string>();
  for (const { code, description } of set.codes) {
    const c = code.trim();
    if (!c) return "Every row needs a code.";
    if (c.includes(",")) return `“${c}”: codes cannot contain commas.`;
    if (c.length > MAX_CODE_LENGTH) return `“${c}” is longer than ${MAX_CODE_LENGTH} characters.`;
    if (description.length > MAX_DESCRIPTION) return `The description of “${c}” is too long.`;
    if (seen.has(c)) return `“${c}” appears more than once.`;
    seen.add(c);
  }
  return null;
}

/** A set as stored and exported: trimmed, without the id or built-in flag. */
export function cleanCodeSet(set: Pick<CodeSet, "name" | "codes">) {
  return {
    name: set.name.trim(),
    codes: set.codes.map((c) => ({ code: c.code.trim(), description: c.description.trim() })),
  };
}

export function serializeCodeSets(sets: Pick<CodeSet, "name" | "codes">[]): string {
  return JSON.stringify({ app: "pdf-redact", type: "code-sets", version: 1, sets: sets.map(cleanCodeSet) }, null, 2);
}

/** Read code sets written by `serializeCodeSets` (or a bare set or list of sets). Throws if invalid. */
export function parseCodeSets(json: string): Pick<CodeSet, "name" | "codes">[] {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    throw new Error("The file is not valid JSON.");
  }
  const obj = data as { sets?: unknown; name?: unknown; codes?: unknown } | null;
  const list = Array.isArray(data) ? data : Array.isArray(obj?.sets) ? obj.sets : obj?.codes ? [obj] : null;
  if (!list) throw new Error("The file does not contain code sets.");
  return list.map((item: unknown, i: number) => {
    const set = item as { name?: unknown; codes?: unknown } | null;
    const codes = set?.codes;
    if (
      typeof set?.name !== "string" ||
      !Array.isArray(codes) ||
      !codes.every(
        (c) =>
          c &&
          typeof c === "object" &&
          typeof c.code === "string" &&
          (c.description === undefined || typeof c.description === "string"),
      )
    ) {
      throw new Error(`Code set ${i + 1} is not valid: it needs a name and a list of codes.`);
    }
    const parsed = cleanCodeSet({
      name: set.name,
      codes: codes.map((c: { code: string; description?: string }) => ({
        code: c.code,
        description: c.description ?? "",
      })),
    });
    const problem = codeSetProblem(parsed);
    if (problem) throw new Error(`${parsed.name || `Code set ${i + 1}`}: ${problem}`);
    return parsed;
  });
}
