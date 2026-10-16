import { memo, type PointerEvent, useMemo, useRef, useState } from "react";
import {
  clampedOffset,
  contains,
  fromPoints,
  type Handle,
  HANDLES,
  handlePoint,
  height,
  intersects,
  type Point,
  resize,
  roundRect,
  translate,
  width,
} from "../lib/geometry";
import { overlayLayout } from "../lib/overlay";
import {
  type Caret,
  caretAt,
  lineAt,
  nearText,
  selectBetween,
  selectionFromRanges,
  wordAt,
} from "../lib/textSelection";
import { useMarks } from "../marks";
import { useStore } from "../store";
import type { Mark, PageInfo, Rect } from "../types";

const DRAG_THRESHOLD_PX = 3;
const MIN_AREA_PX = 4;
const HANDLE_PX = 8;
const PAGE_MARK_EDGE_PX = 10;
const MULTI_CLICK_MS = 450;

const HANDLE_CURSORS: Record<Handle, string> = {
  n: "ns-resize",
  s: "ns-resize",
  e: "ew-resize",
  w: "ew-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
  nw: "nwse-resize",
  se: "nwse-resize",
};

type Gesture =
  | { type: "text"; start: Point; moved: boolean; anchor: Caret; hit: Mark | null }
  | { type: "area"; start: Point; moved: boolean; hit: Mark | null }
  | { type: "marquee"; start: Point; moved: boolean; additive: boolean }
  | { type: "move"; start: Point; moved: boolean; origin: Map<string, Rect[]>; key: string }
  | { type: "resize"; start: Point; moved: boolean; id: string; handle: Handle; origin: Rect; key: string };

type Draft = { kind: "text"; rects: Rect[] } | { kind: "area" | "marquee"; rect: Rect };

let gestureSeq = 0;

interface Props {
  info: PageInfo;
  zoom: number;
}

/** Marks of one page and the pointer interactions that create and edit them. */
export const MarkLayer = memo(function MarkLayer({ info, zoom }: Props) {
  const allMarks = useMarks((s) => s.marks);
  const selection = useMarks((s) => s.selection);
  const preview = useMarks((s) => s.preview);
  const pageTextEntry = useStore((s) => s.pageText[info.index]);
  const pageText = typeof pageTextEntry === "object" ? pageTextEntry : null;

  const marks = useMemo(() => allMarks.filter((m) => m.page === info.index), [allMarks, info.index]);
  const selected = useMemo(() => new Set(selection), [selection]);
  const handleMark =
    selection.length === 1 ? marks.find((m) => m.id === selection[0] && m.kind === "area") : undefined;

  const [draft, setDraft] = useState<Draft | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const clicks = useRef({ at: 0, x: 0, y: 0, count: 0, wordMark: null as string | null, key: "" });

  const bounds: Rect = [0, 0, info.width, info.height];
  const lines = pageText?.lines ?? [];
  const slop = Math.max(1, 4 / zoom);

  function toPoint(e: PointerEvent): Point {
    const box = svg.current!.getBoundingClientRect();
    return {
      x: Math.min(Math.max((e.clientX - box.left) / zoom, 0), info.width),
      y: Math.min(Math.max((e.clientY - box.top) / zoom, 0), info.height),
    };
  }

  function hitHandle(p: Point): Handle | null {
    if (!handleMark) return null;
    const reach = (HANDLE_PX / 2 + 2) / zoom;
    return (
      HANDLES.find((h) => {
        const hp = handlePoint(handleMark.rects[0], h);
        return Math.abs(p.x - hp.x) <= reach && Math.abs(p.y - hp.y) <= reach;
      }) ?? null
    );
  }

  /** Topmost mark under `p`. Page marks are only hit near the page edge. */
  function hitMark(p: Point): Mark | null {
    const tolerance = 2 / zoom;
    for (let i = marks.length - 1; i >= 0; i--) {
      const m = marks[i];
      if (m.kind !== "page" && m.rects.some((r) => contains(r, p, tolerance))) return m;
    }
    const edge = PAGE_MARK_EDGE_PX / zoom;
    const nearEdge =
      p.x < edge || p.y < edge || p.x > info.width - edge || p.y > info.height - edge;
    return nearEdge ? (marks.findLast((m) => m.kind === "page") ?? null) : null;
  }

  function addTextMark(sel: ReturnType<typeof selectionFromRanges>, replace: string[] = [], key?: string) {
    if (!sel) return null;
    const [mark] = useMarks.getState().addMarks(
      [{ page: info.index, kind: "text", rects: sel.rects.map(roundRect), text: sel.text, angle: sel.angle }],
      replace,
      key,
    );
    return mark;
  }

  function clickSelect(hit: Mark | null, e: PointerEvent) {
    const { select } = useMarks.getState();
    if (hit) select([hit.id], e.shiftKey || e.metaKey || e.ctrlKey ? "toggle" : "replace");
    else select([]);
  }

  function onPointerDown(e: PointerEvent<SVGSVGElement>) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = toPoint(e);
    const store = useMarks.getState();
    const additive = e.shiftKey || e.metaKey || e.ctrlKey;

    const c = clicks.current;
    const now = e.timeStamp;
    const sameSpot = Math.hypot(e.clientX - c.x, e.clientY - c.y) < 5;
    c.count = now - c.at < MULTI_CLICK_MS && sameSpot ? c.count + 1 : 1;
    Object.assign(c, { at: now, x: e.clientX, y: e.clientY });
    setHoverId(null);

    const handle = hitHandle(p);
    if (handle && handleMark) {
      const key = `resize:${++gestureSeq}`;
      gesture.current = { type: "resize", start: p, moved: false, id: handleMark.id, handle, origin: handleMark.rects[0], key };
      return;
    }

    const hit = hitMark(p);
    if (store.tool === "select") {
      if (!hit) {
        gesture.current = { type: "marquee", start: p, moved: false, additive };
        return;
      }
      if (additive) {
        store.select([hit.id], "toggle");
        return;
      }
      if (!selected.has(hit.id)) store.select([hit.id]);
      const ids = new Set(useMarks.getState().selection);
      const movable = marks.filter((m) => ids.has(m.id) && m.kind === "area");
      if (hit.kind === "area" && movable.length) {
        const origin = new Map(movable.map((m) => [m.id, m.rects]));
        gesture.current = { type: "move", start: p, moved: false, origin, key: `move:${++gestureSeq}` };
      }
      return;
    }

    if (store.tool === "text" && pageText && c.count >= 2) {
      gesture.current = null;
      if (c.count > 3) return;
      const range = c.count === 2 ? wordAt(lines, p, slop) : lineAt(lines, p, slop);
      if (!range) return;
      const replace = c.count === 3 && c.wordMark ? [c.wordMark] : [];
      // The line mark replaces the word mark in the same undo step.
      if (c.count === 2) c.key = `multiclick:${++gestureSeq}`;
      const mark = addTextMark(selectionFromRanges(lines, [range]), replace, c.key);
      c.wordMark = c.count === 2 ? (mark?.id ?? null) : null;
      return;
    }
    c.wordMark = null;

    if (store.tool === "text" && pageText && nearText(lines, p, slop)) {
      gesture.current = { type: "text", start: p, moved: false, anchor: caretAt(lines, p)!, hit };
    } else {
      gesture.current = { type: "area", start: p, moved: false, hit };
    }
  }

  function updateHover(p: Point) {
    const el = svg.current!;
    const handle = hitHandle(p);
    const hit = handle ? null : hitMark(p);
    setHoverId(hit?.id ?? null);
    const tool = useMarks.getState().tool;
    let cursor: string;
    if (handle) cursor = HANDLE_CURSORS[handle];
    else if (tool === "select") cursor = hit ? (hit.kind === "area" ? "move" : "pointer") : "default";
    else if (hit) cursor = "pointer";
    else cursor = tool === "text" && nearText(lines, p, slop) ? "text" : "crosshair";
    el.style.cursor = cursor;
  }

  function onPointerMove(e: PointerEvent<SVGSVGElement>) {
    const p = toPoint(e);
    const g = gesture.current;
    if (!g) {
      updateHover(p);
      return;
    }
    if (!g.moved) {
      if (Math.hypot(p.x - g.start.x, p.y - g.start.y) * zoom < DRAG_THRESHOLD_PX) return;
      g.moved = true;
    }
    const store = useMarks.getState();
    switch (g.type) {
      case "text": {
        const sel = pageText && selectBetween(pageText, g.anchor, caretAt(lines, p)!);
        setDraft({ kind: "text", rects: sel?.rects ?? [] });
        break;
      }
      case "area":
      case "marquee":
        setDraft({ kind: g.type, rect: fromPoints(g.start, p) });
        break;
      case "move": {
        const off = clampedOffset([...g.origin.values()].flat(), p.x - g.start.x, p.y - g.start.y, bounds);
        store.updateMarks(
          [...g.origin.keys()],
          (m) => ({ ...m, rects: g.origin.get(m.id)!.map((r) => roundRect(translate(r, off.x, off.y))) }),
          g.key,
        );
        break;
      }
      case "resize": {
        const r = roundRect(resize(g.origin, g.handle, p));
        if (width(r) >= 1 && height(r) >= 1) store.updateMarks([g.id], (m) => ({ ...m, rects: [r] }), g.key);
        break;
      }
    }
  }

  function onPointerUp(e: PointerEvent<SVGSVGElement>) {
    const g = gesture.current;
    gesture.current = null;
    setDraft(null);
    if (!g) return;
    const p = toPoint(e);
    const store = useMarks.getState();
    switch (g.type) {
      case "text":
        if (!g.moved) clickSelect(g.hit, e);
        else if (pageText) addTextMark(selectBetween(pageText, g.anchor, caretAt(lines, p)!));
        break;
      case "area": {
        if (!g.moved) {
          clickSelect(g.hit, e);
          break;
        }
        const r = roundRect(fromPoints(g.start, p));
        if (width(r) * zoom >= MIN_AREA_PX && height(r) * zoom >= MIN_AREA_PX) {
          store.addMarks([{ page: info.index, kind: "area", rects: [r] }]);
        }
        break;
      }
      case "marquee": {
        if (!g.moved) {
          if (!g.additive) store.select([]);
          break;
        }
        const r = fromPoints(g.start, p);
        const ids = marks
          .filter((m) => m.kind !== "page" && m.rects.some((x) => intersects(x, r)))
          .map((m) => m.id);
        store.select(ids, g.additive ? "add" : "replace");
        break;
      }
    }
    updateHover(p);
  }

  function onPointerCancel() {
    gesture.current = null;
    setDraft(null);
  }

  const hatchId = `hatch-${info.index}`;
  const handleSize = HANDLE_PX / zoom;

  return (
    <svg
      ref={svg}
      className="mark-layer"
      viewBox={`0 0 ${info.width} ${info.height}`}
      width={info.width * zoom}
      height={info.height * zoom}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onPointerLeave={() => !gesture.current && setHoverId(null)}
    >
      <defs>
        <pattern
          id={hatchId}
          patternUnits="userSpaceOnUse"
          width={12 / zoom}
          height={12 / zoom}
          patternTransform="rotate(45)"
        >
          <rect width={4 / zoom} height={12 / zoom} className="hatch" />
        </pattern>
      </defs>
      {marks.map((m) => (
        <MarkShape
          key={m.id}
          mark={m}
          selected={selected.has(m.id)}
          final={preview || hoverId === m.id}
          hatch={hatchId}
        />
      ))}
      {draft?.kind === "text" &&
        draft.rects.map((r, i) => <rect key={i} className="draft-text" {...box(r)} />)}
      {(draft?.kind === "area" || draft?.kind === "marquee") && (
        <rect className={`draft-${draft.kind}`} {...box(draft.rect)} />
      )}
      {handleMark &&
        HANDLES.map((h) => {
          const hp = handlePoint(handleMark.rects[0], h);
          return (
            <rect
              key={h}
              className="handle"
              x={hp.x - handleSize / 2}
              y={hp.y - handleSize / 2}
              width={handleSize}
              height={handleSize}
            />
          );
        })}
    </svg>
  );
});

const box = (r: Rect) => ({ x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1] });

interface ShapeProps {
  mark: Mark;
  selected: boolean;
  /** Show the appearance the redaction will have in the output. */
  final: boolean;
  hatch: string;
}

const MarkShape = memo(function MarkShape({ mark, selected, final, hatch }: ShapeProps) {
  const { appearance } = mark;
  return (
    <g className={`mark kind-${mark.kind}${selected ? " selected" : ""}`} data-mark={mark.id}>
      {mark.rects.map((r, i) => {
        if (!final) {
          return (
            <rect
              key={i}
              className="mark-box"
              style={mark.kind === "page" ? { fill: `url(#${hatch})` } : undefined}
              {...box(r)}
            />
          );
        }
        const layout = overlayLayout(r, appearance, mark.kind === "text" ? mark.angle : undefined);
        return (
          <g key={i}>
            <rect
              className={appearance.fill ? "mark-final" : "mark-final no-fill"}
              fill={appearance.fill ?? "none"}
              {...box(r)}
            />
            {layout && (
              <text
                className="mark-overlay"
                x={layout.x}
                y={layout.y}
                fontSize={layout.size}
                fill={appearance.textColor}
                transform={layout.angle ? `rotate(${-layout.angle} ${layout.x} ${layout.y})` : undefined}
              >
                {layout.text}
              </text>
            )}
          </g>
        );
      })}
      {selected && mark.rects.map((r, i) => <rect key={`s${i}`} className="mark-selection" {...box(r)} />)}
    </g>
  );
});
