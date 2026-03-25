import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Root layout locale", () => {
  it("declares en-US html language", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/layout.tsx"), "utf-8");
    expect(source.includes('<html lang="en-US">')).toBe(true);
  });
});
