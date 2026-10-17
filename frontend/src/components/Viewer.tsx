import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { computeLayout, fitZoom, type Layout, pageAt, pagesInRange } from "../lib/layout";
import { useStore } from "../store";
import { PageView } from "./PageView";

interface View {
  top: number;
  height: number;
  width: number;
}

/** Continuous-scroll page view. Only pages near the viewport are mounted. */
export function Viewer() {
  const doc = useStore((s) => s.doc)!;
  const zoom = useStore((s) => s.zoom);
  const fit = useStore((s) => s.fit);
  const currentPage = useStore((s) => s.currentPage);
  const scrollRequest = useStore((s) => s.scrollRequest);
  const setZoom = useStore((s) => s.setZoom);
  const setCurrentPage = useStore((s) => s.setCurrentPage);

  const ref = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ top: 0, height: 0, width: 0 });
  const layout = useMemo(() => computeLayout(doc.pages, zoom), [doc.pages, zoom]);
  const innerWidth = Math.max(view.width, layout.width);

  const measure = useCallback(() => {
    const el = ref.current;
    if (el) setView({ top: el.scrollTop, height: el.clientHeight, width: el.clientWidth });
  }, []);

  useLayoutEffect(() => {
    const el = ref.current!;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    return () => observer.disconnect();
  }, [measure]);

  const frame = useRef(0);
  const onScroll = useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(measure);
  }, [measure]);

  // Fit modes follow the window size.
  useEffect(() => {
    if (!fit || !view.width) return;
    const next = fitZoom(doc.pages, fit, view.width, view.height, currentPage);
    if (Math.abs(next - zoom) > 1e-3) setZoom(next, fit);
  }, [fit, view.width, view.height, doc.pages, currentPage, zoom, setZoom]);

  // Keep the point at the centre of the viewport fixed while zooming.
  const previous = useRef<{ zoom: number; layout: Layout; innerWidth: number }>(null);
  useLayoutEffect(() => {
    const el = ref.current!;
    const prev = previous.current;
    if (prev && prev.zoom !== zoom && prev.layout.tops.length) {
      // Anchor the viewport centre, or the top edge when scrolled to the very top.
      const anchor = el.scrollTop <= 0 ? 0 : el.clientHeight / 2;
      const y = el.scrollTop + anchor;
      const i = pageAt(prev.layout, y);
      const fraction = (y - prev.layout.tops[i]) / prev.layout.heights[i];
      el.scrollTop = anchor ? layout.tops[i] + fraction * layout.heights[i] - anchor : 0;
      const centerX = (el.scrollLeft + el.clientWidth / 2) / prev.innerWidth;
      el.scrollLeft = centerX * innerWidth - el.clientWidth / 2;
      measure();
    }
    previous.current = { zoom, layout, innerWidth };
  }, [zoom, layout, innerWidth, measure]);

  useEffect(() => {
    if (!scrollRequest) return;
    const el = ref.current!;
    const { page, y } = scrollRequest;
    // Read zoom without depending on it: only new requests should scroll.
    const z = useStore.getState().zoom;
    const top = computeLayout(doc.pages, z).tops[page];
    el.scrollTop = y === undefined ? top - 8 : top + y * z - el.clientHeight / 3;
    measure();
  }, [scrollRequest, doc.pages, measure]);

  useEffect(() => {
    if (view.height) setCurrentPage(pageAt(layout, view.top + view.height / 3));
  }, [layout, view.top, view.height, setCurrentPage]);

  // Ctrl/Cmd + wheel (and trackpad pinch) zooms instead of scrolling the page.
  useEffect(() => {
    const el = ref.current!;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const { zoom: z, setZoom: set } = useStore.getState();
      set(z * Math.exp(-e.deltaY * 0.0025));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const [first, last] = pagesInRange(layout, view.top - view.height, view.top + 2 * view.height);
  const visible: number[] = [];
  for (let i = first; i <= last; i++) visible.push(i);

  return (
    // Focusable so the pages can be scrolled with the keyboard.
    <div className="viewer" ref={ref} onScroll={onScroll} tabIndex={0} role="region" aria-label="Pages">
      <div className="viewer-inner" style={{ height: layout.height, width: innerWidth }}>
        {visible.map((i) => (
          <PageView
            key={i}
            info={doc.pages[i]}
            zoom={zoom}
            top={layout.tops[i]}
            left={(innerWidth - layout.widths[i]) / 2}
          />
        ))}
      </div>
    </div>
  );
}
