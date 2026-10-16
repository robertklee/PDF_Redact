import { type ChangeEvent, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { allCodeSets, useCodeSets } from "../codeSets";
import {
  type CodeSet,
  cleanCodeSet,
  codeSetProblem,
  MAX_CODE_LENGTH,
  parseCodeSets,
  serializeCodeSets,
  uniqueName,
} from "../lib/codes";
import { saveTextFile } from "../lib/files";
import { plural } from "../lib/format";

type Draft = Pick<CodeSet, "name" | "codes">;

/** View the built-in code sets and create, edit, import and export custom ones. */
export function CodeSetsDialog({ onClose }: { onClose: () => void }) {
  const { custom, activeId, add, update, remove, setActive } = useCodeSets();
  const sets = allCodeSets(custom);
  const [selectedId, setSelectedId] = useState(activeId);
  const selected = sets.find((s) => s.id === selectedId) ?? sets[0];
  const [draft, setDraft] = useState<Draft | null>(null);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const shown: Draft = draft ?? selected;
  const problem = draft && codeSetProblem(draft);
  const names = sets.map((s) => s.name);

  /** Drop unsaved edits, asking first. */
  function discard(): boolean {
    if (draft && !window.confirm(`Discard your changes to “${selected.name}”?`)) return false;
    setDraft(null);
    return true;
  }

  function select(id: string) {
    if (id === selected.id || !discard()) return;
    setSelectedId(id);
    setMessage(null);
  }

  function create(set: Draft, note?: string) {
    setSelectedId(add(set));
    setDraft(null);
    setMessage(note ? { text: note } : null);
  }

  function edit(change: Partial<Draft>) {
    setDraft({ ...shown, ...change });
  }

  function save() {
    if (!draft || problem) return;
    update(selected.id, cleanCodeSet(draft));
    setDraft(null);
    setMessage({ text: "Saved." });
  }

  function close() {
    if (!discard()) return;
    setActive(selected.id);
    onClose();
  }

  function removeSelected() {
    if (!window.confirm(`Delete the code set “${selected.name}”?`)) return;
    remove(selected.id);
    setDraft(null);
    setSelectedId(sets[0].id);
    setMessage(null);
  }

  async function importFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !discard()) return;
    try {
      const imported = parseCodeSets(await file.text());
      if (!imported.length) throw new Error("The file contains no code sets.");
      const taken = [...names];
      let last = "";
      for (const set of imported) {
        const name = uniqueName(set.name, taken);
        taken.push(name);
        last = add({ ...set, name });
      }
      setSelectedId(last);
      setMessage({ text: `Imported ${plural(imported.length, "code set")}.` });
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : String(err), error: true });
    }
  }

  function exportSelected() {
    const slug = selected.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "codes";
    saveTextFile(`${slug}.codes.json`, serializeCodeSets([selected]));
  }

  const setCode = (i: number, change: Partial<Draft["codes"][number]>) =>
    edit({ codes: shown.codes.map((c, j) => (j === i ? { ...c, ...change } : c)) });

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div
        className="modal code-sets-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="code-sets-title"
        onKeyDown={(e) => e.key === "Escape" && close()}
      >
        <h2 id="code-sets-title">Code sets</h2>
        <div className="code-sets-layout">
          <div className="code-sets-list">
            <select
              size={8}
              aria-label="Code sets"
              value={selected.id}
              onChange={(e) => select(e.target.value)}
            >
              {sets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <button onClick={() => discard() && create({ name: uniqueName("New code set", names), codes: [] })}>
              New set
            </button>
            <button onClick={() => fileInput.current?.click()}>Import…</button>
            <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={importFile} />
          </div>

          <div className="code-set-editor">
            {selected.builtIn ? (
              <p className="muted small">
                {selected.name} is built in and cannot be changed. Duplicate it to make your own version.
              </p>
            ) : (
              <label className="field">
                <span>Name</span>
                <input type="text" maxLength={100} value={shown.name} onChange={(e) => edit({ name: e.target.value })} />
              </label>
            )}
            <table className="codes-table">
              <thead>
                <tr>
                  <th scope="col">Code</th>
                  <th scope="col">Description</th>
                  {!selected.builtIn && <th scope="col" aria-label="Remove" />}
                </tr>
              </thead>
              <tbody>
                {shown.codes.map((c, i) =>
                  selected.builtIn ? (
                    <tr key={i}>
                      <td className="code-cell">{c.code}</td>
                      <td>{c.description}</td>
                    </tr>
                  ) : (
                    <tr key={i}>
                      <td className="code-cell">
                        <input
                          type="text"
                          aria-label={`Code ${i + 1}`}
                          maxLength={MAX_CODE_LENGTH}
                          autoFocus={c.code === ""}
                          value={c.code}
                          onChange={(e) => setCode(i, { code: e.target.value })}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          aria-label={`Description ${i + 1}`}
                          maxLength={500}
                          value={c.description}
                          onChange={(e) => setCode(i, { description: e.target.value })}
                        />
                      </td>
                      <td>
                        <button
                          className="icon"
                          aria-label={`Remove code ${c.code || i + 1}`}
                          onClick={() => edit({ codes: shown.codes.filter((_, j) => j !== i) })}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            {!shown.codes.length && <p className="muted small">No codes yet.</p>}
            {!selected.builtIn && (
              <button
                className="link add-code"
                onClick={() => edit({ codes: [...shown.codes, { code: "", description: "" }] })}
              >
                + Add code
              </button>
            )}
          </div>
        </div>

        {problem ? (
          <p className="error" role="alert">
            {problem}
          </p>
        ) : (
          message && (
            <p className={message.error ? "error" : "muted"} role={message.error ? "alert" : "status"}>
              {message.text}
            </p>
          )
        )}

        <div className="actions">
          <button
            onClick={() =>
              discard() &&
              create({ name: uniqueName(`${selected.name} (copy)`, names), codes: selected.codes }, "Duplicated.")
            }
          >
            Duplicate
          </button>
          <button onClick={exportSelected} disabled={!!draft}>
            Export…
          </button>
          {!selected.builtIn && (
            <button className="danger" onClick={removeSelected}>
              Delete
            </button>
          )}
          <span className="spacer" />
          {draft && <button onClick={() => setDraft(null)}>Revert</button>}
          {!selected.builtIn && (
            <button className="primary" onClick={save} disabled={!draft || !!problem}>
              Save
            </button>
          )}
          <button onClick={close}>Close</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
