"use client";

import { useEffect, useState } from "react";
import { buildLoginUrl, consumeReloginReason } from "@/lib/auth";
import { BrandTitle } from "@/components/brand-title";

export default function AuthPage() {
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const reason = consumeReloginReason();
    if (reason === "expired") {
      setNotice("Сессия истекла или недостаточно прав. Выполняем повторный вход.");
    }

    let mounted = true;
    async function run() {
      const url = await buildLoginUrl();
      if (mounted) {
        window.location.href = url;
      }
    }
    void run();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="p-8">
      <div className="fixed left-4 safe-top text-lg font-semibold text-slate-900">
        <BrandTitle />
      </div>
      <h1 className="text-xl font-semibold">Вход</h1>
      {notice && <p className="mt-2 text-sm text-amber-700">{notice}</p>}
      <p className="text-sm text-slate-600 mt-2">Перенаправление в Keycloak...</p>
    </div>
  );
}
