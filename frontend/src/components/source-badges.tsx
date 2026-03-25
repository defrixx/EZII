import { SOURCE_LABELS } from "@/lib/source-labels";

type Props = { sources: string[] };

export function SourceBadges({ sources }: Props) {
  return (
    <div className="flex gap-2 mt-2 flex-wrap">
      {sources.map((s) => (
        <span
          key={s}
          className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200"
        >
          {SOURCE_LABELS[s] || s}
        </span>
      ))}
    </div>
  );
}
