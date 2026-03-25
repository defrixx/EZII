import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("ChatPanel accessibility structure", () => {
  const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");

  it("does not use div role=button wrappers for chat rows", () => {
    expect(source.includes('role="button"')).toBe(false);
  });

  it("keeps explicit aria-label on chat delete action", () => {
    expect(source.includes("aria-label={`Delete chat ${c.title}`}")).toBe(true);
  });
});
