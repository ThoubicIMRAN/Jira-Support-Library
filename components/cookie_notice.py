"""Minimal first-visit notice for session cookies (Streamlit apps)."""
from __future__ import annotations

import streamlit as st

_ACK_KEY = "cookie_notice_ack"


def render_cookie_notice() -> None:
    """Show a one-time acknowledgement that the app uses a session cookie."""
    if st.session_state.get(_ACK_KEY):
        return
    with st.container(border=True):
        st.markdown(
            "**Session notice** — This app uses a session cookie to keep you signed in. "
            "Use it only on trusted devices. Open **Privacy & Terms** in the sidebar for details."
        )
        if st.button("Got it", key="cookie_notice_ack_btn"):
            st.session_state[_ACK_KEY] = True
            st.rerun()
