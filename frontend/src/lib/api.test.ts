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
});
