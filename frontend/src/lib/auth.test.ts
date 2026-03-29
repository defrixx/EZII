import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type SessionStore = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
};

function createSessionStorage(): SessionStore {
  const state = new Map<string, string>();
  return {
    getItem: (key: string) => state.get(key) ?? null,
    setItem: (key: string, value: string) => {
      state.set(key, value);
    },
    removeItem: (key: string) => {
      state.delete(key);
    },
  };
}

function installWindow() {
  const sessionStorage = createSessionStorage();
  const locationReplace = vi.fn();
  const location = {
    protocol: "https:",
    hostname: "app.example.com",
    origin: "https://app.example.com",
    replace: locationReplace,
  };
  const windowMock = {
    sessionStorage,
    location,
    setTimeout,
    clearTimeout,
  } as unknown as Window & typeof globalThis;

  Object.defineProperty(globalThis, "window", { value: windowMock, configurable: true });
  Object.defineProperty(globalThis, "document", {
    value: { cookie: "" },
    configurable: true,
  });

  return { sessionStorage, locationReplace };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("auth helpers", () => {
  beforeEach(() => {
    vi.resetModules();
    installWindow();
  });

  it("saves and clears session with oidc transient keys", async () => {
    const auth = await import("@/lib/auth");
    auth.saveSession({
      user_id: "u-1",
      tenant_id: "t-1",
      email: "user@test.dev",
      role: "admin",
    });
    window.sessionStorage.setItem("oidc_state", "state");
    window.sessionStorage.setItem("oidc_nonce", "nonce");
    window.sessionStorage.setItem("oidc_pkce_verifier", "verifier");
    window.sessionStorage.setItem("oidc_processed_code", "code");

    expect(auth.loadSession()).toMatchObject({ user_id: "u-1", role: "admin" });

    auth.clearSession();
    expect(auth.loadSession()).toBeNull();
    expect(window.sessionStorage.getItem("oidc_state")).toBeNull();
    expect(window.sessionStorage.getItem("oidc_nonce")).toBeNull();
    expect(window.sessionStorage.getItem("oidc_pkce_verifier")).toBeNull();
    expect(window.sessionStorage.getItem("oidc_processed_code")).toBeNull();
  });

  it("shows relogin notice once and consumes reason exactly once", async () => {
    const auth = await import("@/lib/auth");

    auth.showReloginNoticeOnce();
    auth.showReloginNoticeOnce();

    expect(auth.consumeReloginReason()).toBe("expired");
    expect(auth.consumeReloginReason()).toBeNull();
  });

  it("reads cookie value and uses csrf token in refresh/logout", async () => {
    const auth = await import("@/lib/auth");
    document.cookie = "csrf_token=csrf123; other=1";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 200 }))
      .mockResolvedValueOnce(new Response("", { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const ok = await auth.refreshAuthSession();
    await auth.backendLogout();

    expect(ok).toBe(true);
    expect(auth.getCookie("csrf_token")).toBe("csrf123");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/oidc/refresh",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": "csrf123" },
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/auth/logout",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": "csrf123" },
      }),
    );
  });

  it("retries code exchange on transient backend errors and clears oidc state on success", async () => {
    const auth = await import("@/lib/auth");
    window.sessionStorage.setItem("oidc_state", "state-1");
    window.sessionStorage.setItem("oidc_nonce", "nonce-1");
    window.sessionStorage.setItem("oidc_pkce_verifier", "verifier-1");
    vi.useFakeTimers();
    (window as unknown as { setTimeout: typeof setTimeout }).setTimeout = setTimeout;

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("temporary", { status: 503 }))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const pending = auth.exchangeCode("code-1", "state-1");
    await vi.advanceTimersByTimeAsync(500);
    await pending;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(window.sessionStorage.getItem("oidc_state")).toBeNull();
    expect(window.sessionStorage.getItem("oidc_nonce")).toBeNull();
    expect(window.sessionStorage.getItem("oidc_pkce_verifier")).toBeNull();
  });

  it("rejects exchange when oidc state is invalid", async () => {
    const auth = await import("@/lib/auth");
    window.sessionStorage.setItem("oidc_state", "state-1");
    window.sessionStorage.setItem("oidc_nonce", "nonce-1");
    window.sessionStorage.setItem("oidc_pkce_verifier", "verifier-1");

    await expect(auth.exchangeCode("code-1", "wrong-state")).rejects.toThrow("Invalid OIDC state");
  });
});
