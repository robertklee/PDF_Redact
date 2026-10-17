import { describe, expect, it } from "vitest";
import { jsonLines } from "./ndjson";

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === "string" ? encoder.encode(c) : c);
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<unknown[]> {
  const out = [];
  for await (const value of jsonLines(stream)) out.push(value);
  return out;
}

describe("jsonLines", () => {
  it("splits lines across chunk boundaries", async () => {
    const stream = streamOf(['{"a":1}\n{"b"', ':2}\n\n{"c":', "3}"]);
    expect(await collect(stream)).toEqual([{ a: 1 }, { b: 2 }, { c: 3 }]);
  });

  it("decodes characters split across chunks", async () => {
    const bytes = new TextEncoder().encode('{"t":"é—"}\n');
    expect(await collect(streamOf([bytes.slice(0, 7), bytes.slice(7)]))).toEqual([{ t: "é—" }]);
  });

  it("cancels the stream when the reader stops early", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"type":"result"}\n'));
      },
      cancel() {
        cancelled = true;
      },
    });
    for await (const value of jsonLines(stream)) {
      expect(value).toEqual({ type: "result" });
      break;
    }
    expect(cancelled).toBe(true);
  });

  it("rejects malformed lines", async () => {
    await expect(collect(streamOf(["{oops}\n"]))).rejects.toThrow(SyntaxError);
  });
});
