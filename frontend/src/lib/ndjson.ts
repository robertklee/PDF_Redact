/** The JSON values in a stream of newline-delimited JSON, as they arrive. */
export async function* jsonLines(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  try {
    while (!finished) {
      const { done, value } = await reader.read();
      finished = done;
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = finished ? "" : lines.pop()!;
      for (const line of lines) {
        if (line.trim()) yield JSON.parse(line);
      }
    }
  } finally {
    // Stopped early (a result arrived, or the caller gave up): don't leave the response open.
    if (!finished) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
