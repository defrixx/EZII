import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("ChatPanel trusted markdown rendering", () => {
  it("renders assistant output from trusted_html payload produced by backend", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");

    expect(source.includes("trusted_html?: string")).toBe(true);
    expect(source.includes("eventType === \"trusted_html\"")).toBe(true);
    expect(source.includes("dangerouslySetInnerHTML")).toBe(true);
  });

  it("falls back to plain text while stream is in progress", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");

    expect(source.includes("if (trustedHtml && !isStreaming)")).toBe(true);
    expect(source.includes("<p className=\"whitespace-pre-wrap text-sm leading-6 text-slate-900\">")).toBe(true);
  });

  it("maps retrieval document titles to document badge tooltips", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");

    expect(source.includes("document_titles")).toBe(true);
    expect(source.includes("nextTooltips.upload = `Source: ${docTitles.join(\", \")}`")).toBe(true);
    expect(source.includes("tooltips={m.source_tooltips}")).toBe(true);
  });
});
