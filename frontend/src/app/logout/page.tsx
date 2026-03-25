"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BrandTitle } from "@/components/brand-title";

const REDIRECT_SECONDS = 5;

export default function LogoutPage() {
  const router = useRouter();
  const [secondsLeft, setSecondsLeft] = useState(REDIRECT_SECONDS);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);

    const redirect = window.setTimeout(() => {
      router.replace("/auth");
    }, REDIRECT_SECONDS * 1000);

    return () => {
      window.clearInterval(timer);
      window.clearTimeout(redirect);
    };
  }, [router]);

  return (
    <div className="min-h-screen grid place-items-center p-6">
      <div className="fixed left-4 safe-top text-lg font-semibold text-slate-900">
        <BrandTitle />
      </div>
      <div className="w-full max-w-md rounded-2xl border border-[var(--line)] bg-white p-6 shadow-sm">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Knowledge Assistant</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-900">You have signed out</h1>
        <p className="mt-2 text-sm text-slate-600">
          Your session has ended. Redirecting to the sign-in page in <span className="font-semibold">{secondsLeft}</span> seconds.
        </p>
        <button
          onClick={() => router.replace("/auth")}
          className="mt-5 w-full rounded bg-ink px-4 py-2 text-sm text-white"
        >
          Go to sign-in now
        </button>
      </div>
    </div>
  );
}
