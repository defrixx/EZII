import { SOURCE_LABELS, normalizeSourceType } from "@/lib/source-labels";

type Props = {
  sources: string[];
  tooltips?: Partial<Record<string, string>>;
};

export function SourceBadges({ sources, tooltips }: Props) {
  return (
    <div className="flex gap-2 mt-2 flex-wrap">
      {sources.map((s) => {
        const normalized = normalizeSourceType(s);
        const tooltip = (tooltips && tooltips[normalized]) || undefined;
        return (
          <span
            key={`${s}-${normalized}`}
            className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200"
            title={tooltip}
          >
            {SOURCE_LABELS[normalized] || normalized}
          </span>
        );
      })}
    </div>
  );
}
