import { type ChangeEvent, type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { saveTextFile } from "../lib/files";
import { plural } from "../lib/format";
import { parsePageRanges } from "../lib/pages";
import {
  categoryLabel,
  coveredHits,
  groupByPage,
  leadingContext,
  parseDetectList,
  parseKeywords,
  serializeDetectList,
} from "../lib/search";
import { useMarks } from "../marks";
import { useSearch } from "../search";
import { useStore } from "../store";
import type { CustomPattern } from "../types";

/** Find text or personal information and turn the hits into marks. */
export function SearchPanel() {
  const loadDetectors = useSearch((s) => s.loadDetectors);

  useEffect(() => {
    void loadDetectors();
  }, [loadDetectors]);

  return (
    <section className="panel search-panel" aria-label="Search">
      <SearchForm />
      <SearchResults />
    </section>
  );
}

function SearchForm() {
  const form = useSearch();
  const doc = useStore((s) => s.doc);
  const currentPage = useStore((s) => s.currentPage);
  const [rangeError, setRangeError] = useState<string | null>(null);
  const running = form.status === "running";
  const canSearch =
    form.kind === "detect" || (form.regex ? form.query.length > 0 : form.query.trim().length > 0);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!doc || !canSearch) return;
    let pages: number[] | undefined;
    if (form.scope === "current") pages = [currentPage];
    else if (form.scope === "range") {
      const parsed = parsePageRanges(form.range, doc.pageCount);
      if (parsed.error !== undefined) {
        setRangeError(parsed.error);
        return;
      }
      pages = parsed.pages;
    }
    setRangeError(null);
    void form.run(doc.id, pages);
  }

  return (
    <form className="search-form" onSubmit={submit}>
      <div className="segmented full" role="group" aria-label="Search for">
        <button
          type="button"
          className={form.kind === "text" ? "active" : ""}
          aria-pressed={form.kind === "text"}
          onClick={() => form.update({ kind: "text" })}
        >
          Text
        </button>
        <button
          type="button"
          className={form.kind === "detect" ? "active" : ""}
          aria-pressed={form.kind === "detect"}
          onClick={() => form.update({ kind: "detect" })}
        >
          Personal info
        </button>
      </div>

      {form.kind === "text" ? <TextFields /> : <DetectFields />}

      <div className="search-scope">
        <select
          aria-label="Pages to search"
          value={form.scope}
          onChange={(e) => form.update({ scope: e.target.value as typeof form.scope })}
        >
          <option value="all">All pages</option>
          <option value="current">Current page ({currentPage + 1})</option>
          <option value="range">Pages…</option>
        </select>
        {form.scope === "range" && (
          <input
            type="text"
            aria-label="Page range"
            placeholder="e.g. 1-3, 7"
            value={form.range}
            onChange={(e) => form.update({ range: e.target.value })}
          />
        )}
        <button type="submit" className="primary" disabled={!canSearch || running}>
          {running ? "Searching…" : "Find"}
        </button>
      </div>
      {(rangeError ?? form.error) && (
        <p className="error" role="alert">
          {rangeError ?? form.error}
        </p>
      )}
    </form>
  );
}

function TextFields() {
  const query = useSearch((s) => s.query);
  const wholeWord = useSearch((s) => s.wholeWord);
  const caseSensitive = useSearch((s) => s.caseSensitive);
  const regex = useSearch((s) => s.regex);
  const update = useSearch((s) => s.update);

  return (
    <>
      <input
        id="search-query"
        type="search"
        aria-label="Find text"
        placeholder={regex ? "Regular expression" : "Find text"}
        className={regex ? "mono" : undefined}
        value={query}
        onChange={(e) => update({ query: e.target.value })}
        spellCheck={false}
        autoComplete="off"
      />
      <div className="search-options">
        <label title={regex ? "Use \\b in the expression instead" : undefined}>
          <input
            type="checkbox"
            checked={wholeWord && !regex}
            disabled={regex}
            onChange={(e) => update({ wholeWord: e.target.checked })}
          />
          Whole words
        </label>
        <label>
          <input
            type="checkbox"
            checked={caseSensitive}
            onChange={(e) => update({ caseSensitive: e.target.checked })}
          />
          Match case
        </label>
        <label title="Python regular expression syntax">
          <input type="checkbox" checked={regex} onChange={(e) => update({ regex: e.target.checked })} />
          Regex
        </label>
      </div>
    </>
  );
}

function DetectFields() {
  const detectors = useSearch((s) => s.detectors);
  const categories = useSearch((s) => s.categories);
  const keywords = useSearch((s) => s.keywords);
  const patterns = useSearch((s) => s.patterns);
  const update = useSearch((s) => s.update);
  const fileInput = useRef<HTMLInputElement>(null);
  const [listError, setListError] = useState<string | null>(null);
  const enabled = new Set(categories ?? (detectors ?? []).filter((d) => d.default).map((d) => d.id));

  function toggle(id: string, on: boolean) {
    const next = (detectors ?? []).map((d) => d.id).filter((c) => (c === id ? on : enabled.has(c)));
    update({ categories: next });
  }

  function setPattern(index: number, patch: Partial<CustomPattern>) {
    update({ patterns: patterns.map((p, i) => (i === index ? { ...p, ...patch } : p)) });
  }

  async function loadList(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const list = parseDetectList(await file.text());
      const merged = parseKeywords([keywords, ...list.keywords].join("\n"));
      const known = new Set(patterns.map((p) => `${p.name}\n${p.pattern}`));
      update({
        keywords: merged.join("\n"),
        patterns: [...patterns, ...list.patterns.filter((p) => !known.has(`${p.name}\n${p.pattern}`))],
      });
      setListError(null);
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    }
  }

  function saveList() {
    saveTextFile("redaction-terms.json", serializeDetectList({ keywords: parseKeywords(keywords), patterns }));
  }

  return (
    <>
      <fieldset className="detectors">
        <legend>Information to find</legend>
        {detectors === null ? (
          <p className="muted">Loading…</p>
        ) : (
          detectors.map((d) => (
            <label key={d.id} title={d.description}>
              <input type="checkbox" checked={enabled.has(d.id)} onChange={(e) => toggle(d.id, e.target.checked)} />
              {d.label}
            </label>
          ))
        )}
      </fieldset>

      <label className="stacked">
        <span>Keywords</span>
        <textarea
          rows={3}
          placeholder={"Names, places, project codes…\nOne per line"}
          value={keywords}
          onChange={(e) => update({ keywords: e.target.value })}
          spellCheck={false}
        />
        <small className="muted">Whole words or phrases, ignoring case. Not saved.</small>
      </label>

      <fieldset className="patterns">
        <legend>Custom patterns</legend>
        {patterns.map((p, i) => (
          <div className="pattern-row" key={i}>
            <input
              type="text"
              aria-label="Pattern name"
              placeholder="Name"
              value={p.name}
              onChange={(e) => setPattern(i, { name: e.target.value })}
            />
            <input
              type="text"
              className="mono"
              aria-label="Regular expression"
              placeholder="Regular expression"
              value={p.pattern}
              onChange={(e) => setPattern(i, { pattern: e.target.value })}
              spellCheck={false}
            />
            <button
              type="button"
              className="icon"
              aria-label="Remove pattern"
              title="Remove pattern"
              onClick={() => update({ patterns: patterns.filter((_, j) => j !== i) })}
            >
              ✕
            </button>
          </div>
        ))}
        <div className="pattern-actions">
          <button
            type="button"
            className="link"
            onClick={() => update({ patterns: [...patterns, { name: `Pattern ${patterns.length + 1}`, pattern: "" }] })}
          >
            + Add pattern
          </button>
          <span className="spacer" />
          <button type="button" className="link" onClick={() => fileInput.current?.click()}>
            Load list…
          </button>
          <button type="button" className="link" onClick={saveList}>
            Save list…
          </button>
        </div>
        <small className="muted">Python syntax; start with (?i) to ignore case. Patterns are saved in this browser.</small>
        {listError && (
          <p className="error" role="alert">
            {listError}
          </p>
        )}
        <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={loadList} />
      </fieldset>
    </>
  );
}

/** Checkbox that can show a mixed state. */
function TriCheckbox({
  checked,
  mixed,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  mixed: boolean;
  disabled?: boolean;
  label: string;
  onChange(checked: boolean): void;
}) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      ref={(el) => {
        if (el) el.indeterminate = mixed;
      }}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

function SearchResults() {
  const status = useSearch((s) => s.status);
  const hits = useSearch((s) => s.hits);
  const truncated = useSearch((s) => s.truncated);
  const resultKind = useSearch((s) => s.resultKind);
  const checked = useSearch((s) => s.checked);
  const active = useSearch((s) => s.active);
  const detectors = useSearch((s) => s.detectors);
  const setChecked = useSearch((s) => s.setChecked);
  const setActive = useSearch((s) => s.setActive);
  const clearResults = useSearch((s) => s.clearResults);
  const marks = useMarks((s) => s.marks);
  const addMarks = useMarks((s) => s.addMarks);
  const goToPage = useStore((s) => s.goToPage);

  const header = useRef<HTMLElement>(null);
  const covered = useMemo(() => coveredHits(hits, marks), [hits, marks]);
  const groups = useMemo(() => groupByPage(hits), [hits]);
  const open = hits.map((_, i) => i).filter((i) => !covered.has(i));
  const toMark = open.filter((i) => checked.has(i));

  // New results may start below a long form: bring them into view.
  useEffect(() => {
    const el = header.current;
    const panel = el?.closest(".search-panel");
    if (!el || !panel) return;
    const top = el.getBoundingClientRect().top - panel.getBoundingClientRect().top;
    if (top > panel.clientHeight / 2) panel.scrollTop += top;
  }, [hits]);

  if (status !== "done") return null;

  function jump(i: number) {
    setActive(i);
    goToPage(hits[i].page, hits[i].rects[0][1]);
  }

  function markSelected() {
    addMarks(
      toMark.map((i) => {
        const h = hits[i];
        return {
          page: h.page,
          kind: "text" as const,
          rects: h.rects,
          text: h.text,
          angle: h.angle ?? undefined,
          source: resultKind === "text" ? ("search" as const) : ("detect" as const),
          category: h.category ?? undefined,
        };
      }),
    );
  }

  const summary = hits.length
    ? `${plural(hits.length, "result")} on ${plural(groups.length, "page")}`
    : "No results";

  return (
    <div className="search-results">
      <header className="results-header" ref={header}>
        {open.length > 0 && (
          <TriCheckbox
            label="Select all results"
            checked={toMark.length === open.length}
            mixed={toMark.length > 0 && toMark.length < open.length}
            onChange={(on) => setChecked(open, on)}
          />
        )}
        <span className="muted" role="status">
          {summary}
          {covered.size > 0 && `, ${covered.size} marked`}
        </span>
        <button className="link" onClick={clearResults}>
          Clear
        </button>
      </header>
      {truncated && (
        <p className="warning">Only the first {hits.length} results are shown. Narrow the search to see the rest.</p>
      )}
      {groups.map(([page, indexes]) => {
        const pageOpen = indexes.filter((i) => !covered.has(i));
        const pageChecked = pageOpen.filter((i) => checked.has(i));
        return (
          <div key={page} className="hit-group">
            <h3>
              <TriCheckbox
                label={`Select results on page ${page + 1}`}
                checked={pageOpen.length > 0 && pageChecked.length === pageOpen.length}
                mixed={pageChecked.length > 0 && pageChecked.length < pageOpen.length}
                disabled={pageOpen.length === 0}
                onChange={(on) => setChecked(pageOpen, on)}
              />
              Page {page + 1}
              <span className="count">{indexes.length}</span>
            </h3>
            <ul>
              {indexes.map((i) => {
                const h = hits[i];
                const isCovered = covered.has(i);
                return (
                  <li key={i} className={`hit${i === active ? " active" : ""}${isCovered ? " covered" : ""}`}>
                    <input
                      type="checkbox"
                      aria-label={`Select “${h.text}”`}
                      checked={isCovered || checked.has(i)}
                      disabled={isCovered}
                      onChange={(e) => setChecked([i], e.target.checked)}
                    />
                    <button className="hit-text" onClick={() => jump(i)} title="Show on page">
                      <span className="ctx">{leadingContext(h.before)}</span>
                      <mark>{h.text}</mark>
                      <span className="ctx">{h.after}</span>
                    </button>
                    {isCovered ? (
                      <span className="chip marked">Marked</span>
                    ) : (
                      h.category && <span className="chip">{categoryLabel(h.category, detectors)}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      {open.length > 0 && (
        <footer className="results-footer">
          <button className="primary" disabled={!toMark.length} onClick={markSelected}>
            Mark {toMark.length} selected
          </button>
        </footer>
      )}
    </div>
  );
}
