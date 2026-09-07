"use client";

import { Fragment, ReactNode, useState } from "react";

function inline(value: string): ReactNode[] {
  const parts = value.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)]+\))/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function MarkdownMessage({ content, copyLabel, copiedLabel }: { content: string; copyLabel: string; copiedLabel: string }) {
  const [copied, setCopied] = useState(false);
  const blocks = content.split(/(```[\s\S]*?```)/g);
  return (
    <div className="markdown-message">
      {blocks.map((block, blockIndex) => {
        if (block.startsWith("```") && block.endsWith("```")) {
          const body = block.slice(3, -3).replace(/^[^\n]*\n/, "");
          return <pre key={blockIndex}><code>{body.trimEnd()}</code></pre>;
        }
        return block.split("\n").map((line, lineIndex) => {
          const key = `${blockIndex}-${lineIndex}`;
          if (/^###\s/.test(line)) return <h4 key={key}>{inline(line.slice(4))}</h4>;
          if (/^##?\s/.test(line)) return <h3 key={key}>{inline(line.replace(/^##?\s/, ""))}</h3>;
          if (/^[-*]\s/.test(line)) return <div className="markdown-list-item" key={key}>• <span>{inline(line.slice(2))}</span></div>;
          return line ? <p key={key}>{inline(line)}</p> : <br key={key} />;
        });
      })}
      <button className="message-copy" type="button" onClick={async () => { await navigator.clipboard.writeText(content); setCopied(true); window.setTimeout(() => setCopied(false), 1600); }}>
        {copied ? `✓ ${copiedLabel}` : `⧉ ${copyLabel}`}
      </button>
    </div>
  );
}
