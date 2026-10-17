import { type FormEvent, useState } from "react";
import { useStore } from "../store";
import { Modal } from "./Modal";

export function PasswordDialog() {
  const doc = useStore((s) => s.doc);
  const unlock = useStore((s) => s.unlock);
  const closeDocument = useStore((s) => s.closeDocument);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await unlock(password);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal labelledBy="password-title">
      <form className="modal" onSubmit={submit}>
        <h2 id="password-title">Password required</h2>
        <p>
          <strong>{doc?.filename}</strong> is protected. Enter its password to open it.
        </p>
        <input
          type="password"
          data-autofocus
          aria-label="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" onClick={() => void closeDocument()}>
            Cancel
          </button>
          <button className="primary" type="submit" disabled={busy}>
            Open
          </button>
        </div>
      </form>
    </Modal>
  );
}
