"""Support: announcements, feedback; maintenance = superadmin only; announcements = admin+."""

from __future__ import annotations

import logging

import streamlit as st

from components.cards import page_header
from services import comms_service
from utils.errors import safe_message

logger = logging.getLogger(__name__)


def _render_announcements() -> None:
    items = comms_service.active_announcements()
    if not items:
        st.info("No active announcements right now.")
        return

    for a in items:
        # Use a lightweight custom HTML block instead of the chunky default border
        with st.container():
            st.markdown(
                f"""
                <div style="background: var(--secondary-background-color); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                    <h4 style="margin-top: 0; margin-bottom: 0.5rem;">{a["title"]}</h4>
                    <p style="margin-bottom: 0.5rem; font-size: 0.95rem;">{a["body"]}</p>
                    <span style="font-size: 0.75rem; color: var(--text-color); opacity: 0.6;">
                        {a.get("created_at", "")}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_feedback_form(user) -> None:
    st.markdown(
        "Share improvements, bugs, or support needs. Managers and admins will be notified."
    )

    with st.form("feedback_form", clear_on_submit=True):
        cat = st.selectbox(
            "Type", ["improvement", "bug", "support"], format_func=str.title
        )
        title = st.text_input(
            "Title", placeholder="Brief summary of the issue or idea..."
        )
        body = st.text_area(
            "Details",
            height=140,
            placeholder="Provide context, steps to reproduce, or your proposed solution...",
        )

        submitted = st.form_submit_button("Submit Feedback", type="primary")

    if submitted:
        if not title.strip() or not body.strip():
            st.error("Title and details are required.")
            return

        try:
            fid = comms_service.submit_feedback(
                user_id=user.id,
                title=title.strip(),
                body=body.strip(),
                category=cat,
                project_id=st.session_state.get("project_id"),
            )
            st.success(f"Feedback submitted successfully (#{fid}).")
        except Exception as exc:
            logger.exception("Failed to submit feedback")
            st.error(safe_message(exc))


def _render_admin_inbox() -> None:
    feedback_items = comms_service.list_feedback(40)
    if not feedback_items:
        st.info("The feedback inbox is currently empty.")
        return

    for fb in feedback_items:
        with st.expander(f"#{fb['id']} · {fb['title']} ({fb['category']})"):
            st.caption(f"Submitted by **{fb['user']}** on {fb['created_at']}")
            st.markdown("---")
            st.write(fb["body"])


def _render_admin_tools(user, role: str) -> None:
    is_super = role == "superadmin"

    # Use tabs within the admin section to prevent a massive scroll
    t_maint, t_ann, t_inbox = st.tabs(
        ["🚧 Maintenance", "📢 New Announcement", "📥 Feedback Inbox"]
    )

    if is_super:
        with t_maint:
            st.markdown("#### System Maintenance Mode")
            st.caption(
                "Publishing maintenance will restrict access to superadmins only."
            )

            with st.form("maint_form"):
                mtitle = st.text_input(
                    "Maintenance title", placeholder="e.g., Scheduled Database Upgrade"
                )
                mbody = st.text_area(
                    "Maintenance message", placeholder="The system will be down for..."
                )

                c1, c2 = st.columns(2)
                publish = c1.form_submit_button(
                    "Publish Maintenance", type="primary", width="stretch"
                )
                clear = c2.form_submit_button("Clear Maintenance", width="stretch")

            if publish:
                if mtitle.strip() and mbody.strip():
                    comms_service.set_maintenance(
                        user_id=user.id,
                        title=mtitle.strip(),
                        message=mbody.strip(),
                        active=True,
                    )
                    st.success("Maintenance mode activated.")
                    st.rerun()
                else:
                    st.error("Title and message are required.")

            if clear:
                comms_service.clear_maintenance()
                st.success("Maintenance mode cleared.")
                st.rerun()
    else:
        with t_maint:
            st.info("Maintenance mode is controlled by superadmins only.")

    with t_ann:
        st.markdown("#### Publish Announcement")
        with st.form("ann_form"):
            atitle = st.text_input(
                "Announcement title", placeholder="e.g., New Jira templates available"
            )
            abody = st.text_area("Announcement body", placeholder="Details here...")
            publish_ann = st.form_submit_button("Publish Announcement", type="primary")

        if publish_ann:
            if atitle.strip() and abody.strip():
                comms_service.add_announcement(
                    user_id=user.id, title=atitle.strip(), body=abody.strip()
                )
                st.success("Announcement published.")
                st.rerun()
            else:
                st.error("Title and body are required.")

    with t_inbox:
        _render_admin_inbox()


def render(user) -> None:
    # Inject CSS to tighten up the spacing just like the settings page
    st.markdown(
        """
        <style>
        [data-testid="stTabsContent"] { padding-top: 1rem !important; }
        [data-testid="stForm"] { padding: 1.5rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    page_header(
        "Support & Product", "Announcements, feedback, and system controls.", icon="💬"
    )

    role = getattr(user, "role", "user")
    is_admin = role in ("admin", "superadmin")

    # Build the main tabs based on role
    tabs = ["Announcements", "Submit Feedback"]
    if is_admin:
        tabs.append("Admin Tools")

    tab_objs = st.tabs(tabs)

    with tab_objs[0]:
        _render_announcements()

    with tab_objs[1]:
        _render_feedback_form(user)

    if is_admin and len(tab_objs) > 2:
        with tab_objs[2]:
            _render_admin_tools(user, role)
