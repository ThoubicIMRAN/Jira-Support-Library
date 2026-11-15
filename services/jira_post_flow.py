"""Run the actions of the Jira dialog as independent, retry-safe steps.

Steps: comment, watchers, each attachment, time log, transition(s). Every step records itself
in ``done`` when it succeeds, so pressing Post again after a partial failure retries only the
steps that failed (no second comment, no double time log, no second status change).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable

from services import jira_service
from services.jira_client import JiraError
from utils.errors import safe_message

logger = logging.getLogger(__name__)


@dataclass
class StepOutcome:
    results: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and not self.errors


def _message(exc: Exception) -> str:
    return str(exc)[:300] if isinstance(exc, (JiraError, ValueError)) else safe_message(exc)


def _step(done: set, name: str, label: str, fn: Callable[[], str | None], out: StepOutcome) -> None:
    if name in done:
        out.results.append(f"✔ {label} (already done)")
        return
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 - reported per step, never aborts the other steps
        logger.warning("Jira step %s failed: %s", name, type(exc).__name__, exc_info=True)
        out.errors.append(f"{label}: {_message(exc)}")
        return
    done.add(name)
    out.results.append(f"✔ {label}{(' ' + detail) if detail else ''}")


def run_post_steps(
    user_id: int,
    issue_key: str,
    *,
    comment: str,
    internal: bool,
    idempotency_key: str,
    done: set,
    watchers: Iterable[str] = (),
    files: Iterable[tuple[str, bytes, str | None]] = (),
    time_raw: str = "",
    chain: list[tuple[str, str]] | None = None,
) -> StepOutcome:
    """Execute the selected actions in a fixed order; ``done`` is updated in place."""
    out = StepOutcome()

    def post_comment() -> str | None:
        posted = jira_service.add_comment(user_id, issue_key, comment, internal=internal, idempotency_key=idempotency_key)
        return None if posted else "(already posted)"

    _step(done, "comment", "Comment", post_comment, out)

    ids = [w for w in dict.fromkeys(w.strip().lstrip("@") for w in watchers) if w]
    if ids:
        def add_watchers() -> str | None:
            problems = jira_service.add_watchers(user_id, issue_key, ids)
            if problems:
                raise JiraError("; ".join(str(p) for p in problems[:3]))
            return f"({len(ids)})"

        _step(done, "watchers", "Watchers", add_watchers, out)

    for name, data, mime in files:
        _step(done, f"file:{name}", f"File {name}", lambda n=name, d=data, m=mime: jira_service.add_attachment(user_id, issue_key, n, d, m) and None, out)

    if (time_raw or "").strip():
        _step(done, "time", "Time", lambda: str(jira_service.log_work(user_id, issue_key, time_raw)), out)

    for i, (tid, label) in enumerate(chain or []):
        before = len(out.errors)
        # one step at a time: availability is re-checked against the ticket's *current* status,
        # and a retry resumes after the last step that really happened
        _step(
            done, f"transition:{i}:{tid}", f"Status → {label}",
            lambda t=tid, lab=label: jira_service.multi_step_transition(user_id, issue_key, [t], labels=[lab]) and None,
            out,
        )
        if len(out.errors) > before:
            break                       # later steps depend on this one
    return out
