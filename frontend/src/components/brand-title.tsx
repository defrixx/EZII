"use client";

type Props = {
  className?: string;
};

export function BrandTitle({ className }: Props) {
  return (
    <span
      className={`relative inline-flex items-center group ${className || ""}`}
      tabIndex={0}
      aria-label="Knowledge Assistant"
    >
      Knowledge Assistant
      <span
        className="pointer-events-none absolute left-0 top-full z-50 mt-1 hidden whitespace-nowrap rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-900 shadow-lg group-hover:block group-focus-within:block"
        style={{ color: "#0f172a", backgroundColor: "#ffffff" }}
      >
        Экспертная база знаний
      </span>
    </span>
  );
}
