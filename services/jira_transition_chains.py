"""Package 3: named multi-step Jira transition chain presets."""
from __future__ import annotations

import json

from sqlalchemy import select

from database import SessionLocal, JiraTransitionChain


def list_transition_chains(jira_project_key: str | None = None) -> list[dict]:
    """Return named multi-step transition presets."""
    with SessionLocal() as db:
        stmt = select(JiraTransitionChain).order_by(
            JiraTransitionChain.sort_order, JiraTransitionChain.name
        )
        if jira_project_key:
            stmt = stmt.where(
                (JiraTransitionChain.jira_project_key == jira_project_key)
                | (JiraTransitionChain.jira_project_key == "*")
            )
        rows = list(db.scalars(stmt).all())
        out = []
        for r in rows:
            try:
                steps = json.loads(r.steps_json or "[]")
            except Exception:
                steps = []
            if not isinstance(steps, list):
                steps = []
            out.append(
                {
                    "id": r.id,
                    "jira_project_key": r.jira_project_key,
                    "name": r.name,
                    "steps": [str(s).strip() for s in steps if str(s).strip()],
                    "sort_order": r.sort_order,
                }
            )
        return out


def upsert_transition_chain(
    *,
    jira_project_key: str,
    name: str,
    steps: list[str],
    sort_order: int = 0,
    chain_id: int | None = None,
) -> None:
    jira_project_key = (jira_project_key or "*").strip() or "*"
    name = (name or "").strip()
    steps = [str(s).strip() for s in (steps or []) if str(s).strip()]
    if not name:
        raise ValueError("Chain name is required.")
    if not steps:
        raise ValueError("At least one transition step is required.")
    with SessionLocal() as db:
        row = db.get(JiraTransitionChain, chain_id) if chain_id else None
        if not row:
            row = JiraTransitionChain(
                jira_project_key=jira_project_key,
                name=name,
                steps_json=json.dumps(steps, ensure_ascii=False),
                sort_order=int(sort_order or 0),
            )
            db.add(row)
        else:
            row.jira_project_key = jira_project_key
            row.name = name
            row.steps_json = json.dumps(steps, ensure_ascii=False)
            row.sort_order = int(sort_order or 0)
        db.commit()


def delete_transition_chain(chain_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(JiraTransitionChain, chain_id)
        if row:
            db.delete(row)
            db.commit()


def resolve_chain_to_labels(
    user_id: int,
    issue_key: str,
    chain_steps: list[str],
    *,
    jira_project_key: str | None = None,
) -> list[str]:
    """Map chain raw step names to current friendly labels available on the issue."""
    from services.jira_service import list_transitions_friendly

    transitions = list_transitions_friendly(
        user_id, issue_key, jira_project_key=jira_project_key
    ) or []
    by_raw = {}
    by_label = {}
    for t in transitions:
        name = (t.get("name") or "").strip()
        label = (t.get("label") or name).strip()
        if name:
            by_raw[name.lower()] = label
        if label:
            by_label[label.lower()] = label
    out: list[str] = []
    for step in chain_steps or []:
        s = (step or "").strip()
        if not s:
            continue
        lab = by_raw.get(s.lower()) or by_label.get(s.lower())
        if lab and lab not in out:
            out.append(lab)
    return out
