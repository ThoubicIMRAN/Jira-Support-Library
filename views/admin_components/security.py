from __future__ import annotations

import streamlit as st
from sqlalchemy import func, select

from config import APP_ENV, APP_SECRET_KEY, ALLOW_DEFAULT_BOOTSTRAP_ADMIN, SESSION_TIMEOUT_MINUTES, SESSION_ABSOLUTE_HOURS
from database import AppSession, SessionLocal, User
from services.session_service import revoke_user_sessions


def render(user) -> None:
    if user.role not in {"admin", "superadmin"}:
        st.error("Administrator access required.")
        return

    st.subheader("Security")
    st.caption("Review authentication posture, sessions and production readiness.")

    checks = [
        ("Application secret", bool(APP_SECRET_KEY) and APP_SECRET_KEY != "development-only-change-me"),
        ("Bootstrap admin disabled", not ALLOW_DEFAULT_BOOTSTRAP_ADMIN or APP_ENV != "production"),
        ("Idle session timeout", SESSION_TIMEOUT_MINUTES > 0),
        ("Absolute session limit", SESSION_ABSOLUTE_HOURS > 0),
        ("Production environment", APP_ENV == "production"),
    ]
    for label, ok in checks:
        c1, c2 = st.columns([4, 1])
        c1.write(label)
        c2.write("✅" if ok else "⚠️")

    st.markdown("---")
    st.subheader("Active sessions")
    if user.role != "superadmin":
        st.info("Only superadmins can revoke other users' sessions.")
        return

    with SessionLocal() as db:
        rows = db.execute(
            select(AppSession.user_id, func.count(AppSession.id), func.max(AppSession.last_seen_at))
            .where(AppSession.revoked_at.is_(None))
            .group_by(AppSession.user_id)
            .order_by(func.max(AppSession.last_seen_at).desc())
        ).all()
        accounts = {u.id: u for u in db.scalars(select(User)).all()}

    for user_id, count, last_seen in rows:
        account = accounts.get(user_id)
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{account.username if account else user_id}** · {count} active session(s)  \nLast seen: {last_seen}")
            if user_id != user.id and c2.button("Revoke all", key=f"ac_revoke_{user_id}"):
                revoke_user_sessions(user_id)
                st.toast("Sessions revoked.", icon="🔒")
                st.rerun()
