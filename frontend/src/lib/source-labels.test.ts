import { describe, expect, it } from "vitest";

import { SOURCE_LABELS, normalizeSourceType } from "@/lib/source-labels";

describe("source labels", () => {
  it("keeps english labels for source badges", () => {
    expect(SOURCE_LABELS.glossary).toBe("Glossary");
    expect(SOURCE_LABELS.upload).toBe("Document");
    expect(SOURCE_LABELS.github_playbook).toBe("GitHub Playbook");
    expect(SOURCE_LABELS.website).toBe("Website");
    expect(SOURCE_LABELS.model).toBe("Model-only");
  });

  it("normalizes legacy document source type to upload", () => {
    expect(normalizeSourceType("document")).toBe("upload");
    expect(normalizeSourceType("upload")).toBe("upload");
  });
});
