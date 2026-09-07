"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePreferences } from "./app-preferences";
import { ErrorToast } from "./error-toast";
type Status = {
  knowledge_bases: number;
  sources: number;
  chats: number;
  pending_ingestion_jobs: number;
  pending_cleanup_tasks: number;
};
export function MaintenancePanel({embedded=false}:{embedded?:boolean}) {
  const { t, errorText } = usePreferences();
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(
    () =>
      api<Status>("/maintenance/status")
        .then(setStatus)
        .catch((error) => setError(errorText(error))),
    [errorText],
  );
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);
  async function retry() {
    if (!window.confirm(t.confirmCleanup)) return;
    try {
      await api("/maintenance/retry-cleanup?confirm=true", { method: "POST" });
      setNotice(t.saved);
      await load();
    } catch (error) {
      setError(errorText(error));
    }
  }
  if (!status) return <p role="status">{t.loading}</p>;
  return (
    <div className="stack maintenance-panel">
      {embedded?<h2>🛠️ {t.maintenance}</h2>:<h1>🛠️ {t.maintenance}</h1>}
      <p className="page-description">{t.maintenancePurpose}</p>
      {error && (
        <ErrorToast
          message={error}
          onClose={() => setError("")}
          onRetry={() => void load()}
          retryLabel={t.retry}
        />
      )}
      {notice && (
        <ErrorToast
          kind="success"
          message={notice}
          onClose={() => setNotice("")}
        />
      )}
      <section className="panel stack">
        <div className="stats">
          <p>
            <strong>{status.knowledge_bases}</strong>
            <span>{t.bases}</span>
          </p>
          <p>
            <strong>{status.sources}</strong>
            <span>{t.sources}</span>
          </p>
          <p>
            <strong>{status.chats}</strong>
            <span>{t.chats}</span>
          </p>
          <p>
            <strong>{status.pending_ingestion_jobs}</strong>
            <span>{t.pendingJobs}</span>
          </p>
          <p>
            <strong>{status.pending_cleanup_tasks}</strong>
            <span>{t.pendingCleanup}</span>
          </p>
        </div>
        <div className="maintenance-action">
          <div>
            <h2>{t.retryCleanup}</h2>
            <p className="muted">{t.cleanupHelp}</p>
          </div>
          {status.pending_cleanup_tasks ? (
            <button className="danger" onClick={() => void retry()}>
              {t.retryCleanup}
            </button>
          ) : (
            <span className="success">✓ {t.nothingToCleanup}</span>
          )}
        </div>
      </section>
    </div>
  );
}
