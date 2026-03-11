"use client";

import { FormEvent, useEffect, useState } from "react";
import { buildLoginUrl } from "@/lib/auth";

type RegisterResponse = { detail?: string };
type CaptchaChallenge = { captcha_id: string; prompt: string };
type RegisterConfigResponse = {
  captcha_required: boolean;
  captcha_provider: string;
  builtin_captcha: boolean;
};

const BUILTIN_CAPTCHA_PROVIDERS = new Set(["builtin", "selfhosted", "self-hosted", "local"]);

export default function RegisterPage() {
  const envCaptchaRequired = (process.env.NEXT_PUBLIC_REGISTER_ENFORCE_CAPTCHA || "").trim().toLowerCase() === "true";
  const envCaptchaProvider = (process.env.NEXT_PUBLIC_REGISTER_CAPTCHA_PROVIDER || "builtin").trim().toLowerCase();
  const envTurnstileSiteKey = (process.env.NEXT_PUBLIC_REGISTER_TURNSTILE_SITE_KEY || "").trim();
  const envHcaptchaSiteKey = (process.env.NEXT_PUBLIC_REGISTER_HCAPTCHA_SITE_KEY || "").trim();
  const envBuiltinCaptcha = BUILTIN_CAPTCHA_PROVIDERS.has(envCaptchaProvider);

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
  const [builtinCaptcha, setBuiltinCaptcha] = useState(envBuiltinCaptcha || envCaptchaRequired);
  const [captchaProvider, setCaptchaProvider] = useState(envCaptchaProvider);

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
        const provider = (data.captcha_provider || "").trim().toLowerCase();
        setCaptchaProvider(provider || "builtin");
        setBuiltinCaptcha(Boolean(data.builtin_captcha || BUILTIN_CAPTCHA_PROVIDERS.has(provider)));
      } catch {
        // Keep env-based defaults if runtime config endpoint is unavailable.
      }
    }
    void loadRegisterConfig();
    return () => {
      mounted = false;
    };
  }, []);

  async function loadCaptcha() {
    setCaptchaLoading(true);
    try {
      const res = await fetch("/api/v1/auth/register/captcha", {
        method: "GET",
        credentials: "include",
      });
      if (!res.ok) {
        throw new Error("Не удалось загрузить CAPTCHA");
      }
      const data = (await res.json()) as CaptchaChallenge;
      setCaptchaId(data.captcha_id);
      setCaptchaPrompt(data.prompt);
      setCaptchaAnswer("");
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить CAPTCHA");
    } finally {
      setCaptchaLoading(false);
    }
  }

  useEffect(() => {
    if (captchaRequired && builtinCaptcha) {
      void loadCaptcha();
    }
  }, [captchaRequired, builtinCaptcha]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      if (captchaRequired && builtinCaptcha) {
        if (!captchaId || !captchaAnswer.trim()) {
          throw new Error("Решите CAPTCHA");
        }
      }
      if (captchaRequired && !builtinCaptcha && !captchaToken.trim()) {
        throw new Error("Введите captcha_token от внешнего провайдера");
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
        let detail = "Регистрация не удалась";
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          detail = parsed.detail || detail;
        } catch {
          if (text) detail = text;
        }
        throw new Error(detail);
      }

      const data = (await res.json()) as RegisterResponse;
      setSuccess(data.detail || "Регистрация завершена");
      setPassword("");
      setCaptchaAnswer("");
      setCaptchaToken("");
      if (captchaRequired && builtinCaptcha) {
        await loadCaptcha();
      }
    } catch (e: any) {
      setError(e?.message || "Регистрация не удалась");
      if (captchaRequired && builtinCaptcha) {
        await loadCaptcha();
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
    <div className="min-h-screen p-8">
      <div className="mx-auto w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold">Регистрация</h1>
        <p className="mt-2 text-sm text-slate-600">Создайте аккаунт (логин/email + пароль), затем выполните вход.</p>

        <form className="mt-4 space-y-3" onSubmit={onSubmit}>
          <label className="block text-sm text-slate-700">
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              placeholder="you@example.com"
            />
          </label>

          <label className="block text-sm text-slate-700">
            Пароль
            <input
              type="password"
              required
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              placeholder="Минимум 12 символов"
            />
          </label>

          <p className="text-xs text-slate-500">
            Требования: 12+ символов, заглавные/строчные буквы, цифра и спецсимвол.
          </p>

          {captchaRequired && builtinCaptcha && (
            <div className="rounded border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-800">
                  {captchaLoading ? "Загрузка CAPTCHA..." : captchaPrompt || "CAPTCHA недоступна"}
                </p>
                <button
                  type="button"
                  onClick={() => void loadCaptcha()}
                  className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
                >
                  Обновить
                </button>
              </div>
              <input
                type="text"
                value={captchaAnswer}
                onChange={(e) => setCaptchaAnswer(e.target.value)}
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2"
                placeholder="Ответ"
                required
              />
            </div>
          )}

          {captchaRequired && !builtinCaptcha && (
            <div className="rounded border border-slate-200 bg-slate-50 p-3">
              <p className="text-sm font-medium text-slate-800">
                Внешняя CAPTCHA: введите `captcha_token` ({captchaProvider})
              </p>
              {captchaProvider === "turnstile" && envTurnstileSiteKey && (
                <p className="mt-1 text-xs text-slate-600">Turnstile site key: {envTurnstileSiteKey}</p>
              )}
              {captchaProvider === "hcaptcha" && envHcaptchaSiteKey && (
                <p className="mt-1 text-xs text-slate-600">hCaptcha site key: {envHcaptchaSiteKey}</p>
              )}
              <input
                type="text"
                value={captchaToken}
                onChange={(e) => setCaptchaToken(e.target.value)}
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2"
                placeholder="captcha token"
                required
              />
            </div>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}
          {success && <p className="text-sm text-emerald-700">{success}</p>}

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={loading || (captchaRequired && builtinCaptcha && captchaLoading)}
              className="rounded bg-amber-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-amber-600 disabled:opacity-70"
            >
              {loading ? "Создаем..." : "Создать аккаунт"}
            </button>
            <button
              type="button"
              onClick={() => void gotoLogin()}
              className="rounded border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              К входу
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
