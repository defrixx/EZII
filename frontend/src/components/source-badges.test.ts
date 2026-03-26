import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("SourceBadges", () => {
  it("supports tooltip metadata for source badges", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/source-badges.tsx"), "utf-8");

    expect(source.includes("tooltips?: Partial<Record<string, string>>")).toBe(true);
    expect(source.includes("title={tooltip}")).toBe(true);
  });
});
