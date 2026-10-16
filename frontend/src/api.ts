import type {
  ApplyOptions,
  DetectRequest,
  Detector,
  DocumentInfo,
  Mark,
  OutputInfo,
  PageText,
  SearchRequest,
  SearchResponse,
} from "./types";
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

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-Session-Token", token);
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
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

  search(id: string, request: SearchRequest): Promise<SearchResponse> {
    return post(`/api/documents/${id}/search`, request);
  },

  detect(id: string, request: DetectRequest): Promise<SearchResponse> {
    return post(`/api/documents/${id}/detect`, request);
  },

  detectors(): Promise<Detector[]> {
    return json("/api/detectors");
  },

  apply(id: string, marks: Mark[], options: ApplyOptions): Promise<OutputInfo> {
    const wire = marks.map(({ id, page, kind, rects, appearance }) => ({
      id,
      page,
      kind,
      rects: kind === "page" ? [] : rects,
      appearance,
    }));
    return post(`/api/documents/${id}/apply`, { marks: wire, options, searchTerms: searchTerms(marks) });
  },

  /** Fetch the output (the token must go in a header) and hand it to the browser as a download. */
  async download(output: OutputInfo): Promise<void> {
    const blob = await (await request(`/api/outputs/${output.id}/file`)).blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = output.filename;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },
};
