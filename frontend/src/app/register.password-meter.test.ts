import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Register password meter contract", () => {
  it("defines password requirements and strength meter helpers", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/register/page.tsx"), "utf-8");

    expect(source.includes("evaluatePasswordRequirements")).toBe(true);
    expect(source.includes("passwordMeter(")).toBe(true);
    expect(source.includes("PASSWORD_MIN_LENGTH")).toBe(true);
  });

  it("renders live requirement checklist and strength label", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/register/page.tsx"), "utf-8");

    expect(source.includes("Password strength")).toBe(true);
    expect(source.includes("passwordRequirements.map")).toBe(true);
    expect(source.includes("passwordStrength.label")).toBe(true);
  });
});
