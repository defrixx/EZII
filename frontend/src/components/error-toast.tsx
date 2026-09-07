"use client";

import { useEffect } from "react";

type Props = {
  message: string;
  onClose: () => void;
  onRetry?: () => void;
  retryLabel?: string;
  kind?: "error" | "success" | "warning";
};

export function ErrorToast({
  message,
  onClose,
  onRetry,
  retryLabel,
  kind = "error",
}: Props) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  useEffect(() => {
    if (kind === "error") return;
    const timer = setTimeout(onClose, 4000);
    return () => clearTimeout(timer);
  }, [kind, onClose]);
  return (
    <div
      className={`error-toast toast-${kind}`}
      role={kind === "error" ? "alert" : "status"}
      aria-live={kind === "error" ? "assertive" : "polite"}
    >
      <span className="error-toast-icon" aria-hidden="true">
        {kind === "success" ? "✓" : kind === "warning" ? "!" : "!"}
      </span>
      <span className="error-toast-message">{message}</span>
      {onRetry && <button onClick={onRetry}>{retryLabel}</button>}
      <button
        className="error-toast-close"
        onClick={onClose}
        aria-label="Закрыть / Close"
      >
        ×
      </button>
    </div>
  );
}
