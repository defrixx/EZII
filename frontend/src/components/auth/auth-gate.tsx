"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import { AuthSession, clearSession, loadSession, redirectToAuth, saveSession, showReloginNoticeOnce } from "@/lib/auth";

type Props = { children: React.ReactNode };

const PUBLIC_PATHS = ["/auth", "/auth/callback", "/register", "/logout"];
const AUTH_CHECK_FAILSAFE_MS = 12000;

export function AuthGate({ children }: Props) {
  const pathname = usePathname();
  const safePathname = pathname || (typeof window !== "undefined" ? window.location.pathname : "");
  const router = useRouter();
  const [ready, setReady] = useState(false);

  const isPublicPath = useMemo(
    () =>
      Boolean(safePathname)
      && PUBLIC_PATHS.some((p) => safePathname === p || safePathname.startsWith(`${p}/`)),
    [safePathname],
  );

  useEffect(() => {
    let mounted = true;
    const failSafeTimer = window.setTimeout(() => {
      if (!mounted) return;
      // Prevent indefinite loading when auth/network checks are stuck.
      setReady(true);
      if (!isPublicPath) {
        router.replace("/auth");
      }
    }, AUTH_CHECK_FAILSAFE_MS);

    async function run() {
      if (!safePathname) {
        if (mounted) setReady(true);
        return;
      }

      if (isPublicPath) {
        if (safePathname === "/auth") {
          try {
            const session = await api<AuthSession>("/auth/session", { retryOn401: false, timeoutMs: 8000 });
            saveSession(session);
            router.replace("/chat");
          } catch {
            // unauthenticated user stays on auth page
          }
        }
        if (mounted) setReady(true);
        return;
      }

      try {
        const session = await api<AuthSession>("/auth/session", { timeoutMs: 8000 });
        saveSession(session);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clearSession();
          // Allow chat page in guest read-only mode; other private routes still require auth.
          if (safePathname === "/chat" || safePathname.startsWith("/chat/")) {
            if (mounted) setReady(true);
            return;
          }
          if (mounted) setReady(true);
          showReloginNoticeOnce();
          redirectToAuth();
          return;
        }
        // Fallback for unexpected errors in auth check.
        router.replace("/auth");
        if (mounted) setReady(true);
        return;
      }

      const session = loadSession();

      if (safePathname === "/auth") {
        router.replace("/chat");
      }
      if (safePathname.startsWith("/admin") && session?.role !== "admin") {
        router.replace("/chat");
      }

      if (mounted) setReady(true);
    }

    run();
    return () => {
      mounted = false;
      window.clearTimeout(failSafeTimer);
    };
  }, [isPublicPath, router, safePathname]);

  if (!ready) {
    return <div className="p-8 text-sm text-slate-600">Checking authentication...</div>;
  }

  return <>{children}</>;
}
