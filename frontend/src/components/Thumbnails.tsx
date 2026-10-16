import { memo, useEffect, useRef, useState } from "react";
import { renderPage } from "../pdf";
import { useStore } from "../store";
import type { PageInfo } from "../types";

const THUMB_WIDTH = 112;

const Thumb = memo(function Thumb({ info, active }: { info: PageInfo; active: boolean }) {
  const pdf = useStore((s) => s.pdf);
  const goToPage = useStore((s) => s.goToPage);
  const ref = useRef<HTMLButtonElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const scale = THUMB_WIDTH / info.width;

  useEffect(() => {
    const el = ref.current!;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), {
      root: el.closest(".thumbnails"),
      rootMargin: "300px 0px",
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !pdf || holder.current?.firstChild) return;
    let cancel: (() => void) | undefined;
    let cancelled = false;
    void (async () => {
      try {
        const page = await pdf.getPage(info.index + 1);
        if (cancelled) return;
        const { canvas, task } = renderPage(page, scale);
        cancel = () => task.cancel();
        await task.promise;
        if (!cancelled) holder.current?.replaceChildren(canvas);
      } catch {
        /* cancelled or unrenderable; the placeholder stays */
      }
    })();
    return () => {
      cancelled = true;
      cancel?.();
    };
  }, [visible, pdf, info.index, scale]);

  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);

  return (
    <button
      ref={ref}
      className={`thumb${active ? " active" : ""}`}
      onClick={() => goToPage(info.index)}
      title={`Page ${info.index + 1}`}
    >
      <div className="thumb-page" ref={holder} style={{ width: THUMB_WIDTH, height: info.height * scale }} />
      <span className="thumb-label">{info.index + 1}</span>
    </button>
  );
});

export function Thumbnails() {
  const pages = useStore((s) => s.doc?.pages ?? []);
  const currentPage = useStore((s) => s.currentPage);
  return (
    <nav className="thumbnails" aria-label="Pages">
      {pages.map((p) => (
        <Thumb key={p.index} info={p} active={p.index === currentPage} />
      ))}
    </nav>
  );
}
