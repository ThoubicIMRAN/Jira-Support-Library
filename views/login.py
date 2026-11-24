"""Sign-in, password reset, invitation & account creation – polished Atlassian style."""

from __future__ import annotations

import logging
import secrets
import time

import streamlit as st
import streamlit.components.v1 as components

from auth import authenticate
from components.cards import page_header
from components.passkey_flow import passkey_flow
from oauth_service import (
    OAuthError,
    configured,
    finish_google,
    finish_microsoft,
    start_google,
    start_microsoft,
)
from config import ALLOW_SELF_REGISTRATION
from services.account_service import (
    accept_invitation,
    consume_reset_token,
    register_user,
    request_password_reset,
    validate_invitation,
    validate_reset_token,
)
from services.cookie_service import set_session_cookie
from services.rate_limit import RateLimitExceeded, limit_signup
from services.security_policy import email_allowed
from utils.errors import safe_message
from services.passkey_service import (
    ORIGIN as PASSKEY_ORIGIN,
)
from services.passkey_service import (
    WEBAUTHN_ENABLED,
    finish_authentication,
    start_authentication,
)
from services.session_service import create_session
from utils.validators import valid_password

logger = logging.getLogger(__name__)
PASSKEY_LOGIN_PENDING = "login_passkey_authentication"
PASSKEY_CHALLENGE_TTL = 300


# ── CSS ───────────────────────────────────────────────────────────────────────
def inject_auth_css() -> None:
    st.markdown(
        """
    <style>
    #MainMenu, footer, header {visibility: hidden;}
    .stApp { background: #f4f5f7; }

    .block-container {
        max-width: 420px !important;
        padding-top: 2.8rem !important;
        padding-bottom: 2rem !important;
    }

    .jsl-brand { text-align: center; margin-bottom: 1.4rem; }
    .jsl-logo {
        width: 46px; height: 46px; border-radius: 10px;
        background: #0c46ce; display: inline-flex;
        align-items: center; justify-content: center;
        font-size: 1.45rem; color: white; margin-bottom: 0.55rem;
        box-shadow: 0 4px 14px rgba(12,70,206,0.28);
    }
    .jsl-title {
        font-size: 1.3rem; font-weight: 700; color: #172b4d;
        letter-spacing: -0.02em; margin: 0;
    }
    .jsl-subtitle {
        font-size: 1.05rem; font-weight: 600; color: #172b4d;
        margin: 1.3rem 0 1rem;
    }

    .stForm {
        background: white; border-radius: 8px;
        padding: 1.45rem 1.55rem 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 8px 24px rgba(0,0,0,0.06);
        border: 1px solid #dfe1e6;
    }

    .stTextInput > div > div > input {
        border-radius: 6px !important; border: 1.5px solid #dfe1e6 !important;
        height: 42px !important; font-size: 0.95rem !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: #0c46ce !important;
        box-shadow: 0 0 0 2px rgba(12,70,206,0.2) !important;
    }

    div[data-testid="stFormSubmitButton"] > button {
        background: #0c46ce !important; color: white !important;
        border: none !important; border-radius: 6px !important;
        height: 44px !important; font-weight: 600 !important;
        font-size: 0.95rem !important;
    }
    div[data-testid="stFormSubmitButton"] > button:hover {
        background: #0939a8 !important;
    }

    .stButton > button, .stLinkButton > a {
        border: 1.5px solid #dfe1e6 !important; border-radius: 6px !important;
        height: 42px !important; background: white !important;
        color: #172b4d !important; font-weight: 500 !important;
        width: 100% !important;
    }
    .stButton > button:hover, .stLinkButton > a:hover {
        background: #f4f5f7 !important; border-color: #b3bac5 !important;
    }

    .jsl-section-label {
        text-align: center; color: #6b778c; font-size: 0.85rem;
        font-weight: 500; margin: 1.35rem 0 0.65rem;
    }

    .jsl-bottom-links {
        text-align: center; margin: 1.25rem 0 0.4rem; font-size: 0.875rem;
    }
    .jsl-bottom-links a {
        color: #0c46ce; text-decoration: none; font-weight: 500;
    }
    .jsl-bottom-links a:hover { text-decoration: underline; }
    .jsl-dot { color: #6b778c; margin: 0 0.35rem; }

    .jsl-footer {
        text-align: center; margin-top: 2.3rem; padding-top: 1.15rem;
        border-top: 1px solid #dfe1e6; font-size: 0.8rem; color: #6b778c;
    }
    .jsl-footer a { color: #6b778c; text-decoration: none; }
    .jsl-footer a:hover { color: #0c46ce; text-decoration: underline; }
    .jsl-footer-brand { font-weight: 600; color: #172b4d; margin-bottom: 0.3rem; }
    </style>
    """,
        unsafe_allow_html=True,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _complete_login(user, auth_method: str = "local") -> None:
    st.session_state.pop(PASSKEY_LOGIN_PENDING, None)
    remember = bool(st.session_state.pop("remember_me", False))
    token = create_session(user.id, auth_method, remember=remember)
    st.session_state.user_id = user.id
    st.session_state.session_token = token
    st.session_state.page = "home"
    st.session_state.last_activity = time.time()

    # Clean up any expired-session flags
    keys_to_remove = [
        k
        for k in st.session_state.keys()
        if "expired" in k.lower() or (k.startswith("session") and k != "session_token")
    ]
    for k in keys_to_remove:
        del st.session_state[k]

    try:
        set_session_cookie(token, remember=remember)
    except Exception:
        logger.exception("Failed to set session cookie")

    for key in ("code", "state", "session_state", "error", "error_description"):
        st.query_params.pop(key, None)

    components.html(
        """<script>
        setTimeout(function(){ window.parent.location.reload(); }, 120);
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
        logger.exception("OAuth callback failed")
        st.error("Sign-in failed. Please try again.")
        for key in ("code", "state", "session_state", "error", "error_description"):
            st.query_params.pop(key, None)
    return True


# ── Reset Password Screen ─────────────────────────────────────────────────────


def reset_screen(token: str) -> None:
    page_header("Set a new password")
    if not validate_reset_token(token):
        st.error("This reset link is invalid or has expired.")
        st.markdown(
            '<div class="jsl-bottom-links"><a href="?mode=signin">← Back to sign in</a></div>',
            unsafe_allow_html=True,
        )
        return

    with st.form("reset_password"):
        password = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        save = st.form_submit_button(
            "Update password", type="primary", use_container_width=True
        )

    if save:
        if not valid_password(password):
            st.error("Password must be at least 8 characters.")
        elif password != confirm:
            st.error("Passwords do not match.")
        else:
            user = consume_reset_token(token, password)
            if user:
                st.success("Password updated successfully. Signing you in…")
                time.sleep(0.7)
                _complete_login(user, "local")
            else:
                st.error("This reset link is invalid or has already been used.")


# ── Invitation Screen ─────────────────────────────────────────────────────────


def invitation_screen(token: str) -> None:
    invitation = validate_invitation(token)
    if not invitation:
        st.error("This invitation is invalid or expired.")
        return

    page_header("Accept invitation")
    st.info(f"Invited email: **{invitation['email']}** · Role: {invitation['role']}")

    with st.form("accept_invitation"):
        username = st.text_input("Username")
        full_name = st.text_input("Full name")
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        save = st.form_submit_button(
            "Create account", type="primary", use_container_width=True
        )

    if save:
        if not username.strip() or not full_name.strip():
            st.error("Username and full name are required.")
        elif not valid_password(password):
            st.error("Password must be at least 8 characters.")
        elif password != confirm:
            st.error("Passwords do not match.")
        else:
            user = accept_invitation(
                token, username.strip(), full_name.strip(), password
            )
            if user:
                st.success("Account created. Signing you in…")
                time.sleep(0.6)
                _complete_login(user, "local")
            else:
                st.error("Could not accept invitation.")


# ── Create Account Screen ─────────────────────────────────────────────────────


def create_account_screen() -> None:
    if not ALLOW_SELF_REGISTRATION:
        st.info("Self-registration is turned off. Ask an administrator for an invitation.")
        st.markdown('<div class="jsl-bottom-links"><a href="?mode=signin">Back to sign in</a></div>', unsafe_allow_html=True)
        return

    st.markdown('<div class="jsl-subtitle">Create an account</div>', unsafe_allow_html=True)
    st.caption("Creates a standard user account. An administrator must give it access to project libraries.")

    with st.form("create_account"):
        email = st.text_input("Email *", placeholder="you@company.com")
        full_name = st.text_input("Full name *")
        password = st.text_input("Password *", type="password")
        confirm = st.text_input("Confirm password *", type="password")
        submit = st.form_submit_button("Create account", type="primary", use_container_width=True)

    if submit:
        address = email.strip().lower()
        if not address or not full_name.strip():
            st.error("Email and full name are required.")
        elif not email_allowed(address):
            st.error("That email domain is not allowed.")
        elif not valid_password(password):
            st.error("Password must be at least 8 characters.")
        elif password != confirm:
            st.error("Passwords do not match.")
        else:
            try:
                limit_signup()
                register_user(address, full_name.strip(), address, password)
            except RateLimitExceeded as exc:
                st.error(safe_message(exc))
            except ValueError as exc:
                st.error(safe_message(exc))
            except Exception:  # noqa: BLE001
                logger.exception("Registration failed")
                st.error("Registration failed. Please try again.")
            else:
                user, error = authenticate(address, password)
                if user:
                    st.success("Account created. Signing you in…")
                    time.sleep(0.7)
                    _complete_login(user, "local")
                else:
                    st.success("Account created. Sign in to continue.")

    st.markdown(
        '<div class="jsl-bottom-links"><a href="?mode=signin">Already have an account? Log in</a></div>',
        unsafe_allow_html=True,
    )


# ── Forgot Password ───────────────────────────────────────────────────────────


def _render_forgot() -> None:
    st.markdown(
        '<div class="jsl-subtitle">Reset your password</div>', unsafe_allow_html=True
    )

    with st.form("forgot_password"):
        identity = st.text_input("Email or username", placeholder="you@company.com")
        send = st.form_submit_button(
            "Send reset link", type="primary", use_container_width=True
        )

    if send:
        result = request_password_reset(identity.strip())

        # Support both old and new return signatures
        if isinstance(result, tuple) and len(result) == 3:
            success, token, exists = result
        else:
            # Fallback for older version that only returns bool / None
            success = bool(result)
            token = result if isinstance(result, str) else None
            exists = success

        if not exists:
            st.error("No account found with that email or username.")
        elif success and token:
            # Redirect straight to the reset form
            st.query_params.clear()
            st.query_params["reset_token"] = token
            st.rerun()
        else:
            st.error("Unable to generate a reset link. Please try again later.")

    st.markdown(
        """
        <div class="jsl-bottom-links">
            <a href="?mode=signin">← Back to sign in</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main Sign-in ──────────────────────────────────────────────────────────────


def _render_sso_buttons() -> None:
    try:
        if configured("google"):
            st.link_button(
                "🅖  Google", start_google(st.session_state), use_container_width=True
            )
        if configured("microsoft"):
            st.link_button(
                "🪟  Microsoft",
                start_microsoft(st.session_state),
                use_container_width=True,
            )
    except OAuthError:
        logger.exception("OAuth provider setup failed")


def _render_sign_in() -> None:
    if "login_flash" in st.session_state:
        st.success(st.session_state.pop("login_flash"))

    prefill = st.session_state.pop("login_prefill_username", "")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email *", value=prefill, placeholder="Enter your email")
        password = st.text_input(
            "Password *", type="password", placeholder="Enter your password"
        )
        remember = st.checkbox(
            "Remember me", value=False, help="Stay signed in on this device"
        )
        submitted = st.form_submit_button(
            "Continue", type="primary", use_container_width=True
        )

    if submitted:
        if not email.strip() or not password:
            st.error("Please enter both email and password.")
        else:
            user, error = authenticate(email.strip(), password)
            if user:
                if remember:
                    st.session_state["remember_me"] = True
                _complete_login(user, "local")
            else:
                st.error(error or "Invalid credentials.")

    # Passkey
    st.markdown(
        '<div class="jsl-section-label">Or login with:</div>', unsafe_allow_html=True
    )
    if st.button(
        "🔑  Passkey",
        use_container_width=True,
        key="passkey_btn",
        disabled=not WEBAUTHN_ENABLED,
        help=None
        if WEBAUTHN_ENABLED
        else "Passkey sign-in is disabled by your administrator.",
    ):
        try:
            authentication = start_authentication()
        except Exception:  # noqa: BLE001
            logger.exception("Could not start passkey authentication")
            st.error("Could not start passkey sign-in. Please try again.")
        else:
            st.session_state[PASSKEY_LOGIN_PENDING] = {
                "challenge": authentication["challenge"],
                "options": authentication["options"],
                "expires_at": time.time() + PASSKEY_CHALLENGE_TTL,
                "request_id": secrets.token_urlsafe(12),
            }

    pending = st.session_state.get(PASSKEY_LOGIN_PENDING)
    if pending and pending.get("expires_at", 0) <= time.time():
        st.session_state.pop(PASSKEY_LOGIN_PENDING, None)
        st.info("Passkey sign-in expired. Select Passkey to try again.")
        pending = None
    if pending:
        result = passkey_flow(
            mode="authentication",
            options=pending["options"],
            expected_origin=PASSKEY_ORIGIN,
            key=f"login_passkey_authentication_{pending['request_id']}",
        )
        if result is not None:
            pending = st.session_state.pop(PASSKEY_LOGIN_PENDING, None)
            if not isinstance(result, dict) or pending is None:
                st.error("Passkey sign-in could not be completed. Please try again.")
            else:
                try:
                    user = finish_authentication(result, pending["challenge"])
                except Exception:  # noqa: BLE001
                    logger.exception("Could not complete passkey authentication")
                    st.error("Could not verify the passkey. Please try again.")
                else:
                    if user is not None and user.is_active:
                        _complete_login(user, "passkey")
                    else:
                        st.error(
                            "Passkey sign-in failed. Check your authenticator and try again."
                        )

    # SSO
    if configured("google") or configured("microsoft"):
        st.markdown(
            '<div class="jsl-section-label">Or continue with:</div>',
            unsafe_allow_html=True,
        )
        _render_sso_buttons()

    # Bottom links
    signup_link = '<span class="jsl-dot">•</span><a href="?mode=signup">Create an account</a>' if ALLOW_SELF_REGISTRATION else ""
    st.markdown(
        f'<div class="jsl-bottom-links"><a href="?mode=forgot">Can\'t log in?</a>{signup_link}</div>',
        unsafe_allow_html=True,
    )


# ── Entry Point ───────────────────────────────────────────────────────────────


def render() -> None:
    inject_auth_css()

    # Clear any leftover session-expired flags
    for key in list(st.session_state.keys()):
        if "expired" in key.lower() or key == "session_expired_shown":
            del st.session_state[key]

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

    _, center, _ = st.columns([1, 1.15, 1])

    with center:
        st.markdown(
            """
            <div class="jsl-brand">
                <div class="jsl-logo">🛠</div>
                <div class="jsl-title">Jira Support Library</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        mode = st.query_params.get("mode", "signin")

        if mode == "forgot":
            _render_forgot()
        elif mode == "signup":
            create_account_screen()
        else:
            st.markdown(
                '<div class="jsl-subtitle">Log in to continue</div>',
                unsafe_allow_html=True,
            )
            _render_sign_in()

        # Footer – Privacy Policy & User Notice only
        st.markdown(
            """
            <div class="jsl-footer">
                <div class="jsl-footer-brand">Jira Support Library</div>
                <a href="https://github.com/ThoubicIMRAN/Jira-Support-Library/blob/main/docs/PRIVACY_POLICY.md" target="_blank">Privacy Policy</a>
                &nbsp;•&nbsp;
                <a href="https://github.com/ThoubicIMRAN/Jira-Support-Library/blob/main/docs/USER_NOTICE.md" target="_blank">User Notice</a>
            </div>
            """,
            unsafe_allow_html=True,
        )
