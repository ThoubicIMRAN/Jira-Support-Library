"""User profile page.

Renders the profile form (name, designation, password, per-project
designation overrides) and the OAuth identity manager.

Public API:
    render(user)                   -> profile form + linked identities
    render_profile_form(user)      -> just the profile form
    render_linked_identities(user) -> just the OAuth section
"""

from __future__ import annotations

import logging
import secrets
import time

import streamlit as st
from sqlalchemy import select

from auth import hash_password
from components.cards import page_header
from components.passkey_flow import passkey_flow
from config import APP_NAME, APP_VERSION
from database import (
    Project,
    SessionLocal,
    User,
    UserAuthIdentity,
    UserProjectDesignation,
)
from oauth_service import OAuthError, configured, start_google, start_microsoft
from services.avatar_service import (
    MAX_BYTES,
    AvatarError,
    clear_avatar,
    get_avatar,
    render_avatar_image,
    set_avatar,
)
from services.passkey_service import (
    ORIGIN as PASSKEY_ORIGIN,
)
from services.passkey_service import (
    WEBAUTHN_ENABLED,
    finish_registration,
    list_passkeys,
    remove_passkey,
    start_registration,
)
from utils.errors import safe_message
from utils.validators import valid_password

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULT_DESIGNATION = "Support Engineer"
PASSWORD_MIN_LENGTH = 8

PROVIDERS: tuple[tuple[str, str], ...] = (
    ("microsoft", "Microsoft"),
    ("google", "Google"),
)

SESSION_FLASH = "profile_flash"
PASSKEY_PENDING = "profile_passkey_registration"
PASSKEY_CHALLENGE_TTL = 300


# --------------------------------------------------------------------------- #
# Data loaders
# --------------------------------------------------------------------------- #
def _load_projects_and_overrides(
    user_id: int,
) -> tuple[list[Project], dict[int, UserProjectDesignation]]:
    """Return (active projects, {project_id: override}) for the given user."""
    with SessionLocal() as db:
        projects = list(
            db.scalars(
                select(Project)
                .where(Project.is_deleted == False)  # noqa: E712
                .order_by(Project.sort_order, Project.id)
            ).all()
        )
        overrides = {
            x.project_id: x
            for x in db.scalars(
                select(UserProjectDesignation).where(
                    UserProjectDesignation.user_id == user_id
                )
            ).all()
        }
    return projects, overrides


def _load_identities(user_id: int) -> list[UserAuthIdentity]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(UserAuthIdentity)
                .where(UserAuthIdentity.user_id == user_id)
                .order_by(UserAuthIdentity.provider)
            ).all()
        )


def _load_fresh_user(user_id: int) -> User | None:
    """Re-read the user from the DB, or return None on failure."""
    try:
        with SessionLocal() as db:
            return db.get(User, user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not reload user %s", user_id)
        return None


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
class ProfileValidationError(ValueError):
    """Raised when the profile form fails client-side validation."""


def _save_profile(
    user_id: int,
    name: str,
    designation: str,
    new_password: str | None,
    project_values: dict[int, str],
) -> None:
    """Persist the profile form.

    Raises ``ProfileValidationError`` for user-facing validation problems
    and lets DB errors propagate unchanged.
    """
    clean_name = (name or "").strip()
    clean_designation = (designation or "").strip()

    if new_password and not valid_password(new_password):
        raise ProfileValidationError(
            f"Password must contain at least {PASSWORD_MIN_LENGTH} characters."
        )

    with SessionLocal() as db:
        u = db.get(User, user_id)
        if u is None:
            raise ProfileValidationError("User no longer exists.")

        if clean_name:
            u.full_name = clean_name
        u.designation = clean_designation or DEFAULT_DESIGNATION

        if new_password:
            u.password_hash = hash_password(new_password)
            u.must_change_password = False

        existing = {
            row.project_id: row
            for row in db.scalars(
                select(UserProjectDesignation).where(
                    UserProjectDesignation.user_id == user_id
                )
            ).all()
        }

        for project_id, value in project_values.items():
            cleaned = (value or "").strip()
            row = existing.get(project_id)
            if cleaned:
                if row is not None:
                    row.designation = cleaned
                else:
                    db.add(
                        UserProjectDesignation(
                            user_id=user_id,
                            project_id=project_id,
                            designation=cleaned,
                        )
                    )
            elif row is not None:
                db.delete(row)

        db.commit()


def _unlink_identity(user_id: int, provider: str) -> None:
    with SessionLocal() as db:
        row = db.scalar(
            select(UserAuthIdentity).where(
                UserAuthIdentity.user_id == user_id,
                UserAuthIdentity.provider == provider,
            )
        )
        if row is not None:
            db.delete(row)
            db.commit()


def _render_passkeys(user) -> None:
    st.subheader("Passkeys")
    if not WEBAUTHN_ENABLED:
        st.info("Passkey sign-in is disabled by your administrator.")
        return
    st.caption(
        "Add a passkey for this account. Passkey setup requires a secure HTTPS connection."
    )

    try:
        passkeys = list_passkeys(user.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load passkeys for user %s", user.id)
        st.error("Could not load passkeys. Please try again.")
        return

    label = st.text_input(
        "Passkey name",
        value=f"Passkey {len(passkeys) + 1}",
        max_chars=128,
        key=f"profile_passkey_name_{user.id}",
    )
    if st.button("Add passkey", key=f"profile_add_passkey_{user.id}", type="primary"):
        try:
            registration = start_registration(
                user.id,
                user.username,
                user.full_name or user.username,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not start passkey registration for user %s", user.id
            )
            st.error("Could not start passkey setup. Please try again.")
        else:
            st.session_state[PASSKEY_PENDING] = {
                "user_id": user.id,
                "challenge": registration["challenge"],
                "options": registration["options"],
                "device_name": (label or "").strip()[:128] or "Passkey",
                "expires_at": time.time() + PASSKEY_CHALLENGE_TTL,
                "request_id": secrets.token_urlsafe(12),
            }

    pending = st.session_state.get(PASSKEY_PENDING)
    if pending and pending.get("user_id") != user.id:
        st.session_state.pop(PASSKEY_PENDING, None)
        pending = None
    if pending and pending.get("expires_at", 0) <= time.time():
        st.session_state.pop(PASSKEY_PENDING, None)
        st.info("Passkey setup expired. Select Add passkey to try again.")
        pending = None
    if pending:
        result = passkey_flow(
            mode="registration",
            options=pending["options"],
            expected_origin=PASSKEY_ORIGIN,
            key=f"profile_passkey_registration_{pending['request_id']}",
        )
        if result is not None:
            pending = st.session_state.pop(PASSKEY_PENDING, None)
            if not isinstance(result, dict) or pending is None:
                st.error("Passkey setup could not be completed. Please try again.")
            else:
                try:
                    saved = finish_registration(
                        user.id,
                        result,
                        pending["challenge"],
                        pending["device_name"],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Could not save passkey for user %s", user.id)
                    st.error("Could not save the passkey. Please try again.")
                else:
                    if saved:
                        _set_flash("Passkey added.")
                        st.rerun()
                    else:
                        st.error("Passkey verification failed. Please try again.")

    if not passkeys:
        st.info("No passkeys are registered for this account.")
    for passkey in passkeys:
        info, action = st.columns([4, 1], vertical_alignment="center")
        info.write(passkey["name"])
        if passkey["created_at"]:
            info.caption(f"Added {passkey['created_at']:%Y-%m-%d}")
        if action.button(
            "Remove",
            key=f"profile_remove_passkey_{passkey['id']}",
            width="stretch",
        ):
            try:
                removed = remove_passkey(user.id, passkey["id"])
            except ValueError as exc:
                st.warning(safe_message(exc))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Could not remove passkey %s for user %s", passkey["id"], user.id
                )
                st.error("Could not remove the passkey. Please try again.")
            else:
                if removed:
                    _set_flash("Passkey removed.")
                    st.rerun()
                else:
                    st.error("Passkey not found. Refresh the page and try again.")


# --------------------------------------------------------------------------- #
# Flash helpers
# --------------------------------------------------------------------------- #
def _render_flash() -> None:
    flash = st.session_state.pop(SESSION_FLASH, None)
    if flash:
        st.success(flash)


def _set_flash(message: str) -> None:
    st.session_state[SESSION_FLASH] = message


# --------------------------------------------------------------------------- #
# Avatar section
# --------------------------------------------------------------------------- #
def _render_avatar_section(user) -> None:
    display_user = _load_fresh_user(user.id) or user

    st.subheader("Profile photo")
    st.caption(
        f"PNG, JPEG or WebP · max {MAX_BYTES // 1024} KB · stored securely in the database"
    )
    c_av1, c_av2 = st.columns([1, 3])
    with c_av1:
        render_avatar_image(display_user, width=96)
        st.caption("Photo on file" if get_avatar(user.id) else "No photo yet")
    with c_av2:
        up = st.file_uploader(
            "Choose image",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"avatar_up_{user.id}",
            label_visibility="collapsed",
        )
        b1, b2 = st.columns(2)
        if b1.button("Save photo", type="primary", key=f"avatar_save_{user.id}"):
            _handle_avatar_upload(up, user)
        if b2.button("Remove photo", key=f"avatar_clr_{user.id}"):
            _handle_avatar_remove(user)


def _handle_avatar_upload(up, user) -> None:
    if not up:
        st.warning("Choose an image first.")
        return
    try:
        raw = up.getvalue()
        mime = (up.type or "").strip() or "image/png"
        if (
            up.name
            and up.name.lower().endswith((".jpg", ".jpeg"))
            and mime == "image/png"
        ):
            mime = "image/jpeg"
        set_avatar(
            user.id,
            raw,
            mime,
            actor_id=user.id,
            actor_role=getattr(user, "role", None),
        )
    except AvatarError as exc:
        st.error(safe_message(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Avatar save failed for user %s", user.id)
        st.error(f"Could not save photo: {safe_message(exc)}")
    else:
        _set_flash("Profile photo updated.")
        st.rerun()


def _handle_avatar_remove(user) -> None:
    try:
        clear_avatar(
            user.id,
            actor_id=user.id,
            actor_role=getattr(user, "role", None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Avatar remove failed for user %s", user.id)
        st.error(f"Could not remove photo: {safe_message(exc)}")
    else:
        _set_flash("Profile photo removed.")
        st.rerun()


# --------------------------------------------------------------------------- #
# Profile form
# --------------------------------------------------------------------------- #
def render_profile_form(user) -> None:
    _render_avatar_section(user)
    st.divider()

    # Use the freshest copy of the user for form defaults.
    current_user = _load_fresh_user(user.id) or user
    projects, overrides = _load_projects_and_overrides(user.id)

    with st.form("profile_form", clear_on_submit=False):
        st.subheader("Account details")

        col_name, col_desig = st.columns(2)
        name = col_name.text_input(
            "Full name",
            value=current_user.full_name or "",
            key="profile_full_name",
        )
        designation = col_desig.text_input(
            "Default designation",
            value=current_user.designation or "",
            key="profile_designation",
            placeholder=DEFAULT_DESIGNATION,
        )

        new_password = st.text_input(
            "New password",
            type="password",
            key="profile_new_password",
            help=(
                "Leave blank to keep your current password. "
                f"Minimum {PASSWORD_MIN_LENGTH} characters."
            ),
        )

        st.subheader("Project-specific designations")
        st.caption("Leave a field blank to fall back to your default designation.")

        project_values: dict[int, str] = {}
        if not projects:
            st.info("No active projects available.")
        else:
            for project in projects:
                current = (
                    overrides[project.id].designation if project.id in overrides else ""
                )
                project_values[project.id] = st.text_input(
                    project.name,
                    value=current,
                    key=f"profile_project_{project.id}",
                    placeholder="Leave blank to use default",
                )

        submitted = st.form_submit_button(
            "Save changes", type="primary", width="content"
        )

    if not submitted:
        return

    try:
        _save_profile(user.id, name, designation, new_password, project_values)
    except ProfileValidationError as exc:
        logger.warning("Profile validation failed for user %s: %s", user.id, exc)
        st.error(safe_message(exc))
    except Exception:  # noqa: BLE001
        logger.exception("Profile save failed for user %s", user.id)
        st.error("Could not save profile. Please try again.")
    else:
        _set_flash("Profile updated.")
        st.rerun()


# --------------------------------------------------------------------------- #
# Linked identities
# --------------------------------------------------------------------------- #
def _link_url(provider: str, user, state) -> str | None:
    """Return the OAuth start URL, or None if the provider is not configured."""
    if not configured(provider):
        return None
    if provider == "microsoft":
        return start_microsoft(state, user.id)
    if provider == "google":
        return start_google(state, user.id)
    raise ValueError(f"Unsupported OAuth provider: {provider!r}")


def _render_linked_identity(
    provider: str,
    label: str,
    row: UserAuthIdentity | None,
    user,
    can_unlink: bool,
) -> None:
    col_info, col_action = st.columns([5, 2])

    if row is not None:
        email = row.provider_email or "No email returned"
        col_info.success(f"{label} linked · {email}")

        if col_action.button(
            "Unlink",
            key=f"unlink_{provider}",
            disabled=not can_unlink,
            width="stretch",
            help=(
                "Add a password or link another provider before "
                "unlinking your only sign-in method."
            ),
        ):
            try:
                _unlink_identity(user.id, provider)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Could not unlink provider %s for user %s", provider, user.id
                )
                st.error("Could not unlink sign-in method. Please try again.")
            else:
                _set_flash(f"{label} unlinked.")
                st.rerun()
        return

    col_info.info(f"{label} is not linked.")

    try:
        url = _link_url(provider, user, st.session_state)
    except OAuthError as exc:
        col_action.error(str(exc))
        return

    if url:
        col_action.link_button(f"Link {label}", url, width="stretch")
    else:
        col_action.button(
            f"Link {label}",
            disabled=True,
            width="stretch",
            help=f"{label} sign-in is not configured on this server.",
        )


def render_linked_identities(user) -> None:
    st.subheader("Linked sign-in methods")
    st.caption("Sign in with any linked provider, or use your password if one is set.")
    _render_passkeys(user)

    try:
        identities = _load_identities(user.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load sign-in methods for user %s", user.id)
        st.error("Could not load sign-in methods. Please try again.")
        return

    linked = {row.provider: row for row in identities}
    has_password = bool(getattr(user, "password_hash", None))
    can_unlink = has_password or len(identities) > 1

    if not can_unlink:
        st.info(
            "You have no password set and only one linked provider. "
            "Set a password or link another provider before unlinking."
        )

    for provider, label in PROVIDERS:
        _render_linked_identity(provider, label, linked.get(provider), user, can_unlink)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def render(user) -> None:
    page_header("👤 My Profile")
    st.caption(f"{APP_NAME} · v{APP_VERSION}")

    _render_flash()

    tab_profile, tab_signin = st.tabs(["Profile", "Sign-in methods"])

    with tab_profile:
        render_profile_form(user)

    with tab_signin:
        render_linked_identities(user)
