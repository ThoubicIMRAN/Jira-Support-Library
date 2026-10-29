"""User profile page.

Renders the profile form (name, designation, password, per-project
designation overrides) and the OAuth identity manager.

Public API:
    render(user)                   -> profile form + linked identities
    render_profile_form(user)      -> just the profile form
    render_linked_identities(user) -> just the OAuth section
"""
from __future__ import annotations

import streamlit as st

from config import APP_NAME, APP_VERSION

from components.cards import page_header
from sqlalchemy import select

from auth import hash_password
from database import (
    Project,
    SessionLocal,
    User,
    UserAuthIdentity,
    UserProjectDesignation,
)
from oauth_service import OAuthError, configured, start_google, start_microsoft
from utils.validators import valid_password


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


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def _save_profile(
    user_id: int,
    name: str,
    designation: str,
    new_password: str | None,
    project_values: dict[int, str],
) -> None:
    """Persist the profile form. Raises ValueError on validation problems."""
    clean_name = (name or "").strip()
    clean_designation = (designation or "").strip()

    if new_password and not valid_password(new_password):
        raise ValueError(
            f"Password must contain at least {PASSWORD_MIN_LENGTH} characters."
        )

    with SessionLocal() as db:
        u = db.get(User, user_id)
        if u is None:
            raise ValueError("User no longer exists.")

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


# --------------------------------------------------------------------------- #
# Flash helper
# --------------------------------------------------------------------------- #
def _render_flash() -> None:
    flash = st.session_state.pop(SESSION_FLASH, None)
    if flash:
        st.success(flash)


def _set_flash(message: str) -> None:
    st.session_state[SESSION_FLASH] = message


# --------------------------------------------------------------------------- #
# Profile form
# --------------------------------------------------------------------------- #
def render_profile_form(user) -> None:
    import streamlit as st
    from services.avatar_service import (
        set_avatar, clear_avatar, render_avatar_image, get_avatar, AvatarError, MAX_BYTES,
    )
    from database import SessionLocal, User as _User

    # Always re-read avatar from DB (session user object can be stale)
    fresh = None
    try:
        with SessionLocal() as db:
            fresh = db.get(_User, user.id)
    except Exception:
        fresh = user
    display_user = fresh or user

    st.subheader("Profile photo")
    st.caption(f"PNG, JPEG or WebP · max {MAX_BYTES // 1024} KB · stored securely in the database")
    c_av1, c_av2 = st.columns([1, 3])
    with c_av1:
        render_avatar_image(display_user, width=96)
        if get_avatar(user.id):
            st.caption("Photo on file")
        else:
            st.caption("No photo yet")
    with c_av2:
        up = st.file_uploader(
            "Choose image",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"avatar_up_{user.id}",
            label_visibility="collapsed",
        )
        b1, b2 = st.columns(2)
        if b1.button("Save photo", type="primary", key=f"avatar_save_{user.id}"):
            if not up:
                st.warning("Choose an image first.")
            else:
                try:
                    raw = up.getvalue()
                    mime = (up.type or "").strip() or "image/png"
                    if up.name and up.name.lower().endswith(".jpg"):
                        mime = mime or "image/jpeg"
                    set_avatar(user.id, raw, mime)
                    st.session_state[SESSION_FLASH] = "Profile photo updated."
                    st.rerun()
                except AvatarError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    # Surface DB/schema errors so ops can migrate
                    st.error(f"Could not save photo: {exc}")
        if b2.button("Remove photo", key=f"avatar_clr_{user.id}"):
            try:
                clear_avatar(user.id)
                st.session_state[SESSION_FLASH] = "Profile photo removed."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not remove photo: {exc}")
    st.divider()

    projects, overrides = _load_projects_and_overrides(user.id)

    with st.form("profile_form", clear_on_submit=False):
        st.subheader("Account details")

        col_name, col_desig = st.columns(2)
        name = col_name.text_input(
            "Full name",
            value=user.full_name or "",
            key="profile_full_name",
        )
        designation = col_desig.text_input(
            "Default designation",
            value=user.designation or "",
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
        st.caption(
            "Leave a field blank to fall back to your default designation."
        )

        project_values: dict[int, str] = {}
        if not projects:
            st.info("No active projects available.")
        else:
            for project in projects:
                current = (
                    overrides[project.id].designation
                    if project.id in overrides
                    else ""
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
    except ValueError:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Profile validation failed for user %s", user.id)
        st.error("Please review the profile details and try again.")
        return
    except Exception:  # noqa: BLE001
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Profile save failed for user %s", user.id)
        st.error("Could not save profile. Please try again.")
        return

    # One-shot success message that survives the rerun.
    _set_flash("Profile updated.")
    st.rerun()


# --------------------------------------------------------------------------- #
# Linked identities
# --------------------------------------------------------------------------- #
def _link_url(provider: str, user, state) -> str | None:
    """Return the OAuth start URL, or None if not configured."""
    if not configured(provider):
        return None
    if provider == "microsoft":
        return start_microsoft(state, user.id)
    if provider == "google":
        return start_google(state, user.id)
    return None


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
                logger = __import__("logging").getLogger(__name__)
                logger.exception("Could not unlink provider %s for user %s", provider, user.id)
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
    st.caption(
        "Sign in with any linked provider, or use your password if one is set."
    )

    try:
        identities = _load_identities(user.id)
    except Exception:  # noqa: BLE001
        logger = __import__("logging").getLogger(__name__)
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