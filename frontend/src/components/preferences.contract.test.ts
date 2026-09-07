import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { en, ru } from "./app-preferences";
const read = (path: string) => readFileSync(resolve(path), "utf8");
describe("local UI contract", () => {
  it("keeps complete Russian and English dictionaries", () => {
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort());
    expect(ru.bases).toBe("Базы знаний");
    expect(en.bases).toBe("Knowledge bases");
  });
  it("supports and persists every theme", () => {
    const preferences = read("src/components/app-preferences.tsx"),
      layout = read("src/app/layout.tsx");
    expect(preferences).toMatch(
      /type Theme\s*=\s*"light"\s*\|\s*"dark"\s*\|\s*"system"/,
    );
    expect(preferences).toMatch(/localStorage\.setItem\("theme",\s*theme\)/);
    expect(layout).toContain("document.documentElement.dataset.theme");
  });
  it("updates and preloads the document locale", () => {
    expect(read("src/components/app-preferences.tsx")).toMatch(
      /document\.documentElement\.lang\s*=\s*locale/,
    );
    expect(read("src/app/layout.tsx")).toContain(
      "document.documentElement.lang=l==='en'?'en':'ru'",
    );
  });
  it("has no auth flow", () => {
    const api = read("src/lib/api.ts");
    expect(api).not.toContain("refreshAuthSession");
    expect(api).not.toContain("Authorization");
  });
  it("chooses a base only when creating a chat", () => {
    const panel = read("src/components/chat-panel.tsx"),
      send = panel.slice(
        panel.indexOf("async function send"),
        panel.indexOf("if (loading)"),
      );
    expect(panel).toMatch(/knowledge_base_id:\s*selectedKb/);
    expect(send).toContain("/messages/");
    expect(send).not.toContain("knowledge_base_id");
    expect(read("src/lib/api.ts")).toMatch(
      /JSON\.stringify\(\{\s*content,\s*locale\s*\}\)/,
    );
  });
  it("uses unified feedback states", () => {
    for (const file of [
      "chat-panel.tsx",
      "sources-panel.tsx",
      "glossaries-panel.tsx",
      "manage-panel.tsx",
      "maintenance-panel.tsx",
    ]) {
      const source = read(`src/components/${file}`);
      expect(source).toContain("loading");
      expect(source).toContain("ErrorToast");
    }
    expect(read("src/components/error-toast.tsx")).toMatch(
      /kind\s*=\s*"error"/,
    );
  });
  it("marks active navigation and shows icons", () => {
    const nav = read("src/components/app-nav.tsx");
    expect(nav).toContain("usePathname");
    expect(nav).toContain("aria-current");
    expect(nav).toContain("💬");
    expect(nav).toContain("⚙️");
  });
  it("groups chats and glossaries by knowledge base", () => {
    expect(read("src/components/chat-panel.tsx")).toMatch(
      /chat\.knowledge_base_id\s*===\s*base\.id/,
    );
    expect(read("src/components/glossaries-panel.tsx")).toMatch(
      /bases\.map\(\(base\)\s*=>\s*\(/,
    );
  });
  it("separates manage sections and keeps playbook import", () => {
    const manage = read("src/components/manage-panel.tsx");
    expect(manage).toContain("section-tabs");
    expect(manage).toMatch(/activeTab\s*!==\s*"connections"/);
    expect(manage).toMatch(/activeTab\s*!==\s*"models"/);
    expect(manage.match(/playbook\/sync/g)).toHaveLength(1);
    expect(manage).toContain("playbook-summary");
  });
  it("uses prominent create-base actions and labelled preferences", () => {
    for (const file of [
      "chat-panel.tsx",
      "sources-panel.tsx",
      "glossaries-panel.tsx",
    ]) {
      expect(read(`src/components/${file}`)).toContain("button-link primary");
    }
    const preferences = read("src/components/app-preferences.tsx");
    expect(preferences).toContain("🇷🇺 Русский");
    expect(preferences).toContain("🌙");
  });
  it("supports source filtering and selected bulk actions", () => {
    const sources = read("src/components/sources-panel.tsx");
    expect(sources).toContain("sources/bulk");
    expect(sources).toContain('type="search"');
    expect(sources).toContain("publishSelected");
    expect(sources).toContain("source-stats");
  });
  it("supports collapsible bases, model hints, detailed traces, and base visuals", () => {
    const manage = read("src/components/manage-panel.tsx");
    expect(manage).toContain("kb-card");
    expect(manage).toContain("vector-size-options");
    expect(manage).toMatch(
      /form\.get\("name"\)\s*\|\|\s*form\.get\("model_id"\)/,
    );
    expect(read("src/components/diagnostics-panel.tsx")).toContain(
      "retrieval_ms",
    );
    expect(read("src/components/chat-panel.tsx")).toContain(
      "knowledgeBaseIcon",
    );
    expect(read("src/lib/knowledge-base-visual.ts")).toContain(
      "saveKnowledgeBaseIcon",
    );
  });
  it("supports chat lifecycle and stopping generation", () => {
    const chat = read("src/components/chat-panel.tsx");
    expect(chat).toContain("renameChat");
    expect(chat).toContain("deleteChat");
    expect(chat).toContain("AbortController");
    expect(chat).toContain("scrollIntoView");
  });
  it("shows an accessible animated response indicator", () => {
    const chat = read("src/components/chat-panel.tsx"),
      styles = read("src/app/enhancements.css");
    expect(chat).toContain("typing-message");
    expect(chat).toContain("awaitingAnswer");
    expect(styles).toContain("typing-bounce");
    expect(styles).toContain("prefers-reduced-motion");
  });
});
