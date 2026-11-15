"""Privacy Policy and Terms of Use (internal enterprise app)."""
from __future__ import annotations

import streamlit as st

from components.cards import page_header
from config import APP_NAME, APP_VERSION, APP_URL


def render_privacy() -> None:
    page_header("Privacy Policy")
    st.caption(f"{APP_NAME} · v{APP_VERSION}")
    st.markdown(
        f"""
### 1. Who we are
**{APP_NAME}** is an internal IT support tool for authorised staff. It is not a public consumer website.

### 2. Data we process
- **Account data:** username, full name, email (optional), role, designation, profile photo (optional).
- **Authentication:** password hashes (or SSO identities), session tokens, login attempt metadata.
- **Usage:** favourites, recent responses, preferences, audit logs of content and Jira actions you perform.
- **Integrations:** Jira / Confluence credentials you connect are stored **encrypted** (Fernet) on the server; API tokens are never sent to the browser as plaintext secrets.

### 3. Why we process it
To provide the command library, authenticate users, enforce roles, post to Jira on your behalf, and keep an audit trail for operational security.

### 4. Cookies and local storage
We use a **session cookie** (`jira_support_session_token`) so you stay signed in across reloads. It is required for the app to work. Optional analytics (if enabled by your administrator) may set additional cookies.

### 5. Sharing
Data stays on systems controlled by your organisation. We do not sell personal data. Jira/Confluence receive only the actions you explicitly run (comments, transitions, attachments).

### 6. Retention
Accounts and audit logs are retained according to your organisation’s policy. Session tokens expire (idle and absolute timeouts). You or an admin can revoke sessions.

### 7. Your rights
Contact your administrator to correct profile data, reset credentials, or request account deactivation. SSO users should also use their identity provider tools where applicable.

### 8. Security
Access requires sign-in. Production deployments must use HTTPS, strong `APP_SECRET_KEY` / `FERNET_KEY`, and restricted network exposure (see deploy documentation).

### 9. Contact
Use in-app **Support** or your IT help desk. Application URL: `{APP_URL}`.

*Last updated: 2026-11-15*
"""
    )


def render_terms() -> None:
    page_header("Terms of Use")
    st.caption(f"{APP_NAME} · v{APP_VERSION}")
    st.markdown(
        f"""
### 1. Acceptance
By signing in to **{APP_NAME}** you agree to use the system only for authorised work purposes under your organisation’s policies.

### 2. Eligibility
Access is limited to users with valid accounts (local or SSO). Sharing credentials is prohibited.

### 3. Acceptable use
- Use library responses and Jira actions only on tickets and projects you are entitled to handle.
- Do not attempt to bypass role controls, rate limits, or audit logging.
- Do not upload malware or unlawful content via attachments.
- Do not scrape or bulk-export the library beyond your role permissions.

### 4. Content ownership
Library responses and operational data remain property of your organisation. You are responsible for the accuracy of comments you post to Jira.

### 5. Availability
The service is provided “as available.” Maintenance windows may be announced in-app.

### 6. Liability
The app assists support workflows; final responsibility for customer-facing Jira content rests with the signed-in agent and your organisation.

### 7. Changes
Administrators may update these terms. Continued use after notice constitutes acceptance.

### 8. Contact
Questions: in-app **Support** or your IT administrator.

*Last updated: 2026-11-15*
"""
    )


def render(user=None, *, section: str = "privacy") -> None:
    """Render privacy or terms. `user` is optional (login page has no user)."""
    tab = section if section in ("privacy", "terms") else "privacy"
    choice = st.radio(
        "Document",
        ["Privacy Policy", "Terms of Use"],
        index=0 if tab == "privacy" else 1,
        horizontal=True,
        label_visibility="collapsed",
        key="legal_doc_choice",
    )
    if choice.startswith("Privacy"):
        render_privacy()
    else:
        render_terms()
