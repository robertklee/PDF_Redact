import { useState } from "react";
import { useStore } from "../store";

export function NoticeBar() {
  const notices = useStore((s) => s.doc?.notices ?? []);
  const docId = useStore((s) => s.doc?.id);
  const [dismissed, setDismissed] = useState<string | null>(null);
  if (!notices.length || dismissed === docId) return null;
  const warning = notices.some((n) => n.level === "warning");
  return (
    <div className={`notice-bar ${warning ? "warning" : "info"}`} role="status">
      <ul>
        {notices.map((n) => (
          <li key={n.code}>{n.message}</li>
        ))}
      </ul>
      <button className="link" onClick={() => setDismissed(docId ?? null)} aria-label="Dismiss">
        ✕
      </button>
    </div>
  );
}
