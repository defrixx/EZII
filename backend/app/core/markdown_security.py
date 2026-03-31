from __future__ import annotations

import html
import re
from urllib.parse import unquote, urlsplit

MAX_MARKDOWN_CHARS = 100_000
MAX_STREAM_CHUNK_CHARS = 8_000
EXTERNAL_LINK_REL = "nofollow ugc noopener noreferrer"
ALLOWED_URI_SCHEMES = {"http", "https", "mailto"}
ZERO_WIDTH_TRANSLATION = {
    ord("\u200b"): None,  # zero-width space
    ord("\u200c"): None,  # zero-width non-joiner
    ord("\u200d"): None,  # zero-width joiner
    ord("\ufeff"): None,  # BOM / zero-width no-break space
    ord("\u2060"): None,  # word joiner
}

_ORDERED_ITEM_RE = re.compile(r"^\s*\d+\.\s+(.+)$")
_UNORDERED_ITEM_RE = re.compile(r"^\s*[-*]\s+(.+)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_STRIKE_RE = re.compile(r"~~([^~\n]+)~~")


def normalize_markdown_text(text: str, *, max_len: int = MAX_MARKDOWN_CHARS) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").translate(ZERO_WIDTH_TRANSLATION)
    # Keep text printable and markdown-friendly while dropping hidden/control characters.
    sanitized = "".join(ch for ch in normalized if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    if len(sanitized) > max_len:
        return sanitized[:max_len]
    return sanitized


def sanitize_markdown_stream_chunk(chunk: str) -> str:
    normalized = normalize_markdown_text(chunk, max_len=MAX_STREAM_CHUNK_CHARS)

    def stream_link_replacer(match: re.Match[str]) -> str:
        label = match.group(1) or ""
        raw_href = match.group(2) or ""
        title = match.group(3) or ""
        safe_href = normalize_safe_href(raw_href)
        if not safe_href:
            return label
        title_suffix = f' "{title}"' if title else ""
        return f"[{label}]({safe_href}{title_suffix})"

    return _LINK_RE.sub(stream_link_replacer, normalized)


def normalize_safe_href(raw_href: str | None) -> str | None:
    if not raw_href:
        return None
    href = html.unescape(raw_href).strip()
    if not href:
        return None

    decoded = href
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value

    # Remove invisible separators and controls to block obfuscated schemes.
    compact = "".join(ch for ch in decoded if ch not in {" ", "\t", "\n", "\r", "\f", "\v"} and ord(ch) >= 32)
    if not compact:
        return None
    scheme = urlsplit(compact).scheme.lower()
    if scheme in ALLOWED_URI_SCHEMES:
        return compact
    return None


def _tokenize_inline(raw: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}
    token_index = 0
    out = raw

    def make_token(rendered: str) -> str:
        nonlocal token_index
        token = f"@@MD_TOKEN_{token_index}@@"
        placeholders[token] = rendered
        token_index += 1
        return token

    def code_replacer(match: re.Match[str]) -> str:
        return make_token(f"<code>{html.escape(match.group(1), quote=False)}</code>")

    out = _CODE_SPAN_RE.sub(code_replacer, out)

    def link_replacer(match: re.Match[str]) -> str:
        label = match.group(1) or ""
        raw_href = match.group(2) or ""
        title = match.group(3) or ""
        safe_href = normalize_safe_href(raw_href)
        if not safe_href:
            return make_token(html.escape(label, quote=False))
        escaped_label = html.escape(label, quote=False)
        escaped_href = html.escape(safe_href, quote=True)
        escaped_title = html.escape(title, quote=True) if title else ""
        is_external = safe_href.startswith("http://") or safe_href.startswith("https://") or safe_href.startswith("mailto:")
        target_attr = ' target="_blank"' if is_external else ""
        rel_attr = f' rel="{EXTERNAL_LINK_REL}"' if is_external else ""
        title_attr = f' title="{escaped_title}"' if escaped_title else ""
        return make_token(f'<a href="{escaped_href}"{title_attr}{target_attr}{rel_attr}>{escaped_label}</a>')

    out = _LINK_RE.sub(link_replacer, out)
    return out, placeholders


def render_markdown_to_safe_html(markdown_text: str) -> str:
    text = normalize_markdown_text(markdown_text)
    if not text:
        return "<p></p>"
    lines = text.split("\n")
    blocks: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()
        if not trimmed:
            i += 1
            continue

        if trimmed.startswith("```"):
            lang = html.escape(trimmed[3:].strip(), quote=True)
            i += 1
            code_lines: list[str] = []
            while i < len(lines):
                candidate = lines[i]
                if candidate.strip().startswith("```"):
                    i += 1
                    break
                code_lines.append(candidate)
                i += 1
            class_attr = f' class="language-{lang}"' if lang else ""
            code_html = html.escape("\n".join(code_lines), quote=False)
            blocks.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
            continue

        heading_match = _HEADING_RE.match(trimmed)
        if heading_match:
            level = min(6, len(heading_match.group(1)))
            blocks.append(f"<h{level}>{_render_inline(heading_match.group(2))}</h{level}>")
            i += 1
            continue

        ordered_match = _ORDERED_ITEM_RE.match(trimmed)
        if ordered_match:
            items: list[str] = []
            while i < len(lines):
                current = lines[i].strip()
                if not current:
                    i += 1
                    continue
                match = _ORDERED_ITEM_RE.match(current)
                if not match:
                    break
                items.append(f"<li>{_render_inline(match.group(1))}</li>")
                i += 1
            blocks.append(f"<ol>{''.join(items)}</ol>")
            continue

        unordered_match = _UNORDERED_ITEM_RE.match(trimmed)
        if unordered_match:
            items = []
            while i < len(lines):
                current = lines[i].strip()
                if not current:
                    i += 1
                    continue
                match = _UNORDERED_ITEM_RE.match(current)
                if not match:
                    break
                items.append(f"<li>{_render_inline(match.group(1))}</li>")
                i += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue

        if "|" in trimmed and i + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[i + 1].strip()):
            header_cells = _split_table_row(trimmed)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines):
                row_line = lines[i].strip()
                if not row_line or "|" not in row_line:
                    break
                rows.append(_split_table_row(row_line))
                i += 1
            header_html = "".join(f"<th>{_render_inline(cell)}</th>" for cell in header_cells)
            body_parts = []
            for row in rows:
                row_html = "".join(f"<td>{_render_inline(cell)}</td>" for cell in row)
                body_parts.append(f"<tr>{row_html}</tr>")
            blocks.append(f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>")
            continue

        if trimmed.startswith(">"):
            quote_lines: list[str] = []
            while i < len(lines):
                quote_candidate = lines[i].strip()
                if not quote_candidate.startswith(">"):
                    break
                quote_lines.append(quote_candidate[1:].lstrip())
                i += 1
            blocks.append(f"<blockquote>{_render_inline(' '.join(quote_lines))}</blockquote>")
            continue

        paragraph_lines = [line]
        i += 1
        while i < len(lines):
            candidate = lines[i]
            candidate_trimmed = candidate.strip()
            if not candidate_trimmed:
                break
            if (
                candidate_trimmed.startswith("```")
                or _HEADING_RE.match(candidate_trimmed)
                or _ORDERED_ITEM_RE.match(candidate_trimmed)
                or _UNORDERED_ITEM_RE.match(candidate_trimmed)
                or candidate_trimmed.startswith(">")
            ):
                break
            paragraph_lines.append(candidate)
            i += 1
        blocks.append(f"<p>{_render_inline(' '.join(x.strip() for x in paragraph_lines))}</p>")

    return "".join(blocks) or "<p></p>"


def _split_table_row(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip() for cell in row.split("|")]


def _render_inline(raw: str) -> str:
    tokenized, placeholders = _tokenize_inline(raw)
    escaped = html.escape(tokenized, quote=False)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _STRIKE_RE.sub(r"<del>\1</del>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    for token, rendered in placeholders.items():
        escaped = escaped.replace(html.escape(token, quote=False), rendered)
    return escaped
