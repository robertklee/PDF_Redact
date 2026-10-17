import type { Progress } from "../api";

/** What a long operation is doing, how far it got, and a way to stop it. */
export function JobProgress(props: {
  progress: Progress | null;
  /** Shown until the operation reports what it is doing. */
  label: string;
  onCancel?: () => void;
  /** Move the focus to the Cancel button, e.g. when it replaces the button that started the work. */
  focusCancel?: boolean;
}) {
  const { progress, label, onCancel, focusCancel } = props;
  const phase = progress?.phase ?? label;
  const known = progress !== null && progress.total > 0;
  return (
    <div className="job-progress">
      <div className="job-progress-row">
        <span role="status" className="small">
          {phase}…
        </span>
        {known && <span className="muted small">{Math.floor((100 * progress.done) / progress.total)}%</span>}
      </div>
      <div className="job-progress-row">
        <progress aria-label={phase} value={known ? progress.done : undefined} max={known ? progress.total : undefined} />
        {onCancel && (
          <button type="button" onClick={onCancel} autoFocus={focusCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
