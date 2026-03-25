type Props = { sources: string[] };

export function SourceBadges({ sources }: Props) {
  const labels: Record<string, string> = {
    glossary: "Glossary",
    document: "Document",
    website: "Website",
    web: "Web",
    synthesis: "Synthesis",
    model: "Model-only",
    demo: "Demo",
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
