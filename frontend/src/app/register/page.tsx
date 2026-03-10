"use client";

import { FormEvent, useState } from "react";
import Script from "next/script";
import { buildLoginUrl } from "@/lib/auth";
import { BrandTitle } from "@/components/brand-title";

type RegisterResponse = { detail?: string };

export default function RegisterPage() {
  const captchaRequired = (process.env.NEXT_PUBLIC_REGISTER_ENFORCE_CAPTCHA || "").trim().toLowerCase() === "true";
  const captchaProvider = (process.env.NEXT_PUBLIC_REGISTER_CAPTCHA_PROVIDER || "").trim().toLowerCase();
  const turnstileSiteKey = process.env.NEXT_PUBLIC_REGISTER_TURNSTILE_SITE_KEY || "";
  const hcaptchaSiteKey = process.env.NEXT_PUBLIC_REGISTER_HCAPTCHA_SITE_KEY || "";
  const captchaScriptSrc =
    captchaProvider === "turnstile"
      ? "https://challenges.cloudflare.com/turnstile/v0/api.js"
      : captchaProvider === "hcaptcha"
        ? "https://js.hcaptcha.com/1/api.js"
        : "";
  const captchaConfigured =
    (captchaProvider === "turnstile" && turnstileSiteKey.length > 0) ||
    (captchaProvider === "hcaptcha" && hcaptchaSiteKey.length > 0);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      let captchaToken = "";
      if (captchaRequired) {
        if (!captchaConfigured) {
          throw new Error("CAPTCHA не настроена");
        }
        if (captchaProvider === "turnstile") {
          const input = document.querySelector<HTMLInputElement>('input[name="cf-turnstile-response"]');
          captchaToken = input?.value?.trim() || "";
        } else if (captchaProvider === "hcaptcha") {
          const input = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(
            '[name="h-captcha-response"]',
          );
          captchaToken = input?.value?.trim() || "";
        }
        if (!captchaToken) {
          throw new Error("Пройдите CAPTCHA");
        }
      }

      const res = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password, captcha_token: captchaToken || undefined }),
      });

      if (!res.ok) {
        const text = await res.text();
        let detail = "Регистрация не удалась";
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          detail = parsed.detail || detail;
        } catch {
          if (text) {
            detail = text;
          }
        }
        throw new Error(detail);
      }

      const data = (await res.json()) as RegisterResponse;
      setSuccess(data.detail || "Регистрация завершена");
      setPassword("");
    } catch (e: any) {
      setError(e?.message || "Регистрация не удалась");
    } finally {
      setLoading(false);
    }
  }

  async function gotoLogin() {
    const url = await buildLoginUrl();
    window.location.href = url;
  }

  return (
    <div className="min-h-screen bg-slate-50 p-8">
      {captchaRequired && captchaConfigured && captchaScriptSrc && (
        <Script src={captchaScriptSrc} strategy="afterInteractive" />
      )}
      <div className="mx-auto w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="text-lg font-semibold text-slate-900">
          <BrandTitle />
        </div>
        <h1 className="mt-4 text-xl font-semibold">Регистрация</h1>
        <p className="mt-2 text-sm text-slate-600">После регистрации войдите через Keycloak и начните чат.</p>

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
              pattern="^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$"
              title="Введите корректный email, например user@example.com"
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

          {captchaRequired && captchaConfigured && captchaProvider === "turnstile" && (
            <div className="cf-turnstile" data-sitekey={turnstileSiteKey} data-theme="light" />
          )}
          {captchaRequired && captchaConfigured && captchaProvider === "hcaptcha" && (
            <div className="h-captcha" data-sitekey={hcaptchaSiteKey} data-theme="light" />
          )}
          {captchaRequired && !captchaConfigured && (
            <p className="text-sm text-amber-700">
              CAPTCHA не отображается: проверьте `NEXT_PUBLIC_REGISTER_CAPTCHA_PROVIDER` и site key для выбранного
              провайдера.
            </p>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}
          {success && <p className="text-sm text-emerald-700">{success}</p>}

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={loading}
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
