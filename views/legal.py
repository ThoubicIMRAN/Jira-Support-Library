"""Privacy Policy and Terms of Use (internal app launch checklist)."""
from __future__ import annotations

import streamlit as st

from components.cards import page_header
from config import APP_NAME, APP_VERSION


def render_privacy(_user=None) -> None:
    page_header("Privacy Policy")
    st.caption(f"{APP_NAME} · v{APP_VERSION}")
    st.markdown(
        f"""
This internal application (**{APP_NAME}**) is operated for organisational support use only.

**Data we process**
- Account profile (name, email, role, optional avatar)
- Session and authentication data
- Jira / Confluence credentials you choose to store (encrypted at rest)
- Audit logs of actions you take in the app (comments posted, transitions, admin changes)

**How we use data**
- To authenticate you and enforce role-based access
- To post to Jira / Confluence on your behalf when you connect an account
- To improve reliability (audit, rate limits, security)

**Retention**
- Account and audit data are retained according to your organisation's IT policy
- You may request account deactivation through an administrator

**Contact**
- Speak to your system administrator or the team that runs this deployment

This page is a template for internal deployments. Replace with your organisation's official policy where required.
"""
    )


def render_terms(_user=None) -> None:
    page_header("Terms of Use")
    st.caption(f"{APP_NAME} · v{APP_VERSION}")
    st.markdown(
        f"""
By using **{APP_NAME}** you agree to:

1. Use the app only for authorised work purposes.
2. Not share your password or API tokens.
3. Only post content to Jira/Confluence that you are allowed to post under your organisation's rules.
4. Understand that actions you take (comments, transitions, bulk runs) are audited.
5. Accept that the service may be rate-limited and that credentials are stored encrypted for your convenience.

Administrators may suspend access for misuse or security reasons.

This page is a template for internal deployments. Replace with your organisation's official terms where required.
"""
    )


def render(user=None) -> None:
    """Sidebar entry: show Privacy and Terms as tabs."""
    page_header("Privacy & Terms")
    st.caption(f"{APP_NAME} · v{APP_VERSION}")
    tab_p, tab_t = st.tabs(["Privacy Policy", "Terms of Use"])
    with tab_p:
        render_privacy(user)
    with tab_t:
        render_terms(user)
