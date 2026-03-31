from app.core.markdown_security import (
    MAX_MARKDOWN_CHARS,
    normalize_markdown_text,
    normalize_safe_href,
    render_markdown_to_safe_html,
    sanitize_markdown_stream_chunk,
)


def test_normalize_safe_href_fail_closed_for_dangerous_schemes():
    assert normalize_safe_href("javascript:alert(1)") is None
    assert normalize_safe_href("data:text/html;base64,PHNjcmlwdD4=") is None
    assert normalize_safe_href("%6a%61%76%61%73%63%72%69%70%74%3aalert(1)") is None
    assert normalize_safe_href("java\nscript:alert(1)") is None


def test_normalize_safe_href_allows_only_http_https_mailto():
    assert normalize_safe_href("https://example.com/a") == "https://example.com/a"
    assert normalize_safe_href("http://example.com/a") == "http://example.com/a"
    assert normalize_safe_href("mailto:sec@example.com") == "mailto:sec@example.com"
    assert normalize_safe_href("/docs/security") is None
    assert normalize_safe_href("#section-1") is None
    assert normalize_safe_href("//evil.example.com/path") is None


def test_render_markdown_to_safe_html_strips_raw_html_and_applies_rel_policy():
    html = render_markdown_to_safe_html(
        "Click [site](https://example.com)\n\n<script>alert(1)</script>\n\n[data](data:text/html,abc)"
    )
    assert "<script>" not in html
    assert 'href="https://example.com"' in html
    assert 'rel="nofollow ugc noopener noreferrer"' in html
    assert 'target="_blank"' in html
    assert "data:text/html" not in html


def test_render_markdown_handles_broken_tables_and_zero_width_chars():
    html = render_markdown_to_safe_html(
        "Head\u200ber\n| a | b |\n| --- |\n| c | d |\n"
    )
    assert "\u200b" not in html
    assert "Head" in html
    assert "<script>" not in html


def test_normalize_markdown_text_enforces_length_cap():
    raw = ("1. x\n" * 200_000) + "tail"
    normalized = normalize_markdown_text(raw)
    assert len(normalized) == MAX_MARKDOWN_CHARS


def test_render_markdown_handles_huge_nested_lists_without_unsafe_output():
    nested = "\n".join(f"- level {i}" for i in range(5000))
    html = render_markdown_to_safe_html(nested)
    assert "<ul>" in html
    assert "<script>" not in html


def test_sanitize_markdown_stream_chunk_drops_unsafe_markdown_links():
    out = sanitize_markdown_stream_chunk("[bad](javascript:alert(1)) [ok](https://example.com)")
    assert "javascript:" not in out
    assert "[bad]" in out
    assert "(https://example.com)" in out
