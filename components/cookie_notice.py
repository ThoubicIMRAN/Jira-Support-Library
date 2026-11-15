"""First-visit cookie / session notice (internal app)."""
from __future__ import annotations

import streamlit as st


NOTICE_KEY = "jsl_cookie_notice_accepted"


def render_cookie_notice() -> None:
    """Show a compact banner until the user acknowledges session cookies."""
    if st.session_state.get(NOTICE_KEY):
        return
    with st.container(border=True):
        c1, c2 = st.columns([5, 1])
        c1.markdown(
            "**Session cookie notice** — This app uses a session cookie to keep you signed in. "
            "Required for authentication. See **Privacy Policy** for details."
        )
        if c2.button("Got it", key="cookie_notice_ok", type="primary", width="stretch"):
            st.session_state[NOTICE_KEY] = True
            st.rerun()
