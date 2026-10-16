"""Bracket placeholders in library templates: [request link], [App], etc.

Used only when composing a comment in the Jira dialog. The stored template
in the library is never modified.
"""
from __future__ import annotations

import re
from typing import Mapping

# [Field label] — non-empty, no nested brackets
_BRACKET_RE = re.compile(r"\[([^\]\n]+)\]")

# Do not treat Jira wiki mentions as fill-in fields: [~username]
_WIKI_MENTION_RE = re.compile(r"^~")


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


def apply_bracket_fields(text: str, values: Mapping[str, str] | None) -> str:
    """Replace [label] with values[label]. Missing/empty -> empty string.

    Matching is case-insensitive on the label.
    """
    if not text:
        return text or ""
    values = values or {}
    norm = {(k or "").strip().lower(): (v if v is not None else "") for k, v in values.items()}

    def repl(m: re.Match) -> str:
        label = (m.group(1) or "").strip()
        if _WIKI_MENTION_RE.match(label):
            return m.group(0)
        return str(norm.get(label.lower(), ""))

    return _BRACKET_RE.sub(repl, text)
