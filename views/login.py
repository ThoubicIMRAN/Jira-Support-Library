"""Sign-in, sign-up, password reset, and invitation acceptance."""
from __future__ import annotations

import logging
import time

import streamlit as st

from components.cards import page_header

from auth import authenticate
from oauth_service import (
    OAuthError,
    configured,
    finish_google,
    finish_microsoft,
    start_google,
    start_microsoft,
)
from services.account_service import (
    accept_invitation,
    consume_reset_token,
    register_user,
    request_password_reset,
    validate_invitation,
    validate_reset_token,
)
from services.cookie_service import set_session_cookie
from services.session_service import create_session
from utils.validators import valid_password

logger = logging.getLogger(__name__)


def _complete_login(user, auth_method: str = "local") -> None:
    token = create_session(user.id, auth_method)
    st.session_state.user_id = user.id
    st.session_state.session_token = token
    st.session_state.page = "home"
    st.session_state.last_activity = time.time()
    try:
        set_session_cookie(token)
    except Exception:
        logger.exception("Failed to set session cookie (continuing with session state)")
    for key in ("code", "state", "session_state", "error", "error_description"):
        st.query_params.pop(key, None)
    # Full browser reload so the newly written cookie is present on the next
    # HTTP/WebSocket request (st.context.cookies). st.rerun() alone is not enough.
    import streamlit.components.v1 as components
    components.html(
        """<script>
        setTimeout(function(){ window.parent.location.reload(); }, 150);
        </script>""",
        height=0,
        width=0,
    )
    st.stop()


def _oauth_callback() -> bool:
    if not st.query_params.get("code") and not st.query_params.get("error"):
        return False
    provider = st.session_state.get("oauth_provider")
    try:
        if provider == "microsoft":
            user = finish_microsoft(st.query_params, st.session_state)
        elif provider == "google":
            user = finish_google(st.query_params, st.session_state)
        else:
            raise OAuthError("OAuth session was not found. Start sign-in again.")
        _complete_login(user, provider or "oauth")
    except OAuthError:
        logger.exception("OAuth callback failed for provider %s", provider)
        st.error("Sign-in failed. Please try again.")
        for key in ("code", "state", "session_state", "error", "error_description"):
            st.query_params.pop(key, None)
    return True


def reset_screen(token: str) -> None:
    page_header("🔐 Set a new password")
    if not validate_reset_token(token):
        st.error("This reset link is invalid or expired.")
        return
    with st.form("reset_password"):
        password = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        save = st.form_submit_button("Update password", type="primary", width="stretch")
    if save:
        if not valid_password(password):
            st.error("Password must contain at least 8 characters.")
        elif password != confirm:
            st.error("Passwords do not match.")
        else:
            prefill = ""
            try:
                from services.account_reset_helper import username_for_reset_token
                prefill = username_for_reset_token(token) or ""
            except Exception:
                prefill = ""
            if consume_reset_token(token, password):
                st.session_state["login_prefill_username"] = prefill
                st.session_state["login_flash"] = "Password updated. Please sign in."
                st.query_params.clear()
                st.rerun()
            else:
                st.error("The reset link is invalid or has already been used.")



def invitation_screen(token: str) -> None:
    invitation = validate_invitation(token)
    if not invitation:
        st.error("This invitation is invalid or expired.")
        return
    page_header("📨 Accept invitation")
    st.info(f"Invited email: {invitation['email']} · Role: {invitation['role']}")
    with st.form("accept_invitation"):
        username = st.text_input("Username")
        full_name = st.text_input("Full name")
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        save = st.form_submit_button("Create account", type="primary", width="stretch")
    if save:
        if not username.strip() or not full_name.strip():
            st.error("Username and full name are required.")
        elif not valid_password(password):
            st.error("Password must contain at least 8 characters.")
        elif password != confirm:
            st.error("Passwords do not match.")
        else:
            if accept_invitation(token, username.strip(), full_name.strip(), password):
                st.session_state["login_prefill_username"] = username.strip()
                st.session_state["login_flash"] = "Account activated. Please sign in."
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Could not accept invitation. It may already have been used.")



def _render_sign_in() -> None:
    with st.form("login"):
        username = st.text_input("Username", placeholder="Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign in", width="stretch", type="primary")
    if submit:
        user, error = authenticate(username, password)
        if user:
            _complete_login(user, "local")
        else:
            st.error(error or "Invalid credentials.")

    st.markdown("---")
    st.caption("Single sign-on")
    try:
        if configured("microsoft"):
            st.link_button(
                "🔑 Sign in with Microsoft",
                start_microsoft(st.session_state),
                width="stretch",
                type="primary",
            )
        else:
            st.button(
                "🔑 Sign in with Microsoft",
                disabled=True,
                width="stretch",
                help="Configure MS_CLIENT_ID, MS_CLIENT_SECRET and MS_REDIRECT_URI.",
            )
        if configured("google"):
            st.link_button(
                "🅖 Sign in with Google",
                start_google(st.session_state),
                width="stretch",
            )
        else:
            st.button(
                "🅖 Sign in with Google",
                disabled=True,
                width="stretch",
                help="Configure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI.",
            )
    except OAuthError:
        logger.exception("OAuth provider setup failed during login")
        st.error("Single sign-on is unavailable. Please try again later.")


def _render_sign_up() -> None:
    st.subheader("Create an account")
    st.caption("Registers a standard **user** account. An admin can change your role later.")
    with st.form("signup_form"):
        su_username = st.text_input("Username *")
        su_full_name = st.text_input("Full name *")
        su_email = st.text_input("Email (optional)")
        su_designation = st.text_input("Designation", value="Support Engineer")
        su_password = st.text_input("Password *", type="password")
        su_confirm = st.text_input("Confirm password *", type="password")
        su_submit = st.form_submit_button(
            "Create account", width="stretch", type="primary"
        )
    if su_submit:
        if not su_username.strip() or not su_full_name.strip():
            st.error("Username and full name are required.")
        elif not valid_password(su_password):
            st.error("Password must contain at least 8 characters.")
        elif su_password != su_confirm:
            st.error("Passwords do not match.")
        else:
            try:
                register_user(
                    su_username,
                    su_full_name,
                    su_email,
                    su_password,
                    su_designation,
                )
                st.success("Account created. Switch to **Sign in** and log in.")
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                logger.exception("Registration failed")
                st.error("Registration failed. Please try again.")


def _render_forgot() -> None:
    with st.form("forgot_password"):
        identity = st.text_input("Username or email")
        send = st.form_submit_button("Send reset link", width="stretch")
    if send:
        request_password_reset(identity.strip())
        st.info(
            "If an account exists for that identity, a reset link was sent "
            "(or logged, if email is not configured)."
        )


def render() -> None:
    reset = st.query_params.get("reset_token")
    invite = st.query_params.get("invite_token")
    if reset:
        reset_screen(reset)
        return
    if invite:
        invitation_screen(invite)
        return
    if _oauth_callback():
        return

    st.markdown(
        '<div class="jsl-hero"><div class="jsl-hero-tag">IT Operations</div>'
        "<h1>Jira Support Library</h1>"
        "<p>Your team's reusable Jira comment library — sign in to continue.</p></div>",
        unsafe_allow_html=True,
    )

    _, col, _ = st.columns([1, 1.35, 1])
    with col, st.container(key="login_card"):
        # Radio is more visible than tabs in custom dark themes
        mode = st.radio(
            "Account",
            ["Sign in", "Sign up", "Forgot password"],
            horizontal=True,
            label_visibility="collapsed",
            key="login_mode",
        )

        if mode == "Sign in":
            _render_sign_in()
            st.markdown("---")
            st.info("New here? Choose **Sign up** above to create an account.")
        elif mode == "Sign up":
            _render_sign_up()
        else:
            _render_forgot()
