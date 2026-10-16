import { memo, useEffect, useRef, useState } from "react";
import { renderPage } from "../pdf";
import { useStore } from "../store";
import type { PageInfo } from "../types";
import { TextBoxes } from "./TextBoxes";

interface Props {
  info: PageInfo;
  zoom: number;
  top: number;
  left: number;
}

/** One rendered page: canvas plus overlay layers, all in display space scaled by `zoom`. */
export const PageView = memo(function PageView({ info, zoom, top, left }: Props) {
  const pdf = useStore((s) => s.pdf);
  const showTextBoxes = useStore((s) => s.showTextBoxes);
  const loadPageText = useStore((s) => s.loadPageText);
  const holder = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"rendering" | "done" | "error">("rendering");
  const hasCanvas = useRef(false);

  useEffect(() => {
    if (!pdf) return;
    let cancelled = false;
    let cancel: (() => void) | undefined;
    // Re-render after zooming settles; until then the old canvas is stretched by CSS.
    const timer = setTimeout(
      async () => {
        try {
          const page = await pdf.getPage(info.index + 1);
          if (cancelled) return;
          const { canvas, task } = renderPage(page, zoom);
          cancel = () => task.cancel();
          await task.promise;
          if (cancelled) return;
          canvas.className = "page-canvas";
          holder.current?.replaceChildren(canvas);
          hasCanvas.current = true;
          setStatus("done");
        } catch (err) {
          if (!cancelled && (err as Error)?.name !== "RenderingCancelledException") {
            setStatus("error");
          }
        }
      },
      hasCanvas.current ? 150 : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
      cancel?.();
    };
  }, [pdf, info.index, zoom]);

  useEffect(() => {
    // Prefetch text geometry once the page has been on screen briefly.
    const timer = setTimeout(() => void loadPageText(info.index), 200);
    return () => clearTimeout(timer);
  }, [info.index, loadPageText]);

  useEffect(
    () => () => {
      void pdf?.getPage(info.index + 1).then((page) => page.cleanup());
    },
    [pdf, info.index],
  );

  return (
    <div
      className="page"
      data-page={info.index}
      style={{ top, left, width: info.width * zoom, height: info.height * zoom }}
    >
      <div className="page-canvas-holder" ref={holder} />
      {status === "rendering" && <div className="page-status">Rendering…</div>}
      {status === "error" && <div className="page-status error">This page could not be rendered</div>}
      {showTextBoxes && <TextBoxes info={info} zoom={zoom} />}
    </div>
  );
});
