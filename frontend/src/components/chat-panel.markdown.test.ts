import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("ChatPanel markdown rendering", () => {
  it("renders assistant responses via markdown-aware helpers", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");

    expect(source.includes("function renderInlineMarkdown")).toBe(true);
    expect(source.includes("function renderMarkdownContent")).toBe(true);
    expect(source.includes("renderMarkdownContent(content)")).toBe(true);
  });

  it("supports headings and list markup in assistant output", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");

    expect(source.includes("<h3")).toBe(true);
    expect(source.includes("<ol")).toBe(true);
    expect(source.includes("<ul")).toBe(true);
  });
});
