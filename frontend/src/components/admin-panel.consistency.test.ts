import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import * as ts from "typescript";

function parseSource() {
  const source = readFileSync(resolve(process.cwd(), "src/components/admin-panel.tsx"), "utf-8");
  const file = ts.createSourceFile("admin-panel.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  return { source, file };
}

describe("AdminPanel consistency", () => {
  it("uses explicit en-US locale in date-time formatter", () => {
    const { file } = parseSource();
    let found = false;
    const visit = (node: ts.Node) => {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
        if (node.expression.name.text === "toLocaleString" && node.arguments.length > 0) {
          const firstArg = node.arguments[0];
          if (ts.isStringLiteral(firstArg) && firstArg.text === "en-US") {
            found = true;
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
    expect(found).toBe(true);
  });

  it("keeps explicit labels for glossary creation fields", () => {
    const { file } = parseSource();
    const found = new Set<string>();
    const requiredLabels = new Set(["Glossary name", "Description", "Priority"]);

    const visit = (node: ts.Node) => {
      if (ts.isJsxElement(node)) {
        const tag = node.openingElement.tagName.getText(file);
        if (tag === "span") {
          const text = node.children
            .filter(ts.isJsxText)
            .map((child) => child.getText(file).trim())
            .join(" ")
            .trim();
          if (requiredLabels.has(text)) {
            found.add(text);
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
    expect(found).toEqual(requiredLabels);
  });

  it("uses modal-based confirmations instead of window.confirm", () => {
    const { file } = parseSource();
    let hasWindowConfirm = false;
    let hasConfirmModal = false;

    const visit = (node: ts.Node) => {
      if (
        ts.isCallExpression(node)
        && ts.isPropertyAccessExpression(node.expression)
        && node.expression.expression.getText(file) === "window"
        && node.expression.name.text === "confirm"
      ) {
        hasWindowConfirm = true;
      }
      if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(file) === "ConfirmModal") {
        hasConfirmModal = true;
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
    expect(hasWindowConfirm).toBe(false);
    expect(hasConfirmModal).toBe(true);
  });

  it("exposes explicit model selectors for chat and embeddings", () => {
    const { source } = parseSource();
    expect(source.includes("Chat model")).toBe(true);
    expect(source.includes("Embedding model")).toBe(true);
  });

  it("does not render redundant source-type filter in knowledge section", () => {
    const { source } = parseSource();
    expect(source.includes("Source type")).toBe(false);
    expect(source.includes("knowledgeSourceFilter")).toBe(false);
  });

  it("supports collapsible admin sections via shared toggle header", () => {
    const { source } = parseSource();
    expect(source.includes("function SectionToggleHeader")).toBe(true);
    expect(source.includes("glossariesOpen")).toBe(true);
    expect(source.includes("knowledgeBaseOpen")).toBe(true);
    expect(source.includes("sourceImpactOpen")).toBe(true);
    expect(source.includes("responseSettingsOpen")).toBe(true);
    expect(source.includes("userLimitsOpen")).toBe(true);
    expect(source.includes("qdrantMaintenanceOpen")).toBe(true);
    expect(source.includes("pendingRegistrationsOpen")).toBe(true);
  });

  it("keeps advanced admin sections collapsed by default", () => {
    const { source } = parseSource();
    expect(source.includes("const [responseSettingsOpen, setResponseSettingsOpen] = useState(false);")).toBe(true);
    expect(source.includes("const [userLimitsOpen, setUserLimitsOpen] = useState(false);")).toBe(true);
    expect(source.includes("const [qdrantMaintenanceOpen, setQdrantMaintenanceOpen] = useState(false);")).toBe(true);
    expect(source.includes("const [sourceImpactOpen, setSourceImpactOpen] = useState(false);")).toBe(true);
    expect(source.includes("const [userTokenUsageOpen, setUserTokenUsageOpen] = useState(false);")).toBe(true);
  });

  it("renders pending registrations before response settings", () => {
    const { source } = parseSource();
    const pendingIdx = source.indexOf('title="Pending Registrations"');
    const responseIdx = source.indexOf('title="Response Settings"');
    expect(pendingIdx).toBeGreaterThanOrEqual(0);
    expect(responseIdx).toBeGreaterThanOrEqual(0);
    expect(pendingIdx).toBeLessThan(responseIdx);
  });

  it("uses modal-driven glossary create/import/add actions", () => {
    const { source } = parseSource();
    expect(source.includes("createGlossaryModalOpen")).toBe(true);
    expect(source.includes("importGlossaryModalOpen")).toBe(true);
    expect(source.includes("addGlossaryEntryModalOpen")).toBe(true);
    expect(source.includes("Create glossary")).toBe(true);
    expect(source.includes("Import glossary CSV")).toBe(true);
    expect(source.includes("Add glossary term")).toBe(true);
  });

  it("keeps default glossary clear action distinct from delete action", () => {
    const { source } = parseSource();
    expect(source.includes("Clear entries")).toBe(true);
    expect(source.includes("border-amber-300")).toBe(true);
    expect(source.includes("btn btn-danger")).toBe(true);
  });

  it("renders source impact analytics block and usage badges in knowledge list", () => {
    const { source } = parseSource();
    expect(source.includes("Source Impact Analytics")).toBe(true);
    expect(source.includes("Top used sources")).toBe(true);
    expect(source.includes("Never used sources")).toBe(true);
    expect(source.includes("Show only unused")).toBe(true);
    expect(source.includes("Used {usageCount} times")).toBe(true);
    expect(source.includes("last used")).toBe(true);
    expect(source.includes("Failed + unused")).toBe(true);
    expect(source.includes("Unused &gt; 30d")).toBe(true);
    expect(source.includes("Unused ({sourceImpact?.window_days ?? sourceImpactDays}d)")).toBe(true);
  });

  it("exposes the controlled Product Security Playbook sync action", () => {
    const { source } = parseSource();
    expect(source.includes("Product Security Playbook")).toBe(true);
    expect(source.includes("defrixx/Product-security-playbook")).toBe(true);
    expect(source.includes("/admin/playbook/sync")).toBe(true);
    expect(source.includes("github_playbook")).toBe(true);
    expect(source.includes("Sync playbook")).toBe(true);
  });

  it("renders user token usage analytics with sort and window summary", () => {
    const { source } = parseSource();
    expect(source.includes("User Token Usage")).toBe(true);
    expect(source.includes("/admin/analytics/token-usage/users")).toBe(true);
    expect(source.includes("Sort by total tokens")).toBe(true);
    expect(source.includes("Show only with requests")).toBe(true);
    expect(source.includes("Highest first")).toBe(true);
    expect(source.includes("Lowest first")).toBe(true);
    expect(source.includes("Window total tokens")).toBe(true);
    expect(source.includes("Avg daily tokens (window)")).toBe(true);
    expect(source.includes("Avg tokens per request (window)")).toBe(true);
  });
});
