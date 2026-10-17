import { DEFAULT_SANITIZE, isDefaultSanitize } from "../lib/applySettings";
import type { AnnotationMode, FormMode, SanitizeOptions } from "../types";

type Flag = { [K in keyof SanitizeOptions]: SanitizeOptions[K] extends boolean ? K : never }[keyof SanitizeOptions];

interface FlagOption {
  key: Flag;
  label: string;
  hint?: string;
}

const CONTENT_FLAGS: FlagOption[] = [
  { key: "metadata", label: "Document properties and metadata", hint: "Title, author, dates, XMP" },
  { key: "layers", label: "Hidden layers", hint: "Visible layers are merged into the page" },
  { key: "hiddenText", label: "Hidden text", hint: "Text that does not show, such as white or covered text" },
];

const OTHER_FLAGS: FlagOption[] = [
  { key: "outsideCrop", label: "Content outside the visible page area" },
  { key: "attachments", label: "Attached files" },
  { key: "links", label: "Links" },
  { key: "javascript", label: "JavaScript and automatic actions" },
  { key: "thumbnails", label: "Page thumbnails" },
  { key: "bookmarks", label: "Bookmarks", hint: "Their titles may repeat redacted text" },
  { key: "pageLabels", label: "Page labels", hint: "Custom page numbering" },
];

const ANNOTATION_MODES: { value: AnnotationMode; label: string }[] = [
  { value: "remove", label: "Remove" },
  { value: "flatten", label: "Flatten into the page" },
  { value: "keep", label: "Keep" },
];

const FORM_MODES: { value: FormMode; label: string }[] = [
  { value: "flatten", label: "Flatten into the page" },
  { value: "reset", label: "Clear the values" },
  { value: "keep", label: "Keep" },
];

interface Props {
  /** With marks, removing hidden information is optional; without, it is all there is to do. */
  optional: boolean;
  enabled: boolean;
  options: SanitizeOptions;
  disabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onChange: (options: SanitizeOptions) => void;
}

/** Choice of hidden information to remove from the whole document when applying. */
export function HiddenInfoOptions({ optional, enabled, options, disabled, onEnabledChange, onChange }: Props) {
  const flag = ({ key, label, hint }: FlagOption, extra?: { nested?: boolean; disabled?: boolean }) => (
    <label key={key} className={extra?.nested ? "nested" : undefined}>
      <input
        type="checkbox"
        checked={options[key]}
        disabled={extra?.disabled}
        onChange={(e) => onChange({ ...options, [key]: e.target.checked })}
      />
      {label}
      {hint && <span className="muted small"> — {hint}</span>}
    </label>
  );

  return (
    <fieldset className="options" disabled={disabled}>
      <legend>Hidden information</legend>
      {optional ? (
        <label>
          <input type="checkbox" checked={enabled} onChange={(e) => onEnabledChange(e.target.checked)} />
          Also remove hidden information from the whole document
          <span className="muted small"> — Recommended</span>
        </label>
      ) : (
        <p className="muted small">Choose what to remove from the whole document.</p>
      )}
      {enabled && (
        <details className="sanitize-options" open={!optional || undefined}>
          <summary>{isDefaultSanitize(options) ? "What is removed" : "What is removed (changed)"}</summary>
          {CONTENT_FLAGS.slice(0, 1).map((f) => flag(f))}
          <label>
            Comments and markup
            <select
              value={options.annotations}
              onChange={(e) => onChange({ ...options, annotations: e.target.value as AnnotationMode })}
            >
              {ANNOTATION_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Form fields
            <select
              value={options.forms}
              onChange={(e) => onChange({ ...options, forms: e.target.value as FormMode })}
            >
              {FORM_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          {CONTENT_FLAGS.slice(1).map((f) => flag(f))}
          {flag(
            { key: "keepOcrText", label: "Keep invisible OCR text over scanned images", hint: "Keeps scans searchable" },
            { nested: true, disabled: !options.hiddenText },
          )}
          {OTHER_FLAGS.map((f) => flag(f))}
          {!isDefaultSanitize(options) && (
            <button type="button" className="link" onClick={() => onChange(DEFAULT_SANITIZE)}>
              Restore defaults
            </button>
          )}
        </details>
      )}
    </fieldset>
  );
}
