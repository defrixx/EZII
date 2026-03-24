"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { exchangeCode, saveSession } from "@/lib/auth";
import { api } from "@/lib/api";
import { BrandTitle } from "@/components/brand-title";

const PROCESSED_CODE_KEY = "oidc_processed_code";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    async function run() {
      const params = new URLSearchParams(window.location.search);
      const code = params.get("code");
      const state = params.get("state");
      const oidcError = params.get("error");
      const oidcErrorDesc = params.get("error_description");

      if (oidcError) {
        setError(oidcErrorDesc || oidcError);
        window.setTimeout(() => router.replace("/auth"), 1500);
        return;
      }
      if (!code) {
        setError("Отсутствует код авторизации");
        window.setTimeout(() => router.replace("/auth"), 1500);
        return;
      }

      const alreadyProcessed = window.sessionStorage.getItem(PROCESSED_CODE_KEY);
      if (alreadyProcessed === code) {
        router.replace("/chat");
        return;
      }

      try {
        await exchangeCode(code, state);
        // Ensure auth cookies are actually accepted before leaving callback page.
        const session = await api<{ user_id: string; tenant_id: string; email: string; role: "admin" | "user" }>(
          "/auth/session",
          { retryOn401: false },
        );
        saveSession(session);
        window.sessionStorage.setItem(PROCESSED_CODE_KEY, code);
        window.history.replaceState(null, "", "/auth/callback");
        router.replace("/chat");
      } catch (e: any) {
        setError(e.message || "Не удалось завершить вход");
        window.setTimeout(() => router.replace("/auth"), 1500);
      }
    }
    void run();
  }, [router]);

  return (
    <div className="p-8">
      <div className="fixed left-4 safe-top text-lg font-semibold text-slate-900">
        <BrandTitle />
      </div>
      <h1 className="text-xl font-semibold">Авторизация</h1>
      {error ? <p className="text-sm text-red-600 mt-2">{error}</p> : <p className="text-sm mt-2">Завершение входа...</p>}
    </div>
  );
}
