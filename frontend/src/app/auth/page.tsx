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
      setNotice("Your session expired or your access changed. Please sign in again.");
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
        <h1 className="mt-4 text-xl font-semibold">Sign In</h1>
        {notice && <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{notice}</p>}
        <p className="mt-2 text-sm text-slate-600">Authentication is handled through Keycloak.</p>
        <p className="mt-2 text-sm text-slate-600">
          Public demo access is available right now, and new account registrations require administrator approval.
        </p>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => void startLogin()}
            disabled={loading}
            className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-70"
          >
            {loading ? "Redirecting..." : "Sign In"}
          </button>
          <a
            href="/register"
            className="rounded border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            Register
          </a>
        </div>
        <div className="mt-3">
          <a
            href="/chat"
            className="inline-flex rounded border border-slate-300 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-100"
          >
            Open Demo Chat
          </a>
        </div>
      </div>
    </div>
  );
}
