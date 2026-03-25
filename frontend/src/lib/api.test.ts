import { afterEach, describe, expect, it, vi } from "vitest";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

async function loadApiWithAuthMocks(refreshImpl: () => Promise<boolean>) {
  vi.resetModules();
  const getCookie = vi.fn(() => "csrf");
  const refreshAuthSession = vi.fn(refreshImpl);
  vi.doMock("@/lib/auth", () => ({ getCookie, refreshAuthSession }));
  const mod = await import("@/lib/api");
  return { api: mod.api, refreshAuthSession };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("api refresh mutex", () => {
  it("deduplicates concurrent refresh calls on parallel 401 responses", async () => {
    const gate = deferred<boolean>();
    const { api, refreshAuthSession } = await loadApiWithAuthMocks(() => gate.promise);

    const hits: Record<string, number> = {};
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      hits[url] = (hits[url] || 0) + 1;
      const count = hits[url];
      if (count === 1) {
        return new Response("unauthorized", { status: 401 });
      }
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const p1 = api<{ ok: boolean }>("/auth/session");
    const p2 = api<{ ok: boolean }>("/chats");

    await vi.waitFor(() => {
      expect(refreshAuthSession).toHaveBeenCalledTimes(1);
    });

    gate.resolve(true);
    const out = await Promise.all([p1, p2]);

    expect(out).toEqual([{ ok: true }, { ok: true }]);
    expect(refreshAuthSession).toHaveBeenCalledTimes(1);
  });

  it("extracts normalized detail from JSON error envelopes", async () => {
    const { api } = await loadApiWithAuthMocks(async () => false);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            detail: "Readable error",
            error: { message: "Readable error" },
          }),
          {
            status: 400,
            headers: { "content-type": "application/json" },
          },
        ),
      ),
    );

    await expect(api("/admin/provider", { retryOn401: false })).rejects.toMatchObject({
      status: 400,
      message: "Readable error",
    });
  });

  it("does not force JSON content-type for multipart form uploads", async () => {
    const { api } = await loadApiWithAuthMocks(async () => false);
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect(headers.has("content-type")).toBe(false);
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    form.append("file", new Blob(["abc"], { type: "text/plain" }), "sample.txt");

    const out = await api<{ ok: boolean }>("/admin/documents/upload", {
      method: "POST",
      body: form,
      retryOn401: false,
    });
    expect(out).toEqual({ ok: true });
  });

  it("fails with timeout ApiError when request hangs", async () => {
    vi.useFakeTimers();
    const { api } = await loadApiWithAuthMocks(async () => false);
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      const signal = init?.signal;
      if (!signal) return;
      signal.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);

    const pending = api("/auth/session", { retryOn401: false, timeoutMs: 10 });
    const assertion = expect(pending).rejects.toMatchObject({
      status: 408,
      message: "Request timeout",
    });
    await vi.advanceTimersByTimeAsync(11);
    await assertion;
  });
});
