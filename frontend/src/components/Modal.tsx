import { type ReactNode, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";

/**
 * A modal dialog. The rest of the page is inert while it is open, so the focus stays inside it;
 * when it closes, the focus returns to where it was. Give the element to focus first a
 * `data-autofocus` attribute (React's autoFocus runs before the dialog is shown); the text of an
 * input focused this way is selected.
 *
 * `onDismiss` runs on Escape and on a click outside the dialog, saying which; leave it out if the
 * dialog must be answered with one of its buttons.
 */
export function Modal({
  labelledBy,
  onDismiss,
  children,
}: {
  labelledBy: string;
  onDismiss?: (how: "escape" | "outside") => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useLayoutEffect(() => {
    const dialog = ref.current!;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    const first = dialog.querySelector<HTMLElement>("[data-autofocus]");
    first?.focus();
    // Typing replaces a suggested value instead of adding to it.
    if (first instanceof HTMLInputElement) first.select();
    return () => {
      dialog.close();
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  return createPortal(
    <dialog
      ref={ref}
      className="modal-backdrop"
      aria-labelledby={labelledBy}
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        // Not the browser's own handling, which would close the dialog behind React's back.
        e.preventDefault();
        onDismiss?.("escape");
      }}
      onCancel={(e) => {
        e.preventDefault();
        onDismiss?.("escape");
      }}
      onMouseDown={(e) => e.target === e.currentTarget && onDismiss?.("outside")}
    >
      {children}
    </dialog>,
    document.body,
  );
}
