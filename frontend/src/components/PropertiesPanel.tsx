import { useState } from "react";
import { unsupportedChars } from "../lib/overlay";
import { useMarks } from "../marks";
import type { Align, Appearance } from "../types";

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
  const [sizeDraft, setSizeDraft] = useState<string | null>(null);

  const ids = new Set(selection);
  const targets = marks.filter((m) => ids.has(m.id));
  const editingDefaults = targets.length === 0;
  const items: Appearance[] = editingDefaults ? [defaults] : targets.map((m) => m.appearance);
  const fill = common(items.map((a) => a.fill));
  const textColor = common(items.map((a) => a.textColor));
  const overlayText = common(items.map((a) => a.overlayText));
  const fontSize = common(items.map((a) => a.fontSize));
  const align = common(items.map((a) => a.align));

  function apply(patch: Partial<Appearance>, key?: string) {
    if (editingDefaults) setDefaults(patch);
    else setAppearance(selection, patch, key && `${key}:${selection.join(",")}`);
  }

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
            disabled={[fill, textColor, overlayText, fontSize, align].includes(MIXED)}
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
            maxLength={200}
            value={overlayText === MIXED ? "" : overlayText}
            placeholder={overlayText === MIXED ? "Mixed" : "None"}
            onChange={(e) => apply({ overlayText: e.target.value }, "overlayText")}
          />
        </label>
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
        <p className="hint">Hover a mark, or turn on Preview, to see how it will look.</p>
      </div>
    </section>
  );
}
