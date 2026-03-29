"use client";

import Script from "next/script";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { buildLoginUrl } from "@/lib/auth";
import { useToast } from "@/components/ui/toast-provider";

type RegisterResponse = { detail?: string };
type CaptchaChallenge = { captcha_id: string; prompt: string };
type RegisterConfigResponse = {
  captcha_required: boolean;
  captcha_provider: string;
  builtin_captcha: boolean;
  captcha_site_key?: string | null;
};

const BUILTIN_CAPTCHA_PROVIDERS = new Set(["builtin", "selfhosted", "self-hosted", "local"]);
const HCAPTCHA_PROVIDERS = new Set(["hcaptcha", "h-captcha"]);
const TURNSTILE_PROVIDERS = new Set(["turnstile", "cloudflare"]);

function normalizeCaptchaProvider(raw: string): "builtin" | "hcaptcha" | "turnstile" | "unsupported" {
  const provider = (raw || "").trim().toLowerCase();
  if (BUILTIN_CAPTCHA_PROVIDERS.has(provider)) return "builtin";
  if (HCAPTCHA_PROVIDERS.has(provider) || !provider) return "hcaptcha";
  if (TURNSTILE_PROVIDERS.has(provider)) return "turnstile";
  return "unsupported";
}

declare global {
  interface Window {
    hcaptcha?: {
      render: (container: HTMLElement | string, options: Record<string, unknown>) => string;
      remove: (widgetId: string) => void;
      reset: (widgetId?: string) => void;
    };
    turnstile?: {
      render: (container: HTMLElement | string, options: Record<string, unknown>) => string;
      remove: (widgetId: string) => void;
      reset: (widgetId?: string) => void;
    };
  }
}

export default function RegisterPage() {
  const envCaptchaRequired = (process.env.NEXT_PUBLIC_REGISTER_ENFORCE_CAPTCHA || "").trim().toLowerCase() === "true";
  const envCaptchaProvider = normalizeCaptchaProvider(process.env.NEXT_PUBLIC_REGISTER_CAPTCHA_PROVIDER || "hcaptcha");
  const envHcaptchaSiteKey = (process.env.NEXT_PUBLIC_REGISTER_HCAPTCHA_SITE_KEY || "").trim();
  const envBuiltinCaptcha = envCaptchaProvider === "builtin";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [captchaId, setCaptchaId] = useState("");
  const [captchaPrompt, setCaptchaPrompt] = useState("");
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [captchaLoading, setCaptchaLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [captchaRequired, setCaptchaRequired] = useState(envCaptchaRequired);
  const [builtinCaptcha, setBuiltinCaptcha] = useState(envBuiltinCaptcha);
  const [captchaProvider, setCaptchaProvider] = useState<string>(envCaptchaProvider);
  const [runtimeCaptchaSiteKey, setRuntimeCaptchaSiteKey] = useState("");
  const [hcaptchaScriptReady, setHcaptchaScriptReady] = useState(false);
  const [turnstileScriptReady, setTurnstileScriptReady] = useState(false);
  const [externalCaptchaError, setExternalCaptchaError] = useState<string | null>(null);
  const externalCaptchaContainerRef = useRef<HTMLDivElement | null>(null);
  const externalCaptchaWidgetIdRef = useRef<string | null>(null);
  const { pushToast } = useToast();

  function getErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof Error && error.message) {
      return error.message;
    }
    return fallback;
  }

  useEffect(() => {
    let mounted = true;
    async function loadRegisterConfig() {
      try {
        const res = await fetch("/api/v1/auth/register/config", {
          method: "GET",
          credentials: "include",
        });
        if (!res.ok) return;
        const data = (await res.json()) as RegisterConfigResponse;
        if (!mounted) return;
        setCaptchaRequired(Boolean(data.captcha_required));
        const provider = normalizeCaptchaProvider(data.captcha_provider || "");
        setCaptchaProvider(provider || "builtin");
        setBuiltinCaptcha(Boolean(data.builtin_captcha || provider === "builtin"));
        setRuntimeCaptchaSiteKey((data.captcha_site_key || "").trim());
        setError(null);
      } catch {
        // Keep env-based defaults if runtime config endpoint is unavailable.
      }
    }
    void loadRegisterConfig();
    return () => {
      mounted = false;
    };
  }, []);

  const effectiveHcaptchaSiteKey = (captchaProvider === "hcaptcha" ? runtimeCaptchaSiteKey : "") || envHcaptchaSiteKey;
  const effectiveTurnstileSiteKey = captchaProvider === "turnstile" ? runtimeCaptchaSiteKey : "";

  const loadCaptcha = useCallback(async () => {
    setCaptchaLoading(true);
    try {
      const res = await fetch("/api/v1/auth/register/captcha", {
        method: "GET",
        credentials: "include",
      });
      if (!res.ok) {
        throw new Error("Failed to load CAPTCHA");
      }
      const data = (await res.json()) as CaptchaChallenge;
      setCaptchaId(data.captcha_id);
      setCaptchaPrompt(data.prompt);
      setCaptchaAnswer("");
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to load CAPTCHA"));
    } finally {
      setCaptchaLoading(false);
    }
  }, []);

  useEffect(() => {
    if (captchaRequired && builtinCaptcha) {
      void loadCaptcha();
    }
  }, [builtinCaptcha, captchaRequired, loadCaptcha]);

  useEffect(() => {
    if (!builtinCaptcha) {
      setError((current) => (current === "Failed to load CAPTCHA" ? null : current));
    }
  }, [builtinCaptcha]);

  useEffect(() => {
    if (!error) return;
    pushToast({ tone: "error", title: "Registration error", description: error });
  }, [error, pushToast]);

  useEffect(() => {
    if (!success) return;
    pushToast({ tone: "success", title: "Registration submitted", description: success });
  }, [pushToast, success]);

  useEffect(() => {
    if (!(captchaRequired && !builtinCaptcha)) {
      return;
    }

    setExternalCaptchaError(null);
    const siteKey =
      captchaProvider === "hcaptcha"
        ? effectiveHcaptchaSiteKey
        : captchaProvider === "turnstile"
          ? effectiveTurnstileSiteKey
          : "";
    if (!siteKey) {
      setExternalCaptchaError("CAPTCHA is temporarily unavailable");
      return;
    }

    const container = externalCaptchaContainerRef.current;
    if (!container) return;

    if (captchaProvider === "hcaptcha") {
      if (!hcaptchaScriptReady || !window.hcaptcha) return;
      if (externalCaptchaWidgetIdRef.current) return;
      const id = window.hcaptcha.render(container, {
        sitekey: siteKey,
        callback: (token: string) => {
          setCaptchaToken(token);
          setExternalCaptchaError(null);
        },
        "expired-callback": () => {
          setCaptchaToken("");
          setExternalCaptchaError(null);
        },
        "error-callback": () => {
          setCaptchaToken("");
          setExternalCaptchaError("hCaptcha is unavailable, try reloading the page");
        },
      });
      externalCaptchaWidgetIdRef.current = id;
      return;
    }

    if (captchaProvider === "turnstile") {
      if (!turnstileScriptReady || !window.turnstile) return;
      if (externalCaptchaWidgetIdRef.current) return;
      const id = window.turnstile.render(container, {
        sitekey: siteKey,
        callback: (token: string) => {
          setCaptchaToken(token);
          setExternalCaptchaError(null);
        },
        "expired-callback": () => {
          setCaptchaToken("");
          setExternalCaptchaError(null);
        },
        "error-callback": () => {
          setCaptchaToken("");
          setExternalCaptchaError("Turnstile is unavailable, try reloading the page");
        },
      });
      externalCaptchaWidgetIdRef.current = id;
      return;
    }

    setExternalCaptchaError("CAPTCHA is temporarily unavailable");
  }, [
    builtinCaptcha,
    captchaProvider,
    captchaRequired,
    envHcaptchaSiteKey,
    effectiveHcaptchaSiteKey,
    effectiveTurnstileSiteKey,
    hcaptchaScriptReady,
    turnstileScriptReady,
  ]);

  useEffect(() => {
    return () => {
      const widgetId = externalCaptchaWidgetIdRef.current;
      if (!widgetId) return;
      try {
        if (captchaProvider === "hcaptcha" && window.hcaptcha) {
          window.hcaptcha.remove(widgetId);
        }
        if (captchaProvider === "turnstile" && window.turnstile) {
          window.turnstile.remove(widgetId);
        }
      } catch {
        // Best effort cleanup on unmount.
      }
      externalCaptchaWidgetIdRef.current = null;
    };
  }, [captchaProvider]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      if (captchaRequired && builtinCaptcha) {
        if (!captchaId || !captchaAnswer.trim()) {
          throw new Error("Solve the CAPTCHA");
        }
      }
      if (captchaRequired && !builtinCaptcha && !captchaToken.trim()) {
        throw new Error("Complete the CAPTCHA challenge");
      }
      const payload: Record<string, unknown> = {
        email: email.trim(),
        password,
      };
      if (captchaRequired && builtinCaptcha) {
        payload.captcha_id = captchaId;
        payload.captcha_answer = captchaAnswer.trim();
      } else if (captchaRequired) {
        payload.captcha_token = captchaToken.trim();
      }

      const res = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const text = await res.text();
        let detail = "Registration failed";
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          detail = parsed.detail || detail;
        } catch {
          if (text) detail = text;
        }
        throw new Error(detail);
      }

      const data = (await res.json()) as RegisterResponse;
      setSuccess(data.detail || "Registration completed");
      setPassword("");
      setCaptchaAnswer("");
      setCaptchaToken("");
      setExternalCaptchaError(null);
      if (captchaRequired && builtinCaptcha) {
        await loadCaptcha();
      } else if (captchaRequired && !builtinCaptcha) {
        const widgetId = externalCaptchaWidgetIdRef.current || undefined;
        if (captchaProvider === "hcaptcha" && window.hcaptcha) {
          window.hcaptcha.reset(widgetId);
        }
        if (captchaProvider === "turnstile" && window.turnstile) {
          window.turnstile.reset(widgetId);
        }
      }
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Registration failed"));
      if (captchaRequired && builtinCaptcha) {
        await loadCaptcha();
      } else if (captchaRequired && !builtinCaptcha) {
        const widgetId = externalCaptchaWidgetIdRef.current || undefined;
        if (captchaProvider === "hcaptcha" && window.hcaptcha) {
          window.hcaptcha.reset(widgetId);
        }
        if (captchaProvider === "turnstile" && window.turnstile) {
          window.turnstile.reset(widgetId);
        }
      }
    } finally {
      setLoading(false);
    }
  }

  async function gotoLogin() {
    const url = await buildLoginUrl();
    window.location.href = url;
  }

  return (
    <div className="safe-x safe-top safe-bottom min-h-screen p-8">
      {captchaRequired && !builtinCaptcha && captchaProvider === "hcaptcha" && effectiveHcaptchaSiteKey && (
        <Script
          src="https://js.hcaptcha.com/1/api.js?render=explicit"
          strategy="afterInteractive"
          onLoad={() => {
            setHcaptchaScriptReady(true);
            setExternalCaptchaError(null);
          }}
          onError={() => setExternalCaptchaError("Failed to load hCaptcha script")}
        />
      )}
      {captchaRequired && !builtinCaptcha && captchaProvider === "turnstile" && effectiveTurnstileSiteKey && (
        <Script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
          strategy="afterInteractive"
          onLoad={() => {
            setTurnstileScriptReady(true);
            setExternalCaptchaError(null);
          }}
          onError={() => setExternalCaptchaError("Failed to load Turnstile script")}
        />
      )}
      <div className="mx-auto w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold">Register</h1>
        <p className="mt-2 text-sm text-slate-600">Create an account using email and password, then sign in.</p>

        <form className="mt-4 space-y-3" onSubmit={onSubmit}>
          <label className="block text-sm text-slate-700">
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-base mt-1"
              placeholder="you@example.com"
            />
          </label>

          <label className="block text-sm text-slate-700">
            Password
            <input
              type="password"
              required
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-base mt-1"
              placeholder="Minimum 12 characters"
            />
          </label>

          <p className="text-xs text-slate-500">
            Requirements: 12+ characters, uppercase and lowercase letters, a digit, and a special character.
          </p>

          {captchaRequired && builtinCaptcha && (
            <div className="rounded border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-800">
                  {captchaLoading ? "Loading CAPTCHA..." : captchaPrompt || "CAPTCHA unavailable"}
                </p>
                <button
                  type="button"
                  onClick={() => void loadCaptcha()}
                  className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
                >
                  Refresh
                </button>
              </div>
              <input
                type="text"
                value={captchaAnswer}
                onChange={(e) => setCaptchaAnswer(e.target.value)}
                className="input-base mt-2"
                placeholder="Answer"
                required
              />
            </div>
          )}

          {captchaRequired && !builtinCaptcha && (
            <div className="rounded border border-slate-200 bg-slate-50 p-3">
              <div ref={externalCaptchaContainerRef} className="mt-2 min-h-16" />
              {externalCaptchaError && <p className="mt-2 text-xs text-red-600">{externalCaptchaError}</p>}
              {!externalCaptchaError && !captchaToken && (
                <p className="mt-2 text-xs text-slate-600">Complete the CAPTCHA challenge before registering</p>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={loading || (captchaRequired && builtinCaptcha && captchaLoading)}
              className="btn btn-primary disabled:opacity-70"
            >
              {loading ? "Creating..." : "Create account"}
            </button>
            <button
              type="button"
              onClick={() => void gotoLogin()}
              className="btn btn-secondary"
            >
              Back to sign-in
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
