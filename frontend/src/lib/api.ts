import { getCookie, refreshAuthSession } from "@/lib/auth";

// Use same-origin API by default to work behind reverse proxy (nginx) in Docker.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
const DEFAULT_API_TIMEOUT_MS = 15000;
let refreshInFlight: Promise<boolean> | null = null;

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type ApiOptions = RequestInit & {
  retryOn401?: boolean;
  timeoutMs?: number;
};

export async function api<T>(path: string, options?: ApiOptions): Promise<T> {
  const retryOn401 = options?.retryOn401 ?? true;
  const timeoutMs = Math.max(1, Number(options?.timeoutMs ?? DEFAULT_API_TIMEOUT_MS));
  const body = options?.body;
  const isMultipartBody = typeof FormData !== "undefined" && body instanceof FormData;
  const shouldSetJsonContentType = body !== undefined && !isMultipartBody;
  const run = async (): Promise<Response> => {
    const timeoutController = new AbortController();
    const timeoutId = globalThis.setTimeout(() => {
      timeoutController.abort("Request timeout");
    }, timeoutMs);
    const onAbort = () => timeoutController.abort("Request aborted");
    options?.signal?.addEventListener("abort", onAbort, { once: true });
    try {
      return await fetch(`${API_BASE}${path}`, {
        ...options,
        signal: timeoutController.signal,
        headers: {
          ...getAuthHeaders(),
          ...(shouldSetJsonContentType ? { "Content-Type": "application/json" } : {}),
          ...(options?.headers as Record<string, string> | undefined),
        },
        credentials: "include",
        cache: "no-store",
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new ApiError(408, "Request timeout");
      }
      throw err;
    } finally {
      globalThis.clearTimeout(timeoutId);
      options?.signal?.removeEventListener("abort", onAbort);
    }
  };

  let res = await run();
  if (res.status === 401 && retryOn401) {
    if (!refreshInFlight) {
      refreshInFlight = refreshAuthSession().finally(() => {
        refreshInFlight = null;
      });
    }
    const refreshed = await refreshInFlight;
    if (refreshed) {
      res = await run();
    }
  }

  if (!res.ok) {
    const body = await res.text();
    let message = body || `HTTP ${res.status}`;
    if (body) {
      try {
        const parsed = JSON.parse(body) as {
          detail?: string;
          error?: { message?: string };
        };
        message = parsed.error?.message || parsed.detail || message;
      } catch {
        message = body;
      }
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return undefined as T;
  }

  return res.json();
}

export function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const csrf = getCookie("csrf_token");
  if (csrf) headers["x-csrf-token"] = csrf;
  return headers;
}
