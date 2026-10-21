"""Parse @username mentions and normalize for Jira comments + watchers."""
from __future__ import annotations

import re

# @thoubic.imran or @j.doe — not email-only (avoid matching inside addresses poorly)
# Allow dots, hyphens, underscores in Jira usernames
_AT_USER_RE = re.compile(r"(?<!\[~)(?<![\w.])@([A-Za-z0-9][A-Za-z0-9._\-]+)")


def extract_at_usernames(text: str) -> list[str]:
    """Unique usernames from @user tokens (order preserved)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _AT_USER_RE.finditer(text or ""):
        u = m.group(1).strip()
        if not u or u.lower() in seen:
            continue
        # skip common non-user tokens
        if u.upper() in ("R", "NAME", "DESIGNATION", "ROLE", "DATE", "TICKET", "SUMMARY", "ASSIGNEE", "PROJECT", "STATUS"):
            continue
        seen.add(u.lower())
        out.append(u)
    return out


def to_jira_wiki_mentions(text: str) -> str:
    """Replace @username with [~username] for Jira Server/DC wiki markup.

    Leaves @R / @NAME style placeholders alone (handled by personalize).
    """
    def repl(m: re.Match) -> str:
        u = m.group(1)
        if u.upper() in ("R", "NAME", "DESIGNATION", "ROLE", "DATE", "TICKET", "SUMMARY", "ASSIGNEE", "PROJECT", "STATUS"):
            return m.group(0)
        return f"[~{u}]"

    return _AT_USER_RE.sub(repl, text or "")
