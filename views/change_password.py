import logging

import streamlit as st

from auth import hash_password
from components.cards import page_header
from database import SessionLocal, User
from utils.errors import safe_message
from utils.validators import valid_password

logger = logging.getLogger(__name__)


def render(user):
    # Tighten the layout for a focused, single-task screen
    st.markdown(
        """
        <style>
        .block-container { max-width: 500px; padding-top: 4rem !important; }
        [data-testid="stForm"] { padding: 1.5rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    page_header("🔐 Change temporary password")
    st.warning(
        "You must change the bootstrap or temporary password before accessing the application.",
        icon="⚠️",
    )

    with st.form("mandatory_password_change"):
        password = st.text_input(
            "New password", type="password", placeholder="Minimum 8 characters"
        )
        confirm = st.text_input(
            "Confirm password", type="password", placeholder="Re-type password"
        )

        save = st.form_submit_button("Change password", type="primary", width="stretch")

    if not save:
        return

    # Validation
    if not valid_password(password):
        st.error("Password must contain at least 8 characters.")
        return
    if password != confirm:
        st.error("Passwords do not match.")
        return

    # Persistence
    try:
        with SessionLocal() as db:
            row = db.get(User, user.id)
            if row is None:
                st.error("User no longer exists. Please contact an administrator.")
                return

            row.password_hash = hash_password(password)
            row.must_change_password = False
            db.commit()

    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to update mandatory password for user %s", user.id)
        st.error(f"Could not save password: {safe_message(exc)}")
        return

    # Success
    st.success("Password changed successfully. Redirecting...")
    st.rerun()
