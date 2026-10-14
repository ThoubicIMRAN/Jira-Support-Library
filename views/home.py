"""Home — project library dashboard (prototype: hero + project card grid)."""
from __future__ import annotations

from services.project_access import visible_project_ids
import logging
from typing import Any, Sequence

import streamlit as st
from sqlalchemy import func, select

from components.cards import empty_state, hero_banner, project_card
from database import Category, Project, Response, SessionLocal
from services.workspace_service import pinned_project_ids, toggle_pin
from utils.layout import card_columns
from utils.navigation import PAGE_PROJECT, goto

logger = logging.getLogger(__name__)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _matches(project: Project, term: str) -> bool:
    if not term:
        return True
    haystack = " ".join(filter(None, (project.name, project.description, project.key))).lower()
    return term in haystack


def _sort_by_pins(rows: Sequence, pins: set[int]) -> list:
    return sorted(rows, key=lambda row: (row[0].id not in pins, row[0].sort_order, row[0].id))


def _load_project_rows() -> list:
    """Projects with category/response counts in a single round-trip."""
    cat_counts = (
        select(Category.project_id.label("pid"), func.count(Category.id).label("n"))
        .group_by(Category.project_id).subquery()
    )
    resp_counts = (
        select(Category.project_id.label("pid"), func.count(Response.id).label("n"))
        .join(Response, Response.category_id == Category.id)
        .group_by(Category.project_id).subquery()
    )
    statement = (
        select(Project, func.coalesce(cat_counts.c.n, 0), func.coalesce(resp_counts.c.n, 0))
        .outerjoin(cat_counts, cat_counts.c.pid == Project.id)
        .outerjoin(resp_counts, resp_counts.c.pid == Project.id)
        .where(Project.is_deleted == False)  # noqa: E712
        .order_by(Project.sort_order, Project.id)
    )
    with SessionLocal() as db:
        return list(db.execute(statement).all())


def _render_grid(shown: Sequence, pins: set[int], user_id: int) -> None:
    if not shown:
        if not st.session_state.get("global_search"):
            empty_state("📚", "Your library is empty",
                        "Administrators: Admin Settings → Content & users → Add project, then import responses from JSON on the project page.")
        else:
            empty_state("🔎", "No projects found", "Try a different search term.")
        return
    count = card_columns()
    columns = st.columns(count, gap="medium")
    for index, (project, n_cat, n_resp) in enumerate(shown):
        with columns[index % count]:
            opened, pin_clicked = project_card(
                project, _as_int(n_cat), _as_int(n_resp), pinned=project.id in pins
            )
        if opened:
            goto(PAGE_PROJECT, project_id=project.id)
        if pin_clicked:
            try:
                toggle_pin(user_id, project.id)
            except Exception:  # noqa: BLE001
                logger.exception("Pin toggle failed for project %s", project.id)
                st.error("Could not update the pin. Please try again.")
            else:
                st.rerun()


def render(user) -> None:
    term = (st.session_state.get("global_search") or "").strip().lower()
    try:
        rows = _load_project_rows()
    except Exception:  # noqa: BLE001
        logger.exception("Could not load project rows")
        st.error("Could not load projects. Please try again.")
        return

    visible = visible_project_ids(user.id, user.role)  # None = unrestricted
    if visible is not None:
        rows = [row for row in rows if row[0].id in visible]
    pins = set(pinned_project_ids(user.id))
    shown = _sort_by_pins([row for row in rows if _matches(row[0], term)], pins)

    hero_banner(
        "Your Jira Comment Library, Organised",
        f"Welcome, {user.full_name or 'there'}. One central hub for reusable support responses.",
        tag="Live library",
        stats=[
            (str(len(rows)), "Projects"),
            (str(sum(_as_int(r[1]) for r in rows)), "Categories"),
            (str(sum(_as_int(r[2]) for r in rows)), "Responses"),
        ],
    )
    _render_grid(shown, pins, user.id)
