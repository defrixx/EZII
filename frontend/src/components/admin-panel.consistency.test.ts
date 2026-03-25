import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("AdminPanel consistency", () => {
  const source = readFileSync(resolve(process.cwd(), "src/components/admin-panel.tsx"), "utf-8");

  it("uses a consistent English locale for date-time formatting", () => {
    expect(source.includes('toLocaleString("en-US"')).toBe(true);
  });

  it("uses explicit labels for glossary creation fields", () => {
    expect(source.includes("Glossary name")).toBe(true);
    expect(source.includes("Description")).toBe(true);
    expect(source.includes("Priority")).toBe(true);
  });
});
