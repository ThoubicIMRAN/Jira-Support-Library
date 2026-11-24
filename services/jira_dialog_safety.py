"""Safety helpers for the Jira action dialog.

This module is deliberately dependency-free (no Streamlit, no DB, no network)
so it can be unit-tested and reused from the backend without side effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

# Jira-format user mentions and library placeholders that must be filled
# before the agent posts the comment to a ticket.
#
# Matches:
#   - @TICKET, @SUMMARY, @ASSIGNEE, @PROJECT, @STATUS
#   - [~username] (Jira's native user-mention syntax)
#
# Does NOT match:
#   - @NAME, @DESIGNATION, @R (personalized at post time by the backend)
#   - Arbitrary brackets like [URGENT] or [P1] (legitimate customer text)
_PLACEHOLDER_RE = re.compile(
    r"@TICKET\b|@SUMMARY\b|@ASSIGNEE\b|@PROJECT\b|@STATUS\b|\[~[^\]\n]+\]",
    re.IGNORECASE,
)

# Personalization tokens that are resolved on post by ``personalize()`` and
# therefore should *not* be flagged as unresolved by the pre-flight check.
_RESOLVED_AT_POST = {"@NAME", "@DESIGNATION", "@R", "@REPORTER"}


def unresolved_placeholders(text: str) -> list[str]:
    """Return the distinct unfilled placeholders found in ``text``, in order."""
    if not text:
        return []

    found: list[str] = []
    for match in _PLACEHOLDER_RE.finditer(text):
        token = match.group(0)
        if token.upper() in _RESOLVED_AT_POST:
            continue
        if token not in found:
            found.append(token)
    return found


def action_plan_lines(
    *,
    issue_key: str,
    internal: bool,
    time_raw: str,
    transition_labels: list[str],
    files_n: int,
    closing: bool,
    include_comment: bool = True,
) -> list[str]:
    """Build the human-readable summary shown to the agent before they submit."""
    plan: list[str] = []

    if include_comment:
        visibility = "Internal comment" if internal else "Customer-visible comment"
        plan.append(f"{visibility} on **{issue_key}**")

    if transition_labels:
        plan.append("Transition: " + " → ".join(transition_labels))

    if (time_raw or "").strip():
        plan.append(f"Log time: `{(time_raw or '').strip()}`")

    if files_n:
        plan.append(f"Attach {files_n} file(s)")

    if closing:
        plan.append("Includes resolution / closing notes")

    return plan


def _stringify_watchers(watchers: Iterable) -> list[str]:
    """Return a clean, sorted, de-duplicated list of watcher usernames."""
    out: set[str] = set()
    for raw in watchers or []:
        text = str(raw).strip().lstrip("@").lower()
        if text:
            out.add(text)
    return sorted(out)


def _stringify_chain(chain: Iterable) -> list[tuple[str, str]]:
    """Normalize ``chain`` to a sorted list of ``(transition_id, label)`` tuples.

    Accepts either ``list[tuple[str, str]]`` or ``list[str]`` (a plain list of
    transition IDs) so callers aren't forced to shape their data one way.
    """
    out: list[tuple[str, str]] = []
    for item in chain or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            tid, label = item[0], item[1]
        else:
            tid, label = item, ""
        out.append((str(tid).strip(), str(label).strip()))
    return sorted(out)


def execution_fingerprint(
    *,
    issue_key: str,
    comment: str,
    include_comment: bool,
    internal: bool,
    watchers: list[str],
    file_fingerprints: list[tuple[str, str]],
    time_raw: str,
    chain: list[tuple[str, str]],
    transition_labels: list[str] | None = None,
    closing: bool = False,
) -> str:
    """Stable identity for one exact set of Jira dialog actions.

    The dialog uses this to clear completed-step state whenever the user changes
    the payload, preventing a retry from silently skipping newly edited actions.
    File content is represented by SHA-256 digests, never stored in session keys.

    Every field that affects what gets sent to Jira is included, so toggling a
    checkbox, changing a transition label, or editing the comment invalidates
    the fingerprint and forces a full re-run of the action plan.
    """
    payload = {
        "issue_key": (issue_key or "").strip().upper(),
        "comment": (comment or "").strip() if include_comment else "",
        "include_comment": bool(include_comment),
        "internal": bool(internal) if include_comment else False,
        "watchers": _stringify_watchers(watchers),
        "files": sorted(
            (str(name).strip(), str(digest).strip())
            for name, digest in (file_fingerprints or [])
        ),
        "time_raw": (time_raw or "").strip(),
        "chain": _stringify_chain(chain),
        "transition_labels": [str(x).strip() for x in (transition_labels or [])],
        "closing": bool(closing),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
