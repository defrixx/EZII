import { describe, expect, it } from "vitest";

import { SOURCE_LABELS } from "@/lib/source-labels";

describe("source labels", () => {
  it("keeps english labels for source badges", () => {
    expect(SOURCE_LABELS.glossary).toBe("Glossary");
    expect(SOURCE_LABELS.document).toBe("Document");
    expect(SOURCE_LABELS.website).toBe("Website");
    expect(SOURCE_LABELS.model).toBe("Model-only");
  });
});
