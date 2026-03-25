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
});
