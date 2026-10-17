import { useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { describeMark, formatBytes, KIND_LABELS, plural } from "../lib/format";
import { overlayDoesNotFit } from "../lib/overlay";
import { formatPages } from "../lib/pages";
import { useMarks } from "../marks";
import { useStore } from "../store";
import type { ApplyOptions, Check, GraphicsMode, ImageMode, Mark, OutputInfo } from "../types";

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

/** Apply the marks on the server, show the verification report and offer the result for download. */
export function ApplyDialog({ onClose }: { onClose: () => void }) {
  const doc = useStore((s) => s.doc)!;
  const marks = useMarks((s) => s.marks);
  const [options, setOptions] = useState<ApplyOptions>({ images: "pixels", graphics: "covered" });
  const [phase, setPhase] = useState<Phase>({ name: "confirm" });
  const [override, setOverride] = useState(false);

  const summary = useMemo(() => {
    const kinds = { text: 0, area: 0, page: 0 };
    for (const m of marks) kinds[m.kind] += 1;
    const pages = [...new Set(marks.map((m) => m.page))].sort((a, b) => a - b);
    const unfilled = marks.filter((m) => m.appearance.fill === null).length;
    const crowded = marks.filter(overlayDoesNotFit).length;
    return { kinds, pages, unfilled, crowded };
  }, [marks]);

  async function apply() {
    setPhase({ name: "working" });
    setOverride(false);
    try {
      const output = await api.apply(doc.id, marks, options);
      setPhase({ name: "done", output, downloaded: false });
    } catch (e) {
      setPhase({ name: "confirm", error: e instanceof ApiError ? e.message : String(e) });
    }
  }

  async function download(output: OutputInfo) {
    try {
      await api.download(output);
      useMarks.getState().markApplied();
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
  const close = () => !busy && onClose();

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div
        className="modal apply-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="apply-title"
        onKeyDown={(e) => e.key === "Escape" && close()}
      >
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
            <h2 id="apply-title">Apply redactions</h2>
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
            <fieldset className="options" disabled={busy}>
              <legend>Images under marks</legend>
              {IMAGE_MODES.map((m) => (
                <label key={m.value}>
                  <input
                    type="radio"
                    name="images"
                    checked={options.images === m.value}
                    onChange={() => setOptions({ ...options, images: m.value })}
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
                    checked={options.graphics === m.value}
                    onChange={() => setOptions({ ...options, graphics: m.value })}
                  />
                  {m.label}
                  {m.hint && <span className="muted small"> — {m.hint}</span>}
                </label>
              ))}
            </fieldset>
            {phase.name === "confirm" && phase.error && (
              <p className="error" role="alert">
                {phase.error}
              </p>
            )}
            <div className="actions">
              <button type="button" onClick={close} disabled={busy}>
                Cancel
              </button>
              <button
                className="danger"
                autoFocus
                onClick={() => void apply()}
                disabled={busy || !marks.length}
              >
                {busy ? "Applying…" : "Apply redactions"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
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

  return (
    <>
      <h2 id="apply-title">{v.passed ? "Redactions applied" : "Verification found problems"}</h2>
      <div className={`verdict ${v.passed ? (issues.length ? "warn" : "pass") : "fail"}`}>
        {v.passed
          ? issues.length
            ? `Marked text was removed. ${plural(issues.length, "warning")} to review.`
            : "Verified: the marked content is no longer in the file."
          : `${plural(v.counts.fail, "check")} failed. Some marked content may still be in the file.`}
      </div>
      <ul className="stats small">
        <li>{plural(stats.marks, "mark")} applied on {plural(stats.pages.length, "page")}</li>
        <li>{plural(stats.glyphsRemoved, "character")} removed</li>
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
