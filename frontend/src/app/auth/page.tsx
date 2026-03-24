"use client";

import { useEffect, useState } from "react";
import { buildLoginUrl, consumeReloginReason } from "@/lib/auth";
import { BrandTitle } from "@/components/brand-title";

export default function AuthPage() {
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const reason = consumeReloginReason();
    if (reason === "expired") {
      setNotice("Сессия истекла или недостаточно прав. Выполняем повторный вход.");
    }
  }, []);

  async function startLogin() {
    setLoading(true);
    try {
      const url = await buildLoginUrl();
      window.location.href = url;
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="text-lg font-semibold text-slate-900">
          <BrandTitle />
        </div>
        <h1 className="mt-4 text-xl font-semibold">Вход</h1>
        {notice && <p className="mt-2 text-sm text-amber-700">{notice}</p>}
        <p className="text-sm text-slate-600 mt-2">Авторизация через Keycloak.</p>
        <p className="mt-2 text-sm text-slate-600">
          Сейчас открыт паблик демо-доступ, а регистрация новых аккаунтов проходит через аппрув администрации.
        </p>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => void startLogin()}
            disabled={loading}
            className="rounded bg-amber-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-amber-600 disabled:opacity-70"
          >
            {loading ? "Переход..." : "Войти"}
          </button>
          <a
            href="/register"
            className="rounded border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            Регистрация
          </a>
        </div>
        <div className="mt-3">
          <a
            href="/chat"
            className="inline-flex rounded border border-sky-300 bg-sky-50 px-4 py-2 text-sm font-medium text-sky-800 hover:bg-sky-100"
          >
            Посмотреть демо-чат
          </a>
        </div>
      </div>
    </div>
  );
}
