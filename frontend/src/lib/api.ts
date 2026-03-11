import { getCookie, refreshAuthSession } from "@/lib/auth";

// Use same-origin API by default to work behind reverse proxy (nginx) in Docker.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
let refreshInFlight: Promise<boolean> | null = null;

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const run = async (): Promise<Response> =>
    fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
        ...(options?.headers as Record<string, string> | undefined),
      },
      credentials: "include",
      cache: "no-store",
    });

  let res = await run();
  if (res.status === 401) {
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
    throw new ApiError(res.status, body || `HTTP ${res.status}`);
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
