export type AuthSession = {
  user_id: string;
  tenant_id: string;
  email: string;
  role: "admin" | "user";
};

const EXCHANGE_MAX_ATTEMPTS = 5;
const EXCHANGE_RETRY_DELAY_MS = 400;

const AUTH_KEY = "ezii_user_session";
const OIDC_STATE_KEY = "oidc_state";
const OIDC_NONCE_KEY = "oidc_nonce";
const OIDC_PKCE_VERIFIER_KEY = "oidc_pkce_verifier";
const OIDC_PROCESSED_CODE_KEY = "oidc_processed_code";
const AUTH_RELOGIN_NOTICE_KEY = "ezii_auth_relogin_notice_shown";
const AUTH_RELOGIN_REASON_KEY = "ezii_auth_relogin_reason";

export function getCookie(name: string): string | null {
  if (typeof window === "undefined") return null;
  const target = `${encodeURIComponent(name)}=`;
  const parts = document.cookie.split(";").map((x) => x.trim());
  for (const p of parts) {
    if (p.startsWith(target)) {
      return decodeURIComponent(p.slice(target.length));
    }
  }
  return null;
}

export function loadSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(AUTH_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthSession;
  } catch {
    return null;
  }
}

export function saveSession(session: AuthSession): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(AUTH_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(AUTH_KEY);
  window.sessionStorage.removeItem(OIDC_STATE_KEY);
  window.sessionStorage.removeItem(OIDC_NONCE_KEY);
  window.sessionStorage.removeItem(OIDC_PKCE_VERIFIER_KEY);
  window.sessionStorage.removeItem(OIDC_PROCESSED_CODE_KEY);
}

export function showReloginNoticeOnce(): void {
  if (typeof window === "undefined") return;
  const alreadyShown = window.sessionStorage.getItem(AUTH_RELOGIN_NOTICE_KEY) === "1";
  if (alreadyShown) return;
  window.sessionStorage.setItem(AUTH_RELOGIN_NOTICE_KEY, "1");
  window.sessionStorage.setItem(AUTH_RELOGIN_REASON_KEY, "expired");
}

export function consumeReloginReason(): "expired" | null {
  if (typeof window === "undefined") return null;
  const reason = window.sessionStorage.getItem(AUTH_RELOGIN_REASON_KEY);
  window.sessionStorage.removeItem(AUTH_RELOGIN_REASON_KEY);
  window.sessionStorage.removeItem(AUTH_RELOGIN_NOTICE_KEY);
  return reason === "expired" ? "expired" : null;
}

export function redirectToAuth(): void {
  if (typeof window === "undefined") return;
  window.location.replace("/auth");
}

function inferKeycloakBaseUrl(): string {
  if (typeof window === "undefined") return "http://localhost:8080";
  const { protocol, hostname } = window.location;
  const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
  if (localHosts.has(hostname)) {
    return "http://localhost:8080";
  }
  if (hostname.startsWith("auth.")) {
    return `${protocol}//${hostname}`;
  }
  return `${protocol}//auth.${hostname}`;
}

export function keycloakConfig() {
  const isBrowser = typeof window !== "undefined";
  const hostname = isBrowser ? window.location.hostname : "";
  const isLocalHost = hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
  const envBaseUrl = (process.env.NEXT_PUBLIC_KEYCLOAK_URL || "").trim();
  const safeBaseUrl = (!isLocalHost && envBaseUrl.includes("localhost")) ? "" : envBaseUrl;
  const baseUrl = (safeBaseUrl || inferKeycloakBaseUrl()).replace(/\/$/, "");
  const envRealm = (process.env.NEXT_PUBLIC_KEYCLOAK_REALM || "").trim();
  const realm = envRealm || "ezii";
  const envClientId = (process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID || "").trim();
  const clientId = envClientId || "ezii-frontend";
  const fallbackRedirect = isBrowser ? `${window.location.origin}/auth/callback` : "http://localhost/auth/callback";
  return {
    baseUrl,
    realm,
    clientId,
    redirectUri: process.env.NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI || fallbackRedirect,
  };
}

function randomUrlSafe(bytes = 32): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  let out = "";
  for (let i = 0; i < arr.length; i += 1) out += String.fromCharCode(arr[i]);
  return btoa(out).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256Base64Url(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(digest);
  let out = "";
  for (let i = 0; i < bytes.length; i += 1) out += String.fromCharCode(bytes[i]);
  return btoa(out).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export async function buildLoginUrl(): Promise<string> {
  const cfg = keycloakConfig();
  const state = randomUrlSafe();
  const nonce = randomUrlSafe();
  const codeVerifier = randomUrlSafe(64);
  const codeChallenge = await sha256Base64Url(codeVerifier);
  window.sessionStorage.setItem(OIDC_STATE_KEY, state);
  window.sessionStorage.setItem(OIDC_NONCE_KEY, nonce);
  window.sessionStorage.setItem(OIDC_PKCE_VERIFIER_KEY, codeVerifier);
  window.sessionStorage.removeItem(OIDC_PROCESSED_CODE_KEY);

  const url = new URL(`${cfg.baseUrl}/realms/${cfg.realm}/protocol/openid-connect/auth`);
  url.searchParams.set("client_id", cfg.clientId);
  url.searchParams.set("redirect_uri", cfg.redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid profile email");
  url.searchParams.set("state", state);
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

export async function exchangeCode(code: string, state: string | null): Promise<void> {
  const expectedState = window.sessionStorage.getItem(OIDC_STATE_KEY);
  const codeVerifier = window.sessionStorage.getItem(OIDC_PKCE_VERIFIER_KEY);
  const nonce = window.sessionStorage.getItem(OIDC_NONCE_KEY);
  if (!expectedState || !state || expectedState !== state || !codeVerifier) {
    throw new Error("Невалидный OIDC state");
  }
  if (!nonce) {
    throw new Error("Отсутствует OIDC nonce");
  }

  const payload = JSON.stringify({
    code,
    code_verifier: codeVerifier,
    nonce,
    redirect_uri: keycloakConfig().redirectUri,
  });

  let lastResponse: Response | null = null;
  let lastError: unknown = null;

  for (let attempt = 1; attempt <= EXCHANGE_MAX_ATTEMPTS; attempt += 1) {
    try {
      const res = await fetch("/api/v1/auth/oidc/exchange", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: payload,
      });
      if (res.ok) {
        window.sessionStorage.removeItem(OIDC_STATE_KEY);
        window.sessionStorage.removeItem(OIDC_PKCE_VERIFIER_KEY);
        window.sessionStorage.removeItem(OIDC_NONCE_KEY);
        return;
      }

      lastResponse = res;
      const shouldRetry = res.status === 502 || res.status === 503 || res.status === 504;
      if (!shouldRetry || attempt === EXCHANGE_MAX_ATTEMPTS) {
        break;
      }
    } catch (error) {
      lastError = error;
      if (attempt === EXCHANGE_MAX_ATTEMPTS) {
        break;
      }
    }

    await new Promise((resolve) => window.setTimeout(resolve, EXCHANGE_RETRY_DELAY_MS * attempt));
  }

  if (lastResponse) {
    let detail = "";
    try {
      const data = await lastResponse.json();
      detail = typeof data?.detail === "string" ? data.detail : "";
    } catch {
      detail = "";
    }
    if (detail) {
      throw new Error(`Не удалось обменять код авторизации: ${detail}`);
    }
    throw new Error("Не удалось обменять код авторизации");
  }
  if (lastError) {
    throw new Error("Не удалось обменять код авторизации: временная ошибка сети");
  }
  throw new Error("Не удалось обменять код авторизации");
}

export async function refreshAuthSession(): Promise<boolean> {
  const csrf = getCookie("csrf_token");
  const res = await fetch("/api/v1/auth/oidc/refresh", {
    method: "POST",
    headers: csrf ? { "x-csrf-token": csrf } : undefined,
    credentials: "include",
  });
  return res.ok;
}

export async function backendLogout(): Promise<void> {
  const csrf = getCookie("csrf_token");
  await fetch("/api/v1/auth/logout", {
    method: "POST",
    headers: csrf ? { "x-csrf-token": csrf } : undefined,
    credentials: "include",
  });
}
