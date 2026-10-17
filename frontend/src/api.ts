import type {
  ApplyOptions,
  DetectRequest,
  Detector,
  DocumentInfo,
  Mark,
  OutputInfo,
  PageText,
  ReportFormat,
  ReportText,
  SearchRequest,
  SearchResponse,
} from "./types";
import { saveBlob } from "./lib/download";
import { jsonLines } from "./lib/ndjson";
import { searchTerms } from "./lib/search";

const TOKEN_KEY = "pdf-redact-token";

/** The server prints a URL with #token=…; keep it for this tab and remove it from the address bar. */
function sessionToken(): string {
  const match = /(?:^|[#&])token=([^&]+)/.exec(window.location.hash);
  if (match) {
    sessionStorage.setItem(TOKEN_KEY, decodeURIComponent(match[1]));
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  return sessionStorage.getItem(TOKEN_KEY) ?? (import.meta.env.DEV ? "dev" : "");
}

const token = sessionToken();

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** What a long operation is doing; `total` is 0 when unknown. */
export interface Progress {
  phase: string;
  done: number;
  total: number;
}

export interface JobOptions {
  signal?: AbortSignal;
  onProgress?: (progress: Progress) => void;
}

const abortError = () => new DOMException("Cancelled", "AbortError");

/** Whether an operation failed because it was cancelled. */
export const isAbort = (err: unknown) => err instanceof DOMException && err.name === "AbortError";

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-Session-Token", token);
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    if (init.signal?.aborted) throw abortError();
    throw new ApiError(0, "Cannot reach the PDF Redact server. Is it still running?");
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : (body.detail?.[0]?.msg ?? message);
    } catch {
      /* not JSON */
    }
    if (res.status === 401) message = "Session expired. Reopen the link printed by the server.";
    throw new ApiError(res.status, message);
  }
  return res;
}

/** The filename in a Content-Disposition header. */
export function attachmentName(res: Response): string | null {
  const header = res.headers.get("Content-Disposition") ?? "";
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(header);
  if (encoded) return decodeURIComponent(encoded[1]);
  return /filename="([^"]+)"/i.exec(header)?.[1] ?? null;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await request(path, init)).json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return json<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const NDJSON = "application/x-ndjson";

type JobEvent<T> =
  | { type: "job"; id: string }
  | ({ type: "progress" } & Progress)
  | { type: "result"; result: T }
  | { type: "error"; status: number; detail: string }
  | { type: "cancelled" };

/**
 * POST a long operation and follow its progress. Aborting `signal` cancels it on the server and
 * rejects with an AbortError (see `isAbort`).
 */
async function runJob<T>(path: string, body: unknown, { signal, onProgress }: JobOptions = {}): Promise<T> {
  if (signal?.aborted) throw abortError();
  const res = await request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: NDJSON },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.body || !res.headers.get("Content-Type")?.startsWith(NDJSON)) return res.json() as Promise<T>;

  let jobId: string | null = null;
  // Dropping the connection also stops the job, but say so explicitly in case a proxy keeps it open.
  const cancel = () => {
    if (jobId) request(`/api/jobs/${jobId}`, { method: "DELETE" }).catch(() => {});
  };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    for await (const line of jsonLines(res.body)) {
      const event = line as JobEvent<T>;
      if (event.type === "job") jobId = event.id;
      else if (event.type === "progress") onProgress?.({ phase: event.phase, done: event.done, total: event.total });
      else if (event.type === "result") return event.result;
      else if (event.type === "error") throw new ApiError(event.status, event.detail);
      else if (event.type === "cancelled") break;
    }
  } catch (err) {
    if (signal?.aborted) throw abortError();
    if (err instanceof ApiError) throw err;
    throw new ApiError(0, "Lost the connection to the PDF Redact server. Is it still running?");
  } finally {
    signal?.removeEventListener("abort", cancel);
  }
  if (signal?.aborted) throw abortError();
  throw new ApiError(0, "The server stopped before finishing. Try again.");
}

/** Marks as the server takes them; only search and detection text is sent (see `searchTerms`). */
const wireMarks = (marks: Mark[]) =>
  marks.map(({ id, page, kind, rects, appearance, source, category, createdAt }) => ({
    id,
    page,
    kind,
    rects: kind === "page" ? [] : rects,
    appearance,
    source: source ?? "manual",
    category: category?.slice(0, 100) ?? null,
    createdAt,
  }));

export const api = {
  upload(file: File): Promise<DocumentInfo> {
    return json(`/api/documents?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: file,
    });
  },

  unlock(id: string, password: string): Promise<DocumentInfo> {
    return post(`/api/documents/${id}/unlock`, { password });
  },

  async close(id: string): Promise<void> {
    await request(`/api/documents/${id}`, { method: "DELETE" });
  },

  pageText(id: string, page: number): Promise<PageText> {
    return json(`/api/documents/${id}/pages/${page}/text`);
  },

  search(id: string, request: SearchRequest, options?: JobOptions): Promise<SearchResponse> {
    return runJob(`/api/documents/${id}/search`, request, options);
  },

  detect(id: string, request: DetectRequest, options?: JobOptions): Promise<SearchResponse> {
    return runJob(`/api/documents/${id}/detect`, request, options);
  },

  detectors(): Promise<Detector[]> {
    return json("/api/detectors");
  },

  apply(id: string, marks: Mark[], options: ApplyOptions, job?: JobOptions): Promise<OutputInfo> {
    const body = { marks: wireMarks(marks), options, searchTerms: searchTerms(marks) };
    return runJob(`/api/documents/${id}/apply`, body, job);
  },

  /** Download a copy of the original carrying the marks as unapplied /Redact annotations. */
  async exportMarked(id: string, filename: string, marks: Mark[]): Promise<void> {
    const res = await request(`/api/documents/${id}/marked`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ marks: wireMarks(marks) }),
    });
    saveBlob(await res.blob(), attachmentName(res) ?? filename.replace(/\.pdf$/i, "") + "_marked.pdf");
  },

  /** Fetch the output (the token must go in a header) and hand it to the browser as a download. */
  async download(output: OutputInfo): Promise<void> {
    saveBlob(await (await request(`/api/outputs/${output.id}/file`)).blob(), output.filename);
  },

  /** Download the audit log or report of an output, showing the removed text as chosen. */
  async downloadReport(output: OutputInfo, format: ReportFormat, text: ReportText): Promise<void> {
    const params = new URLSearchParams({ format, text });
    const res = await request(`/api/outputs/${output.id}/report?${params}`);
    saveBlob(await res.blob(), attachmentName(res) ?? `redaction_report.${format}`);
  },
};
