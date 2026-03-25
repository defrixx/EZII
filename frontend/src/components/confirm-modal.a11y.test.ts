import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import * as ts from "typescript";

function parseConfirmModal() {
  const source = readFileSync(resolve(process.cwd(), "src/components/ui/confirm-modal.tsx"), "utf-8");
  const file = ts.createSourceFile("confirm-modal.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  return { file };
}

describe("ConfirmModal accessibility contract", () => {
  it("declares semantic dialog attributes", () => {
    const { file } = parseConfirmModal();
    let hasDialogRole = false;
    let hasAriaModal = false;
    let hasAriaDescription = false;

    const visit = (node: ts.Node) => {
      if (ts.isJsxAttribute(node) && ts.isStringLiteral(node.initializer)) {
        if (node.name.text === "role" && node.initializer.text === "dialog") {
          hasDialogRole = true;
        }
        if (node.name.text === "aria-modal" && node.initializer.text === "true") {
          hasAriaModal = true;
        }
        if (node.name.text === "aria-describedby" && node.initializer.text === "confirm-modal-description") {
          hasAriaDescription = true;
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(file);

    expect(hasDialogRole).toBe(true);
    expect(hasAriaModal).toBe(true);
    expect(hasAriaDescription).toBe(true);
  });

  it("handles keyboard escape and focus trapping", () => {
    const { file } = parseConfirmModal();
    let checksEscape = false;
    let checksTab = false;
    let movesInitialFocus = false;
    let hasFocusableQuery = false;

    const visit = (node: ts.Node) => {
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken) {
        if (
          ts.isPropertyAccessExpression(node.left)
          && node.left.getText(file) === "event.key"
          && ts.isStringLiteral(node.right)
          && node.right.text === "Escape"
        ) {
          checksEscape = true;
        }
      }
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.ExclamationEqualsEqualsToken) {
        if (
          ts.isPropertyAccessExpression(node.left)
          && node.left.getText(file) === "event.key"
          && ts.isStringLiteral(node.right)
          && node.right.text === "Tab"
        ) {
          checksTab = true;
        }
      }
      if (
        ts.isVariableDeclaration(node)
        && ts.isIdentifier(node.name)
        && node.name.text === "focusable"
      ) {
        hasFocusableQuery = true;
      }
      if (
        ts.isCallExpression(node)
        && ts.isPropertyAccessExpression(node.expression)
        && node.expression.getText(file) === "cancelButtonRef.current?.focus"
      ) {
        movesInitialFocus = true;
      }
      ts.forEachChild(node, visit);
    };
    visit(file);

    expect(checksEscape).toBe(true);
    expect(checksTab).toBe(true);
    expect(movesInitialFocus).toBe(true);
    expect(hasFocusableQuery).toBe(true);
  });
});
