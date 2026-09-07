export const knowledgeBaseIcons = [
  "📚",
  "💼",
  "🌸",
  "🛡️",
  "🧪",
  "📖",
  "🗂️",
  "🚀",
  "🎯",
] as const;

export function knowledgeBaseIcon(id: string, name: string) {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem(`kb-icon:${id}`);
    if (
      saved &&
      knowledgeBaseIcons.includes(saved as (typeof knowledgeBaseIcons)[number])
    )
      return saved;
  }
  const normalized = name.toLocaleLowerCase();
  if (normalized.includes("работ") || normalized.includes("work")) return "💼";
  if (normalized.includes("япон") || normalized.includes("japan")) return "🌸";
  if (normalized.includes("security") || normalized.includes("безопас"))
    return "🛡️";
  return "📚";
}

export function saveKnowledgeBaseIcon(id: string, icon: string) {
  localStorage.setItem(`kb-icon:${id}`, icon);
  window.dispatchEvent(
    new CustomEvent("knowledge-base-visual-change", { detail: { id, icon } }),
  );
}
