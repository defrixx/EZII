import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Root layout favicon metadata", () => {
  it("declares explicit favicon metadata entries", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/layout.tsx"), "utf-8");

    expect(source.includes("export const metadata")).toBe(true);
    expect(source.includes('url: "/favicon.ico"')).toBe(true);
    expect(source.includes('url: "/icon.svg"')).toBe(true);
  });
});
