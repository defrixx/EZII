import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import * as ts from "typescript";

function parseChatPanel() {
  const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");
  const file = ts.createSourceFile("chat-panel.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  return { source, file };
}

describe("ChatPanel accessibility structure", () => {
  it("does not use div role=button wrappers for chat rows", () => {
    const { file } = parseChatPanel();
    let hasRoleButtonDiv = false;
    const visit = (node: ts.Node) => {
      if (ts.isJsxOpeningElement(node) && node.tagName.getText(file) === "div") {
        for (const attribute of node.attributes.properties) {
          if (!ts.isJsxAttribute(attribute)) continue;
          if (attribute.name.text !== "role") continue;
          const value = attribute.initializer;
          if (value && ts.isStringLiteral(value) && value.text === "button") {
            hasRoleButtonDiv = true;
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
    expect(hasRoleButtonDiv).toBe(false);
  });

  it("keeps explicit aria-label on chat delete action", () => {
    const { file } = parseChatPanel();
    let foundDeleteAriaTemplate = false;
    const visit = (node: ts.Node) => {
      if (ts.isJsxAttribute(node) && node.name.text === "aria-label" && node.initializer && ts.isJsxExpression(node.initializer)) {
        const expression = node.initializer.expression;
        if (expression && ts.isTemplateExpression(expression) && expression.head.text.startsWith("Delete chat ")) {
          foundDeleteAriaTemplate = true;
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
    expect(foundDeleteAriaTemplate).toBe(true);
  });

  it("keeps explicit aria-labels for pin and archive actions", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");
    expect(source.includes("Pin chat")).toBe(true);
    expect(source.includes("Unpin chat")).toBe(true);
    expect(source.includes("Archive chat")).toBe(true);
    expect(source.includes("Unarchive chat")).toBe(true);
  });

  it("uses ConfirmModal-based deletion instead of window.confirm", () => {
    const { source } = parseChatPanel();
    expect(source.includes("window.confirm")).toBe(false);
    expect(source.includes("<ConfirmModal")).toBe(true);
    expect(source.includes("chatPendingDelete")).toBe(true);
  });

  it("preserves newline input on Shift+Enter and sends on Enter", () => {
    const { file } = parseChatPanel();
    let checksShiftKey = false;
    const visit = (node: ts.Node) => {
      if (ts.isPropertyAccessExpression(node) && node.getText(file) === "event.shiftKey") {
        checksShiftKey = true;
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
    expect(checksShiftKey).toBe(true);
  });

  it("loads chat list with archived entries enabled", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/chat-panel.tsx"), "utf-8");
    expect(source.includes("/chats?include_archived=true")).toBe(true);
  });
});
