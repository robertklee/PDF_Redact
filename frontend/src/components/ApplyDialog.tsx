import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, isAbort, type Progress } from "../api";
import { type ApplySettings, applyOptions, loadSettings, saveSettings } from "../lib/applySettings";
import { describeMark, formatBytes, KIND_LABELS, plural } from "../lib/format";
import { overlayDoesNotFit } from "../lib/overlay";
import { formatPages } from "../lib/pages";
import { useMarks } from "../marks";
import { useStore } from "../store";
import type { Check, GraphicsMode, ImageMode, Mark, OutputInfo, ReportFormat, ReportText } from "../types";
import { HiddenInfoOptions } from "./HiddenInfoOptions";
import { JobProgress } from "./JobProgress";
import { Modal } from "./Modal";

const IMAGE_MODES: { value: ImageMode; label: string; hint: string }[] = [
  { value: "pixels", label: "Blank the covered pixels", hint: "Recommended" },
  { value: "remove", label: "Remove every image a mark touches", hint: "" },
  { value: "none", label: "Leave images unchanged", hint: "Image content under marks stays in the file" },
];

const GRAPHICS_MODES: { value: GraphicsMode; label: string; hint: string }[] = [
  { value: "covered", label: "Remove shapes inside marks", hint: "Recommended" },
  { value: "touched", label: "Remove every shape a mark touches", hint: "Also removes lines that cross a mark" },
  { value: "none", label: "Leave vector graphics unchanged", hint: "" },
];

type Phase =
  | { name: "confirm"; error?: string }
  | { name: "working" }
  | { name: "done"; output: OutputInfo; downloaded: boolean; downloadError?: string };

/**
 * Apply the marks on the server, show the verification report and offer the result for download.
 * Without marks, only hidden information is removed.
 */
export function ApplyDialog({ onClose }: { onClose: () => void }) {
  const doc = useStore((s) => s.doc)!;
  const marks = useMarks((s) => s.marks);
  const [settings, setSettingsState] = useState(loadSettings);
  const [phase, setPhase] = useState<Phase>({ name: "confirm" });
  const [override, setOverride] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const job = useRef<AbortController | null>(null);

  // Closing the dialog some other way (e.g. the document is closed) stops the work too.
  useEffect(() => () => job.current?.abort(), []);

  const summary = useMemo(() => {
    const kinds = { text: 0, area: 0, page: 0 };
    for (const m of marks) kinds[m.kind] += 1;
    const pages = [...new Set(marks.map((m) => m.page))].sort((a, b) => a - b);
    const unfilled = marks.filter((m) => m.appearance.fill === null).length;
    const crowded = marks.filter(overlayDoesNotFit).length;
    return { kinds, pages, unfilled, crowded };
  }, [marks]);

  const withMarks = marks.length > 0;

  function setSettings(next: ApplySettings) {
    setSettingsState(next);
    saveSettings(next);
  }

  async function apply() {
    const controller = (job.current = new AbortController());
    setPhase({ name: "working" });
    setProgress(null);
    setOverride(false);
    try {
      const options = applyOptions(settings, marks.length);
      const output = await api.apply(doc.id, marks, options, { signal: controller.signal, onProgress: setProgress });
      setPhase({ name: "done", output, downloaded: false });
    } catch (e) {
      if (isAbort(e)) setPhase({ name: "confirm" });
      else setPhase({ name: "confirm", error: e instanceof ApiError ? e.message : String(e) });
    } finally {
      job.current = null;
    }
  }

  async function download(output: OutputInfo) {
    try {
      await api.download(output);
      useMarks.getState().markSaved();
      setPhase({ name: "done", output, downloaded: true });
    } catch (e) {
      const message = e instanceof ApiError ? e.message : String(e);
      setPhase({ name: "done", output, downloaded: false, downloadError: message });
    }
  }

  function showMark(mark: Mark) {
    useMarks.getState().select([mark.id]);
    useStore.getState().goToPage(mark.page, mark.kind === "page" ? undefined : mark.rects[0][1]);
    onClose();
  }

  const busy = phase.name === "working";
  const stop = () => job.current?.abort();

  return (
    // While working, Escape stops the work (like the Cancel button) but a stray click doesn't.
    <Modal labelledBy="apply-title" onDismiss={(how) => (!busy ? onClose() : how === "escape" && stop())}>
      <div className="modal apply-dialog">
        {phase.name === "done" ? (
          <Result
            output={phase.output}
            marks={marks}
            downloaded={phase.downloaded}
            downloadError={phase.downloadError}
            override={override}
            setOverride={setOverride}
            onDownload={() => void download(phase.output)}
            onShowMark={showMark}
            onBack={() => setPhase({ name: "confirm" })}
            onClose={onClose}
          />
        ) : (
          <>
            <h2 id="apply-title">{withMarks ? "Apply redactions" : "Remove hidden information"}</h2>
            {withMarks ? (
              <>
                <p>
                  {plural(marks.length, "mark")} on {summary.pages.length === 1 ? "page" : "pages"}{" "}
                  {formatPages(summary.pages)} (
                  {(["text", "area", "page"] as const)
                    .filter((k) => summary.kinds[k])
                    .map((k) => `${summary.kinds[k]} ${KIND_LABELS[k].toLowerCase()}`)
                    .join(", ")}
                  )
                </p>
                <p className="muted small">
                  Marked text, image pixels and graphics are permanently removed from a new copy of{" "}
                  <strong>{doc.filename}</strong>. The original file is not changed, and you can keep
                  editing marks and apply again.
                </p>
              </>
            ) : (
              <p className="muted small">
                There are no marks, so only hidden information is removed, in a new copy of{" "}
                <strong>{doc.filename}</strong>. The original file is not changed.
              </p>
            )}
            {summary.unfilled > 0 && (
              <p className="hint warning">
                {plural(summary.unfilled, "mark has", "marks have")} no fill: the content is removed
                but the area is left blank, which may reveal the length of what was removed.
              </p>
            )}
            {summary.crowded > 0 && (
              <p className="hint warning">
                The overlay text does not fit on {plural(summary.crowded, "mark")} and will be left
                out there. Shorten the text or enlarge those marks to show it.
              </p>
            )}
            {withMarks && (
              <>
                <fieldset className="options" disabled={busy}>
                  <legend>Images under marks</legend>
                  {IMAGE_MODES.map((m) => (
                    <label key={m.value}>
                      <input
                        type="radio"
                        name="images"
                        checked={settings.images === m.value}
                        onChange={() => setSettings({ ...settings, images: m.value })}
                      />
                      {m.label}
                      {m.hint && <span className="muted small"> — {m.hint}</span>}
                    </label>
                  ))}
                </fieldset>
                <fieldset className="options" disabled={busy}>
                  <legend>Vector graphics under marks</legend>
                  {GRAPHICS_MODES.map((m) => (
                    <label key={m.value}>
                      <input
                        type="radio"
                        name="graphics"
                        checked={settings.graphics === m.value}
                        onChange={() => setSettings({ ...settings, graphics: m.value })}
                      />
                      {m.label}
                      {m.hint && <span className="muted small"> — {m.hint}</span>}
                    </label>
                  ))}
                </fieldset>
              </>
            )}
            <HiddenInfoOptions
              optional={withMarks}
              enabled={settings.removeHidden || !withMarks}
              options={settings.sanitize}
              disabled={busy}
              onEnabledChange={(removeHidden) => setSettings({ ...settings, removeHidden })}
              onChange={(sanitize) => setSettings({ ...settings, sanitize })}
            />
            {phase.name === "confirm" && phase.error && (
              <p className="error" role="alert">
                {phase.error}
              </p>
            )}
            {busy ? (
              <JobProgress
                progress={progress}
                label={withMarks ? "Applying redactions" : "Removing hidden information"}
                onCancel={stop}
                focusCancel
              />
            ) : (
              <div className="actions">
                <button type="button" onClick={onClose}>
                  Cancel
                </button>
                <button className="danger" autoFocus data-autofocus onClick={() => void apply()}>
                  {withMarks ? "Apply redactions" : "Remove hidden information"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

interface ResultProps {
  output: OutputInfo;
  marks: Mark[];
  downloaded: boolean;
  downloadError?: string;
  override: boolean;
  setOverride: (v: boolean) => void;
  onDownload: () => void;
  onShowMark: (mark: Mark) => void;
  onBack: () => void;
  onClose: () => void;
}

const STATUS_ORDER = { fail: 0, warn: 1, pass: 2 } as const;

function Result(props: ResultProps) {
  const { output, marks, downloaded, downloadError, override, setOverride } = props;
  const { verification: v, stats } = output;
  const byId = useMemo(() => new Map(marks.map((m) => [m.id, m])), [marks]);
  const issues = v.checks
    .filter((c) => c.status !== "pass")
    .sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || (a.page ?? -1) - (b.page ?? -1));
  const canDownload = v.passed || override;
  const redacted = stats.marks > 0;
  const failed = v.checks.filter((c) => c.status === "fail");
  const missed = failed.length && failed.every((c) => c.name.startsWith("sanitize-")) ? "hidden information" : "marked content";
  const sanitized = stats.sanitized.filter((a) => a.count > 0);

  return (
    <>
      <h2 id="apply-title">
        {!v.passed ? "Verification found problems" : redacted ? "Redactions applied" : "Hidden information removed"}
      </h2>
      <div className={`verdict ${v.passed ? (issues.length ? "warn" : "pass") : "fail"}`}>
        {v.passed
          ? issues.length
            ? `${redacted ? "Marked text" : "Hidden information"} was removed. ${plural(issues.length, "warning")} to review.`
            : `Verified: the ${redacted ? "marked content" : "hidden information"} is no longer in the file.`
          : `${plural(v.counts.fail, "check")} failed. Some ${missed} may still be in the file.`}
      </div>
      <ul className="stats small">
        {redacted && (
          <>
            <li>{plural(stats.marks, "mark")} applied on {plural(stats.pages.length, "page")}</li>
            <li>{plural(stats.glyphsRemoved, "character")} removed</li>
          </>
        )}
        {stats.safetyPassGlyphs > 0 && (
          <li>{plural(stats.safetyPassGlyphs, "extra character")} removed by the safety pass</li>
        )}
        {stats.annotationsRemoved > 0 && (
          <li>
            {plural(stats.annotationsRemoved, "comment, form field or link", "comments, form fields or links")}{" "}
            under marks removed
          </li>
        )}
        {stats.replacementTextRemoved > 0 && (
          <li>Hidden replacement and alternate text removed from redacted pages</li>
        )}
        {stats.textMarksAsArea.length > 0 && (
          <li>
            {plural(stats.textMarksAsArea.length, "text mark")} matched no characters and{" "}
            {stats.textMarksAsArea.length === 1 ? "was" : "were"} redacted as an area
          </li>
        )}
        {stats.overlaysSkipped.length > 0 && (
          <li>
            Overlay text left out of {plural(stats.overlaysSkipped.length, "mark")} where it did not
            fit
          </li>
        )}
        {sanitized.map((a) => (
          <li key={a.code}>{a.message}</li>
        ))}
        {stats.sanitized.length > 0 && !sanitized.length && <li>No hidden information found</li>}
        <li>
          {plural(v.counts.pass, "check")} passed
          {v.counts.warn > 0 && `, ${plural(v.counts.warn, "warning")}`}
          {v.counts.fail > 0 && `, ${v.counts.fail} failed`}
        </li>
      </ul>
      {issues.length > 0 && (
        <ul className="checks">
          {issues.map((c, i) => (
            <CheckItem key={i} check={c} mark={c.markId ? byId.get(c.markId) : undefined} onShow={props.onShowMark} />
          ))}
        </ul>
      )}
      {!v.passed && (
        <label className="inline override">
          <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} />I
          have reviewed the problems and still want to download this file
        </label>
      )}
      <ReportLinks output={output} />
      {downloadError && (
        <p className="error" role="alert">
          {downloadError}
        </p>
      )}
      {downloaded && <p className="muted small">Saved as {output.filename}. Check your downloads folder.</p>}
      <div className="actions">
        <button type="button" onClick={props.onBack}>
          Back
        </button>
        <span className="spacer" />
        <button type="button" onClick={props.onClose}>
          {downloaded ? "Done" : "Close"}
        </button>
        <button className="primary" autoFocus onClick={props.onDownload} disabled={!canDownload}>
          Download ({formatBytes(output.size)})
        </button>
      </div>
    </>
  );
}

const REPORTS: { format: ReportFormat; label: string; title: string }[] = [
  { format: "html", label: "Report", title: "A printable summary (HTML)" },
  { format: "json", label: "Audit log", title: "Everything recorded about this redaction (JSON)" },
  { format: "csv", label: "CSV", title: "One row per mark, for spreadsheets" },
];

const REPORT_TEXT: { value: ReportText; label: string }[] = [
  { value: "length", label: "Removed text: length only" },
  { value: "hash", label: "Removed text: SHA-256 hash" },
  { value: "plain", label: "Removed text: in full" },
];

function ReportLinks({ output }: { output: OutputInfo }) {
  const [text, setText] = useState<ReportText>("length");
  const [error, setError] = useState<string>();

  async function download(format: ReportFormat) {
    setError(undefined);
    try {
      await api.downloadReport(output, format, text);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div className="report-links small">
      <span className="muted">Download</span>
      {REPORTS.map((r) => (
        <button key={r.format} type="button" className="link" title={r.title} onClick={() => void download(r.format)}>
          {r.label}
        </button>
      ))}
      <select aria-label="Removed text in reports" value={text} onChange={(e) => setText(e.target.value as ReportText)}>
        {REPORT_TEXT.map((t) => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </select>
      {text === "hash" && (
        <p className="hint">Short values, such as account numbers, can be recovered from their hash.</p>
      )}
      {text === "plain" && (
        <p className="hint warning">Reports will contain the redacted text. Keep them as safe as the original.</p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function CheckItem({ check, mark, onShow }: { check: Check; mark?: Mark; onShow: (m: Mark) => void }) {
  return (
    <li className={`check ${check.status}`}>
      <span className="badge">{check.status === "fail" ? "Failed" : "Warning"}</span>
      <span className="check-body">
        {check.page !== null && <strong>Page {check.page + 1}</strong>}
        {mark && <> · {describeMark(mark)}</>}
        <br />
        {check.message}
      </span>
      {mark && (
        <button className="link" onClick={() => onShow(mark)}>
          Show
        </button>
      )}
    </li>
  );
}
