import { describe, expect, it } from "vitest";

import { KNOWLEDGE_STATUS_FILTER_OPTIONS, knowledgeStatusLabel } from "@/lib/knowledge-status";

describe("knowledge status helpers", () => {
  it("includes processing in filter options", () => {
    expect(KNOWLEDGE_STATUS_FILTER_OPTIONS.map((item) => item.value)).toContain("processing");
  });

  it("returns readable labels for known statuses", () => {
    expect(knowledgeStatusLabel("approved")).toBe("Approved");
    expect(knowledgeStatusLabel("processing")).toBe("Processing");
    expect(knowledgeStatusLabel("draft")).toBe("Draft");
  });
});
