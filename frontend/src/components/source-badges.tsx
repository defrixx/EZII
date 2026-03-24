type Props = { sources: string[] };

export function SourceBadges({ sources }: Props) {
  const labels: Record<string, string> = {
    glossary: "глоссарий",
    document: "документ",
    website: "сайт",
    web: "веб",
    synthesis: "синтез",
    model: "модель",
    demo: "демо",
  };

  return (
    <div className="flex gap-2 mt-2 flex-wrap">
      {sources.map((s) => (
        <span
          key={s}
          className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200"
        >
          {labels[s] || s}
        </span>
      ))}
    </div>
  );
}
