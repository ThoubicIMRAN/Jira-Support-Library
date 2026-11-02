"""Safety helpers for the Jira action dialog."""
from __future__ import annotations

import re

# Ticket/context tokens that should be filled before post.
# Intentionally excludes @NAME / @DESIGNATION / @R (personalize on post).
_PLACEHOLDER_RE = re.compile(
    r"@TICKET\b|@SUMMARY\b|@ASSIGNEE\b|@PROJECT\b|@STATUS\b|\[[^\]\n]+\]"
)


def unresolved_placeholders(text: str) -> list[str]:
    found: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(text or ""):
        tok = m.group(0)
        if tok.startswith("[~]"):
            continue
        if tok.startswith("[") and len(tok) > 2 and tok[1] == "~":
            continue
        if tok not in found:
            found.append(tok)
    return found


def action_plan_lines(
    *,
    issue_key: str,
    internal: bool,
    time_raw: str,
    transition_labels: list[str],
    files_n: int,
    closing: bool,
) -> list[str]:
    plan = [
        ("Internal comment" if internal else "Customer-visible comment")
        + f" on **{issue_key}**"
    ]
    if transition_labels:
        plan.append("Transition: " + " → ".join(transition_labels))
    if (time_raw or "").strip():
        plan.append(f"Log time: `{(time_raw or '').strip()}`")
    if files_n:
        plan.append(f"Attach {files_n} file(s)")
    if closing:
        plan.append("Includes resolution / closing notes")
    return plan
