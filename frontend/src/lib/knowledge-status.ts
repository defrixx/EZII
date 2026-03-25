export type KnowledgeStatus = "draft" | "processing" | "approved" | "archived" | "failed";

export const KNOWLEDGE_STATUS_FILTER_OPTIONS: Array<{ value: "all" | KnowledgeStatus; label: string }> = [
  { value: "all", label: "All" },
  { value: "approved", label: "Approved" },
  { value: "processing", label: "Processing" },
  { value: "draft", label: "Draft" },
  { value: "failed", label: "Failed" },
  { value: "archived", label: "Archived" },
];

export function knowledgeStatusLabel(status: KnowledgeStatus): string {
  switch (status) {
    case "approved":
      return "Approved";
    case "archived":
      return "Archived";
    case "failed":
      return "Failed";
    case "processing":
      return "Processing";
    case "draft":
    default:
      return "Draft";
  }
}
