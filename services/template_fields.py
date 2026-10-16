"""Bracket placeholders in library templates: [request link], [App], etc.

Used only when composing a comment in the Jira dialog. The stored template
in the library is never modified.
"""
from __future__ import annotations

import html as html_lib
import re
from typing import Mapping

_BRACKET_RE = re.compile(r"\[([^\]\n]+)\]")
_WIKI_MENTION_RE = re.compile(r"^~")

# Markdown: [text](url)
_MD_LINK_RE = re.compile(
    r"^\[([^\]]*)\]\((https?://[^\s\)]+)\)\s*$",
    re.IGNORECASE,
)
# HTML: <a href="url">text</a>
_HTML_A_RE = re.compile(
    r"""<a\s+[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
# Bare URL
_BARE_URL_RE = re.compile(r"^(https?://\S+)$", re.IGNORECASE)
# Jira wiki already: [text|url]
_JIRA_LINK_RE = re.compile(
    r"^\[([^\]|]+)\|((?:https?://)[^\]]+)\]\s*$",
    re.IGNORECASE,
)


def extract_bracket_fields(text: str) -> list[str]:
    """Return unique field labels in order of first appearance."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _BRACKET_RE.finditer(text or ""):
        label = (m.group(1) or "").strip()
        if not label:
            continue
        if _WIKI_MENTION_RE.match(label):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def normalize_hyperlink_paste(raw: str) -> str:
    """Accept pasted hyperlinks in common formats; emit text safe for Jira comments.

    Supported input forms:
      - plain URL: https://example.com/path
      - markdown: [label](https://example.com)
      - HTML: <a href="https://...">label</a>
      - Jira wiki: [label|https://...]
      - angle-bracket URL: <https://...>

    Output:
      - Jira wiki [text|url] when a label is known
      - otherwise the bare URL (Jira auto-links it)
      - other text returned stripped as-is
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""

    # Already Jira wiki link
    m = _JIRA_LINK_RE.match(s)
    if m:
        return f"[{m.group(1).strip()}|{m.group(2).strip()}]"

    # Markdown
    m = _MD_LINK_RE.match(s)
    if m:
        text, url = m.group(1).strip(), m.group(2).strip()
        return f"[{text}|{url}]" if text else url

    # HTML anchor (possibly with extra whitespace / single tag only)
    m = _HTML_A_RE.search(s)
    if m:
        url = html_lib.unescape(m.group(1).strip())
        text = re.sub(r"<[^>]+>", "", m.group(2) or "")
        text = html_lib.unescape(text).strip()
        if text and text != url:
            return f"[{text}|{url}]"
        return url

    # <https://...>
    if s.startswith("<") and s.endswith(">") and "://" in s:
        inner = s[1:-1].strip()
        if _BARE_URL_RE.match(inner):
            return inner

    # Bare URL (allow trailing punctuation stripped lightly)
    m = _BARE_URL_RE.match(s.rstrip(".,;"))
    if m:
        return m.group(1)

    # Multi-line paste: first line URL + rest ignored, or full keep
    first = s.splitlines()[0].strip()
    if _BARE_URL_RE.match(first.rstrip(".,;")):
        return first.rstrip(".,;")

    # HTML-escaped bare link debris
    unescaped = html_lib.unescape(s)
    if unescaped != s:
        return normalize_hyperlink_paste(unescaped)

    return s


def apply_bracket_fields(text: str, values: Mapping[str, str] | None) -> str:
    """Replace [label] with normalized values. Missing -> empty string."""
    if not text:
        return text or ""
    values = values or {}
    norm = {
        (k or "").strip().lower(): normalize_hyperlink_paste(v if v is not None else "")
        for k, v in values.items()
    }

    def repl(m: re.Match) -> str:
        label = (m.group(1) or "").strip()
        if _WIKI_MENTION_RE.match(label):
            return m.group(0)
        return str(norm.get(label.lower(), ""))

    return _BRACKET_RE.sub(repl, text)
