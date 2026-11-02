"""Package 3 transition chain CRUD (app DB)."""
from __future__ import annotations

from sqlalchemy import select

from database import SessionLocal, JiraTransitionChain, init_db
from services import jira_transition_chains as chains


def test_transition_chain_crud_roundtrip():
    init_db()
    with SessionLocal() as db:
        for row in db.scalars(
            select(JiraTransitionChain).where(JiraTransitionChain.name == "ci-test-chain")
        ).all():
            db.delete(row)
        db.commit()

    chains.upsert_transition_chain(
        jira_project_key="*",
        name="ci-test-chain",
        steps=["Start Progress", "Resolve Issue"],
        sort_order=0,
    )
    listed = chains.list_transition_chains()
    match = [c for c in listed if c["name"] == "ci-test-chain"]
    assert match, "chain should be listed"
    assert match[0]["steps"] == ["Start Progress", "Resolve Issue"]
    chains.delete_transition_chain(match[0]["id"])
    listed2 = chains.list_transition_chains()
    assert not any(c["name"] == "ci-test-chain" for c in listed2)


def test_resolve_chain_to_labels_matches_raw_and_friendly(monkeypatch):
    def fake_list(user_id, issue_key, jira_project_key=None):
        return [
            {"id": "1", "name": "Start Progress", "label": "Start"},
            {"id": "2", "name": "Resolve Issue", "label": "Resolve"},
        ]

    monkeypatch.setattr(
        "services.jira_service.list_transitions_friendly", fake_list
    )
    labels = chains.resolve_chain_to_labels(
        1, "SIT-1", ["Start Progress", "Resolve Issue"], jira_project_key="SIT"
    )
    assert labels == ["Start", "Resolve"]
