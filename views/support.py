"""Support: announcements, feedback; maintenance = superadmin only; announcements = admin+."""
from __future__ import annotations

import logging

import streamlit as st

from components.cards import page_header

from services import comms_service

logger = logging.getLogger(__name__)


def render(user) -> None:
    page_header("💬 Support & product")
    st.caption("Announcements and improvement ideas.")

    role = getattr(user, "role", "user")
    is_super = role == "superadmin"
    is_admin = role in ("admin", "superadmin")
    is_manager = role in ("manager", "admin", "superadmin")

    tabs = ["Announcements", "Request / feedback"]
    if is_admin:
        tabs.append("Admin")
    tab_objs = st.tabs(tabs)

    with tab_objs[0]:
        items = comms_service.active_announcements()
        if not items:
            st.info("No active announcements.")
        for a in items:
            with st.container(border=True):
                st.markdown(f"### {a['title']}")
                st.write(a["body"])
                if a.get("created_at"):
                    st.caption(str(a["created_at"]))

    with tab_objs[1]:
        st.markdown("Share improvements, bugs, or support needs.")
        cat = st.selectbox("Type", ["improvement", "bug", "support"], format_func=lambda x: x.title())
        title = st.text_input("Title")
        body = st.text_area("Details", height=140)
        if st.button("Submit", type="primary"):
            if not title.strip() or not body.strip():
                st.error("Title and details are required.")
            else:
                try:
                    fid = comms_service.submit_feedback(
                        user_id=user.id,
                        title=title,
                        body=body,
                        category=cat,
                        project_id=st.session_state.get("project_id"),
                    )
                    st.success(f"Submitted (#{fid}). Managers and admins are notified.")
                except Exception as exc:
                    logger.exception("feedback")
                    st.error(str(exc))

    if is_admin and len(tab_objs) > 2:
        with tab_objs[2]:
            if is_super:
                st.markdown("#### Maintenance (superadmin only)")
                mtitle = st.text_input("Maintenance title", key="maint_title")
                mbody = st.text_area("Maintenance message", key="maint_body")
                c1, c2 = st.columns(2)
                if c1.button("Publish maintenance", type="primary"):
                    if mtitle.strip() and mbody.strip():
                        comms_service.set_maintenance(
                            user_id=user.id, title=mtitle, message=mbody, active=True
                        )
                        st.success("Maintenance active.")
                        st.rerun()
                if c2.button("Clear maintenance"):
                    comms_service.clear_maintenance()
                    st.success("Cleared.")
                    st.rerun()
            else:
                st.caption("Maintenance is controlled by superadmin only.")

            st.markdown("#### Announcement (admin+)")
            atitle = st.text_input("Announcement title", key="ann_title")
            abody = st.text_area("Announcement body", key="ann_body")
            if st.button("Publish announcement"):
                if atitle.strip() and abody.strip():
                    comms_service.add_announcement(user_id=user.id, title=atitle, body=abody)
                    st.success("Published.")
                    st.rerun()

            if is_manager:
                st.markdown("#### Feedback inbox")
                for fb in comms_service.list_feedback(40):
                    with st.container(border=True):
                        st.markdown(f"**#{fb['id']}** · `{fb['category']}` — {fb['title']}")
                        st.caption(f"{fb['user']} · {fb['created_at']}")
                        st.write(fb["body"])
