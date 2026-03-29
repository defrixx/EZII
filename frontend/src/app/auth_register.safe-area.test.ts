import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Auth and register safe-area layout", () => {
  it("applies safe-area utility classes on auth page container", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/auth/page.tsx"), "utf-8");
    expect(source.includes("safe-x safe-top safe-bottom")).toBe(true);
  });

  it("applies safe-area utility classes on register page container", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/register/page.tsx"), "utf-8");
    expect(source.includes("safe-x safe-top safe-bottom")).toBe(true);
  });

  it("applies safe-area utility classes on chat layout container", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");
    expect(source.includes("safe-x safe-top")).toBe(true);
    expect(source.includes("safe-bottom")).toBe(true);
  });

  it("applies safe-area utility classes on logout page container", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/logout/page.tsx"), "utf-8");
    expect(source.includes("safe-x safe-top safe-bottom")).toBe(true);
  });
});
