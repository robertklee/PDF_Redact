import { useStore } from "../store";
import type { PageInfo } from "../types";

/** Debug layer: the server's text geometry drawn over the rendered page. */
export function TextBoxes({ info, zoom }: { info: PageInfo; zoom: number }) {
  const text = useStore((s) => s.pageText[info.index]);
  if (!text || typeof text === "string") return null;
  return (
    <svg
      className="layer text-boxes"
      viewBox={`0 0 ${info.width} ${info.height}`}
      width={info.width * zoom}
      height={info.height * zoom}
    >
      {text.lines.map((line, i) => (
        <g key={i}>
          <rect
            className="line-box"
            x={line.bbox[0]}
            y={line.bbox[1]}
            width={line.bbox[2] - line.bbox[0]}
            height={line.bbox[3] - line.bbox[1]}
          />
          {line.boxes.map((b, j) => (
            <rect key={j} className="char-box" x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]} />
          ))}
        </g>
      ))}
    </svg>
  );
}
