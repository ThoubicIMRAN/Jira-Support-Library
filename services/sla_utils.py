"""SLA / ageing badges from Jira issue timestamps (no extra Jira config)."""
from __future__ import annotations

from datetime import date, datetime, timezone


def _parse_day(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def issue_badges(issue: dict, *, stale_days: int = 14) -> list[str]:
    """Return badge codes: overdue, due_soon, stale, aging."""
    today = date.today()
    badges: list[str] = []
    due = _parse_day(issue.get("duedate"))
    if due is not None:
        delta = (due - today).days
        if delta < 0:
            badges.append("overdue")
        elif delta <= 2:
            badges.append("due_soon")

    updated = _parse_dt(issue.get("updated"))
    if updated is not None:
        age = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).days
        if age >= stale_days:
            badges.append("stale")
        elif age >= max(7, stale_days // 2):
            badges.append("aging")

    created = _parse_dt(issue.get("created"))
    if created is not None and "overdue" not in badges:
        cage = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).days
        if cage >= 30 and "stale" not in badges:
            badges.append("aging")

    return badges


def badge_label(code: str) -> str:
    return {
        "overdue": "🔴 Overdue",
        "due_soon": "🟠 Due soon",
        "stale": "⚪ No update 14d+",
        "aging": "🟡 Aging",
    }.get(code, code)
