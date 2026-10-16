import { useState } from "react";
import { activeCodeSet, allCodeSets, useCodeSets } from "../codeSets";
import { hasCode, toggleCode } from "../lib/codes";
import { FONT_OPTIONS, MAX_OVERLAY_TEXT, overlayDoesNotFit, unsupportedChars } from "../lib/overlay";
import { useMarks } from "../marks";
import type { Align, Appearance, OverlayFont } from "../types";
import { CodeSetsDialog } from "./CodeSetsDialog";

const MIXED = Symbol("mixed");
type Field<T> = T | typeof MIXED;

/** The value shared by all items, or MIXED. */
function common<T>(values: T[]): Field<T> {
  return values.every((v) => v === values[0]) ? values[0] : MIXED;
}

const ALIGNS: { value: Align; label: string }[] = [
  { value: "left", label: "Left" },
  { value: "center", label: "Centre" },
  { value: "right", label: "Right" },
];

/** Appearance of the selected marks, or of new marks when nothing is selected. */
export function PropertiesPanel() {
  const marks = useMarks((s) => s.marks);
  const selection = useMarks((s) => s.selection);
  const defaults = useMarks((s) => s.defaults);
  const setAppearance = useMarks((s) => s.setAppearance);
  const setDefaults = useMarks((s) => s.setDefaults);
  const codeSets = useCodeSets();
  const codeSet = activeCodeSet(codeSets);
  const [sizeDraft, setSizeDraft] = useState<string | null>(null);
  const [managingCodes, setManagingCodes] = useState(false);

  const ids = new Set(selection);
  const targets = marks.filter((m) => ids.has(m.id));
  const editingDefaults = targets.length === 0;
  const items: Appearance[] = editingDefaults ? [defaults] : targets.map((m) => m.appearance);
  const fill = common(items.map((a) => a.fill));
  const textColor = common(items.map((a) => a.textColor));
  const overlayText = common(items.map((a) => a.overlayText));
  const fontSize = common(items.map((a) => a.fontSize));
  const align = common(items.map((a) => a.align));
  const font = common(items.map((a) => a.font));
  const repeat = common(items.map((a) => a.repeat));
  const crowded = targets.filter(overlayDoesNotFit).length;

  function apply(patch: Partial<Appearance>, key?: string) {
    if (editingDefaults) setDefaults(patch);
    else setAppearance(selection, patch, key && `${key}:${selection.join(",")}`);
  }

  const order = codeSet.codes.map((c) => c.code);
  /** Pressed if every target has the code, mixed if only some do. */
  function codeState(code: string): boolean | "mixed" {
    const n = items.filter((a) => hasCode(a.overlayText, code)).length;
    return n === items.length ? true : n === 0 ? false : "mixed";
  }
  function setCode(code: string, on: boolean) {
    const next = (a: Appearance) => toggleCode(a.overlayText, code, on, order);
    if (editingDefaults) setDefaults({ overlayText: next(defaults) });
    else {
      useMarks
        .getState()
        .updateMarks(selection, (m) => ({ ...m, appearance: { ...m.appearance, overlayText: next(m.appearance) } }));
    }
  }
  const tooLong = (code: string) =>
    items.some((a) => toggleCode(a.overlayText, code, true, order).length > MAX_OVERLAY_TEXT);

  const unsupported = overlayText === MIXED ? [] : unsupportedChars(overlayText);
  const sizeValue = sizeDraft ?? (fontSize === MIXED || fontSize === null ? "" : String(fontSize));
  const sizeNumber = Number(sizeValue);
  const sizeInvalid = sizeValue.trim() !== "" && !(sizeNumber >= 4 && sizeNumber <= 72);

  return (
    <section className="panel properties-panel" aria-label="Appearance">
      <header className="panel-header">
        <h2>{editingDefaults ? "New marks" : `${targets.length} selected`}</h2>
        {!editingDefaults && (
          <button
            className="link"
            title="Use this appearance for new marks"
            disabled={[fill, textColor, overlayText, fontSize, align, font, repeat].includes(MIXED)}
            onClick={() => setDefaults({ ...targets[0].appearance })}
          >
            Set as default
          </button>
        )}
      </header>
      <div className="panel-body form">
        <label className="row">
          <span>Fill</span>
          <input
            type="color"
            aria-label="Fill colour"
            value={fill === MIXED || fill === null ? "#000000" : fill}
            disabled={fill === null}
            onChange={(e) => apply({ fill: e.target.value }, "fill")}
          />
          <label className="inline">
            <input
              type="checkbox"
              checked={fill === null}
              ref={(el) => {
                if (el) el.indeterminate = fill === MIXED;
              }}
              onChange={(e) => apply({ fill: e.target.checked ? null : "#000000" })}
            />
            None
          </label>
        </label>
        {fill === null && (
          <p className="hint warning">
            Without a fill the area is left blank: content is still removed, but readers cannot see
            that something was redacted.
          </p>
        )}
        <label className="row">
          <span>Overlay text</span>
          <input
            type="text"
            maxLength={MAX_OVERLAY_TEXT}
            value={overlayText === MIXED ? "" : overlayText}
            placeholder={overlayText === MIXED ? "Mixed" : "None"}
            onChange={(e) => apply({ overlayText: e.target.value }, "overlayText")}
          />
        </label>
        <div className="row">
          <span>Codes</span>
          <select
            aria-label="Code set"
            value={codeSet.id}
            onChange={(e) => codeSets.setActive(e.target.value)}
          >
            {allCodeSets(codeSets.custom).map((set) => (
              <option key={set.id} value={set.id}>
                {set.name}
              </option>
            ))}
          </select>
        </div>
        {codeSet.codes.length > 0 ? (
          <div className="code-picker" role="group" aria-label={codeSet.name}>
            {codeSet.codes.map(({ code, description }) => {
              const state = codeState(code);
              const blocked = state !== true && tooLong(code);
              return (
                <button
                  key={code}
                  className="code-toggle"
                  aria-pressed={state}
                  disabled={blocked}
                  title={blocked ? "The overlay text would be too long" : description}
                  onClick={() => setCode(code, state !== true)}
                >
                  {code}
                </button>
              );
            })}
            <button className="link manage-codes" onClick={() => setManagingCodes(true)}>
              Manage…
            </button>
          </div>
        ) : (
          <p className="hint">
            This code set is empty.{" "}
            <button className="link manage-codes" onClick={() => setManagingCodes(true)}>
              Manage…
            </button>
          </p>
        )}
        {unsupported.length > 0 && (
          <p className="hint warning">
            The overlay font cannot show {unsupported.join(" ")}; use Latin characters.
          </p>
        )}
        <label className="row">
          <span>Text colour</span>
          <input
            type="color"
            aria-label="Text colour"
            value={textColor === MIXED ? "#ffffff" : textColor}
            onChange={(e) => apply({ textColor: e.target.value }, "textColor")}
          />
        </label>
        <label className="row">
          <span>Font</span>
          <select
            value={font === MIXED ? "" : font}
            onChange={(e) => apply({ font: e.target.value as OverlayFont })}
          >
            {font === MIXED && (
              <option value="" disabled>
                Mixed
              </option>
            )}
            {FONT_OPTIONS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="row">
          <span>Font size</span>
          <input
            type="number"
            min={4}
            max={72}
            step={0.5}
            className={sizeInvalid ? "invalid" : undefined}
            value={sizeValue}
            placeholder={fontSize === MIXED ? "Mixed" : "Auto"}
            onChange={(e) => {
              const v = e.target.value;
              setSizeDraft(v);
              const n = Number(v);
              if (v.trim() === "") apply({ fontSize: null }, "fontSize");
              else if (n >= 4 && n <= 72) apply({ fontSize: n }, "fontSize");
            }}
            onBlur={() => setSizeDraft(null)}
          />
          <span className="muted">pt</span>
        </label>
        <div className="row">
          <span>Align</span>
          <div className="segmented" role="radiogroup" aria-label="Overlay alignment">
            {ALIGNS.map((a) => (
              <button
                key={a.value}
                role="radio"
                aria-checked={align === a.value}
                className={align === a.value ? "active" : undefined}
                onClick={() => apply({ align: a.value })}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
        <div className="row">
          <span>Repeat</span>
          <label className="inline">
            <input
              type="checkbox"
              checked={repeat === true}
              ref={(el) => {
                if (el) el.indeterminate = repeat === MIXED;
              }}
              onChange={(e) => apply({ repeat: e.target.checked })}
            />
            Fill each box with the text
          </label>
        </div>
        {crowded > 0 && (
          <p className="hint warning">
            The overlay text does not fit {targets.length === 1 ? "this mark" : `${crowded} of these marks`}{" "}
            at 4 pt or more and will be left out. Shorten the text or enlarge the mark to show it.
          </p>
        )}
        <p className="hint">Hover a mark, or turn on Preview, to see how it will look.</p>
      </div>
      {managingCodes && <CodeSetsDialog onClose={() => setManagingCodes(false)} />}
    </section>
  );
}
