export const SOURCE_LABELS: Record<string, string> = {
  glossary: "Glossary",
  upload: "Document",
  website: "Website",
  synthesis: "Synthesis",
  model: "Model-only",
  demo: "Demo",
};

export function normalizeSourceType(raw: string): string {
  const value = String(raw || "").trim().toLowerCase();
  if (value === "document") {
    return "upload";
  }
  return value;
}
