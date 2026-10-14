from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from database import AuditLog, SessionLocal, User
from services.audit_service import audit_csv, query_audit


def render(user) -> None:
    if user.role not in {"admin", "superadmin"}:
        st.error("Administrator access required.")
        return

    st.subheader("Audit logs")
    st.caption("Search administrative and security activity. Sensitive credentials should never be written to audit details.")
    with SessionLocal() as db:
        actions = db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()
        entities = db.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)).all()
        users = db.scalars(select(User).order_by(User.username)).all()

    c1, c2, c3 = st.columns(3)
    action = c1.selectbox("Action", ["All", *actions])
    entity = c2.selectbox("Entity", ["All", *entities])
    selected_user = c3.selectbox("User", [None, *[u.id for u in users]], format_func=lambda x: "All" if x is None else next(u.username for u in users if u.id == x))
    c4, c5 = st.columns(2)
    date_from = c4.date_input("From", value=None)
    date_to = c5.date_input("To", value=None)
    limit = st.number_input("Maximum rows", 50, 5000, 500, 50)

    rows = query_audit(None if action == "All" else action, None if entity == "All" else entity, selected_user, date_from, date_to, int(limit))
    st.dataframe(rows, width="stretch", hide_index=True)
    st.download_button("Download CSV", audit_csv(rows), "jira_audit_report.csv", "text/csv")
