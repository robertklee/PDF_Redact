import { memo, useEffect, useMemo, useRef, useState } from "react";
import { renderPage } from "../pdf";
import { useMarks } from "../marks";
import { useStore } from "../store";
import type { PageInfo } from "../types";

const THUMB_WIDTH = 112;

interface ThumbProps {
  info: PageInfo;
  active: boolean;
  marks: number;
}

const Thumb = memo(function Thumb({ info, active, marks }: ThumbProps) {
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
      title={`Page ${info.index + 1}${marks ? ` (${marks} mark${marks === 1 ? "" : "s"})` : ""}`}
    >
      <div className="thumb-page" ref={holder} style={{ width: THUMB_WIDTH, height: info.height * scale }} />
      {marks > 0 && <span className="thumb-badge">{marks}</span>}
      <span className="thumb-label">{info.index + 1}</span>
    </button>
  );
});

export function Thumbnails() {
  const pages = useStore((s) => s.doc?.pages ?? []);
  const currentPage = useStore((s) => s.currentPage);
  const marks = useMarks((s) => s.marks);
  const counts = useMemo(() => {
    const byPage = new Map<number, number>();
    for (const m of marks) byPage.set(m.page, (byPage.get(m.page) ?? 0) + 1);
    return byPage;
  }, [marks]);
  return (
    <nav className="thumbnails" aria-label="Pages">
      {pages.map((p) => (
        <Thumb key={p.index} info={p} active={p.index === currentPage} marks={counts.get(p.index) ?? 0} />
      ))}
    </nav>
  );
}
