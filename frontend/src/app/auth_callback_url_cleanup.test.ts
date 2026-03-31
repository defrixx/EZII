import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Auth callback URL cleanup", () => {
  it("cleans callback query before exchanging OIDC code", () => {
    const source = readFileSync(resolve(process.cwd(), "src/app/auth/callback/page.tsx"), "utf-8");
    const replaceStateIndex = source.indexOf('window.history.replaceState(null, "", "/auth/callback");');
    const exchangeIndex = source.indexOf("await exchangeCode(code, state);");

    expect(replaceStateIndex).toBeGreaterThan(-1);
    expect(exchangeIndex).toBeGreaterThan(-1);
    expect(replaceStateIndex).toBeLessThan(exchangeIndex);
  });
});
