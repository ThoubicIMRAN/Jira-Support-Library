"""Jira Support Library — application entry point.

Responsibilities:
  - one-time bootstrap (schema, bootstrap admin, seed data)
  - session validation and cookie restore
  - theme tokens (assets/styles.css + per-user preference tokens)
  - top bar, sidebar, page dispatch with RBAC guard and error boundary

All navigation goes through ``utils.navigation.goto``.
"""

from __future__ import annotations

import hmac
import html
import logging
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402

from auth import allowed, ensure_superadmin  # noqa: E402
from components.cards import initials  # noqa: E402
from config import APP_NAME, HEALTH_TOKEN  # noqa: E402
from database import Category, Project, SessionLocal, User, init_db  # noqa: E402
from seed_data import seed_if_empty  # noqa: E402
from services.avatar_service import get_avatar_data_uri  # noqa: E402
from services.cookie_service import delete_session_cookie, get_session_cookie  # noqa: E402
from services.notification_service import unread_count  # noqa: E402
from services.preference_service import (
    DEFAULTS,
    get_preferences,
    preference_css,
    save_preferences,
)  # noqa: E402
from services.session_service import revoke_session, validate_session  # noqa: E402
from utils.logging_config import configure_logging, new_correlation_id  # noqa: E402
from utils.navigation import (  # noqa: E402
    PAGE_ADMIN,
    PAGE_ADMIN_SETTINGS,
    PAGE_AI,
    PAGE_DASHBOARD,
    PAGE_HEALTH,
    PAGE_HOME,
    PAGE_NOTIFICATIONS,
    PAGE_PROFILE,
    PAGE_PROJECT,
    PAGE_SECURITY_ADMIN,
    PAGE_SETTINGS,
    PAGE_SUPPORT,
    PAGE_WHATS_NEW,
    PAGE_WORKSPACE,
    goto,
)
from views import (  # noqa: E402
    admin_panel,
    admin_settings,
    ai_assistant,
    change_password,
    health,
    home,
    login,
    my_dashboard,
    notifications,
    profile,
    project_view,
    security_admin,
    settings,
    support,  # noqa: F401
    whats_new,
    workspace,
)

logger = logging.getLogger(__name__)

st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
configure_logging()
st.session_state.setdefault("correlation_id", new_correlation_id())

PAGE_RENDERERS = {
    PAGE_HOME: home.render,
    PAGE_PROJECT: project_view.render,
    PAGE_PROFILE: profile.render,
    PAGE_SETTINGS: settings.render,
    PAGE_WORKSPACE: workspace.render,
    PAGE_NOTIFICATIONS: notifications.render,
    PAGE_ADMIN: admin_panel.render,
    PAGE_SECURITY_ADMIN: security_admin.render,
    PAGE_AI: ai_assistant.render,
    PAGE_ADMIN_SETTINGS: admin_settings.render,
    PAGE_HEALTH: health.render,
    PAGE_DASHBOARD: my_dashboard.render,
    PAGE_WHATS_NEW: whats_new.render,
    PAGE_SUPPORT: support.render,
}

BREADCRUMB_LABELS = {
    PAGE_PROJECT: "Project",
    PAGE_PROFILE: "Profile",
    PAGE_WORKSPACE: "Workspace",
    PAGE_NOTIFICATIONS: "Notifications",
    PAGE_SETTINGS: "Settings",
    PAGE_ADMIN: "Administration",
    PAGE_SECURITY_ADMIN: "Security & Messaging",
    PAGE_AI: "AI Assistant",
    PAGE_ADMIN_SETTINGS: "Admin Settings",
    PAGE_HEALTH: "Health",
    PAGE_DASHBOARD: "My Dashboard",
    PAGE_WHATS_NEW: "What's New",
    PAGE_SUPPORT: "Support",
}


def _can_open(role: str, page: str) -> bool:
    if page in (PAGE_ADMIN, PAGE_ADMIN_SETTINGS):
        return allowed(role, "manage_content")
    if page == PAGE_SECURITY_ADMIN:
        return allowed(role, "manage_security")
    return True


STYLESHEET = APP_DIR / "assets" / "styles.css"


def _inject_tokens(preferences) -> None:
    st.html(preference_css(preferences))


if STYLESHEET.exists():
    st.html(STYLESHEET)
_inject_tokens(DEFAULTS)


@st.cache_resource(show_spinner=False)
def _bootstrap_once() -> bool:
    init_db()
    ensure_superadmin()
    seed_if_empty()
    return True


try:
    _bootstrap_once()
except Exception:  # noqa: BLE001
    logger.exception("Application bootstrap failed")
    st.error("The application could not start. Please contact your administrator.")
    st.stop()

_health_param = st.query_params.get("health")
if (
    HEALTH_TOKEN
    and _health_param
    and hmac.compare_digest(str(_health_param), HEALTH_TOKEN)
):
    health.render()
    st.stop()

st.session_state.setdefault("page", PAGE_HOME)


def _load_user(user_id: int) -> User | None:
    with SessionLocal() as db:
        return db.get(User, user_id)


def _force_login(message: str) -> None:
    delete_session_cookie()
    st.session_state.clear()
    st.warning(message)
    login.render()
    st.stop()


def _resolve_user() -> User | None:
    if "session_token" not in st.session_state:
        cookie_token = get_session_cookie()
        if cookie_token:
            st.session_state.session_token = cookie_token

    token = st.session_state.get("session_token")
    known_id = st.session_state.get("user_id")

    if known_id:
        if validate_session(token) != known_id:
            _force_login("Your session expired or was revoked.")
    elif token:
        known_id = validate_session(token)
        if known_id is None:
            _force_login("Your saved session has expired. Please sign in again.")
        st.session_state.user_id = known_id
    else:
        return None

    st.session_state.last_activity = time.time()
    return _load_user(known_id)


user = _resolve_user()
if not user or not user.is_active:
    login.render()
    st.stop()

if user.must_change_password:
    change_password.render(user)
    st.stop()

preferences = st.session_state.get("user_preferences") or get_preferences(user.id)
st.session_state.user_preferences = preferences
_inject_tokens(preferences)


def _sign_out() -> None:
    revoke_session(st.session_state.get("session_token"))
    delete_session_cookie()
    st.session_state.clear()
    st.rerun()


def _toggle_theme() -> None:
    prefs = dict(st.session_state.user_preferences)
    prefs["theme"] = "light" if prefs.get("theme") == "dark" else "dark"
    try:
        st.session_state.user_preferences = save_preferences(user.id, prefs)
    except Exception:  # noqa: BLE001
        st.error("Could not save the theme preference.")
        return
    st.rerun()


def _safe_unread() -> int:
    try:
        return unread_count(user.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not compute unread notifications")
        return 0


page = st.session_state.get("page", PAGE_HOME)
if page not in PAGE_RENDERERS or not _can_open(user.role, page):
    page = PAGE_HOME
    st.session_state.page = page
unread = _safe_unread()
is_admin_area = allowed(user.role, "manage_content")


def _crumb_label() -> str:
    if page == PAGE_PROJECT and st.session_state.get("project_id") is not None:
        try:
            with SessionLocal() as db:
                project = db.get(Project, st.session_state["project_id"])
            if project and project.name:
                return project.name
        except Exception:  # noqa: BLE001
            logger.exception("Could not load project name for breadcrumb")
    return BREADCRUMB_LABELS.get(page, "")


def _on_search_change() -> None:
    st.session_state["_search_to_home"] = True


def _render_breadcrumb() -> None:
    with st.container(key="crumbs"):
        if page == PAGE_HOME:
            st.markdown(
                '<span class="jsl-crumb-now">Home</span>', unsafe_allow_html=True
            )
            return
        if st.button("Home", key="crumb_home", type="tertiary", icon=":material/home:"):
            goto(PAGE_HOME, clear_project=True)
        label = html.escape(_crumb_label())
        st.markdown(
            f'<span class="jsl-crumb-sep">/</span><span class="jsl-crumb-now" title="{label}">{label}</span>',
            unsafe_allow_html=True,
        )


def _account_header_html(name: str, contact: str, role: str, src: str | None) -> str:
    if src:
        avatar = f'<img class="jsl-acct-avatar" src="{html.escape(src, quote=True)}" alt="Profile photo of {html.escape(name)}" />'
    else:
        avatar = f'<div class="jsl-acct-avatar jsl-acct-avatar-fb">{html.escape(initials(name))}</div>'
    return (
        f'<div class="jsl-acct-head">{avatar}<div class="jsl-acct-name">{html.escape(name)}</div>'
        f'<div class="jsl-acct-mail">{html.escape(contact)}</div><div class="jsl-acct-role">{html.escape(role)}</div></div>'
    )


def _topbar_dynamic_css(src: str | None, unread_count_: int) -> str:
    """Only the per-user bits (photo, badge count) are generated; all styling is in assets/styles.css."""
    rules = []
    if src:  # data URIs are base64, so they cannot break out of url("...")
        rules.append(
            f'.st-key-top_account [data-testid="stPopover"] button {{ background-image: url("{src}") !important; color: transparent; font-size: 0; }}'
        )
    if unread_count_:
        badge = "9+" if unread_count_ > 9 else str(unread_count_)
        rules.append(f'.st-key-top_notifications::after {{ content: "{badge}"; }}')
    return "<style>" + "".join(rules) + "</style>" if rules else ""


def _render_top_bar() -> None:
    name = user.full_name or user.username or "User"
    contact = getattr(user, "email", None) or user.username or ""
    src = get_avatar_data_uri(user.id)
    css = _topbar_dynamic_css(src, unread)
    if css:
        st.html(css)
    with st.container(key="topbar"):
        left, centre, c_bell, c_user = st.columns(
            [1.3, 2.2, 0.16, 0.16], gap="small", vertical_alignment="center"
        )
        with left:
            _render_breadcrumb()
        with centre:
            st.text_input(
                "Search libraries",
                key="global_search",
                placeholder="Search libraries",
                label_visibility="collapsed",
                icon=":material/search:",
                on_change=_on_search_change,
            )
        with c_bell:
            if st.button(
                "",
                key="top_notifications",
                icon=":material/notifications:",
                help=f"Notifications ({unread} unread)" if unread else "Notifications",
            ):
                goto(PAGE_NOTIFICATIONS)
        with c_user:
            with st.container(key="top_account"):
                # With a photo the label is the name (hidden visually, kept for screen readers).
                with st.popover(name if src else initials(name), width="content"):
                    st.markdown(
                        _account_header_html(name, contact, user.role.title(), src),
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "Profile",
                        key="nav_profile",
                        icon=":material/person:",
                        width="stretch",
                    ):
                        goto(PAGE_PROFILE)
                    if st.button(
                        "Personal settings",
                        key="nav_settings",
                        icon=":material/settings:",
                        width="stretch",
                    ):
                        goto(PAGE_SETTINGS)
                    if st.button(
                        "Sign out",
                        key="nav_signout",
                        icon=":material/logout:",
                        width="stretch",
                    ):
                        _sign_out()

    # Searching from any other screen jumps to the library list, where the filter applies.
    if (
        st.session_state.pop("_search_to_home", False)
        and page != PAGE_HOME
        and st.session_state.get("global_search")
    ):
        goto(PAGE_HOME, clear_project=True)


_render_top_bar()


def _nav_button(
    label: str, target: str, key: str, icon: str | None = None, **goto_kwargs
) -> None:
    active = page == target
    if st.button(
        label,
        key=key,
        icon=icon,
        width="stretch",
        type="primary" if active else "tertiary",
    ):
        goto(target, **goto_kwargs)


def _render_project_categories() -> None:
    project_id = st.session_state.get("project_id")
    if project_id is None:
        return
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        categories = (
            db.scalars(
                select(Category)
                .where(Category.project_id == project_id)
                .order_by(Category.sort_order, Category.id)
            ).all()
            if project and not project.is_deleted
            else []
        )
    if not categories:
        return
    st.markdown(
        f'<div class="jsl-sb-label">{project.name}</div>', unsafe_allow_html=True
    )
    active_filter = st.session_state.get("category_filter")
    if st.button(
        "All categories",
        key="sbcat_all",
        icon=":material/list:",
        width="stretch",
        type="primary" if not active_filter else "tertiary",
    ):
        st.session_state.pop("category_filter", None)
        st.rerun()
    for cat in categories:
        if st.button(
            cat.name,
            key=f"sbcat_{cat.id}",
            width="stretch",
            type="primary" if active_filter == cat.id else "tertiary",
        ):
            st.session_state.category_filter = cat.id
            st.rerun()


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="jsl-sb-brand"><div class="jsl-brand-logo">🎯</div><div>'
            f'<div class="jsl-sb-title">{APP_NAME}</div><div class="jsl-sb-sub">IT Operations · Enterprise Support Platform</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="jsl-sb-label">Command library (Jira)</div>',
            unsafe_allow_html=True,
        )
        _nav_button(
            "Home", PAGE_HOME, "nav_home", ":material/home:", clear_project=True
        )
        _nav_button("My Workspace", PAGE_WORKSPACE, "nav_workspace", ":material/star:")
        _nav_button(
            "My Dashboard",
            PAGE_DASHBOARD,
            "nav_dashboard",
            ":material/dashboard:",
            clear_project=True,
        )
        _nav_button(
            "What's New",
            PAGE_WHATS_NEW,
            "nav_whats_new",
            ":material/new_releases:",
            clear_project=True,
        )
        _nav_button("AI Assistant", PAGE_AI, "nav_ai", ":material/smart_toy:")
        st.markdown('<div class="jsl-sb-label">Workspace</div>', unsafe_allow_html=True)
        _nav_button("Support", PAGE_SUPPORT, "nav_support", ":material/support_agent:")
        _nav_button(
            f"Notifications ({unread})" if unread else "Notifications",
            PAGE_NOTIFICATIONS,
            "nav_notifications",
            ":material/notifications:",
        )

        if page == PAGE_PROJECT:
            _render_project_categories()

        st.divider()
        is_dark = preferences.get("theme") == "dark"
        if st.button(
            "Light mode" if is_dark else "Dark mode",
            key="quick_theme_toggle",
            icon=":material/light_mode:" if is_dark else ":material/dark_mode:",
            width="stretch",
            type="tertiary",
        ):
            _toggle_theme()
        if is_admin_area:
            _nav_button(
                "Admin Settings",
                PAGE_ADMIN_SETTINGS,
                "nav_admin_settings",
                ":material/settings:",
            )
            if allowed(user.role, "view_health"):
                _nav_button(
                    "Health", PAGE_HEALTH, "nav_health", ":material/monitor_heart:"
                )


try:
    from services.comms_service import active_maintenance

    _m = active_maintenance()
    if _m:
        st.warning(f"**Maintenance:** {_m['title']} — {_m['message']}")
except Exception:  # noqa: BLE001
    logger.exception("Could not load maintenance banner")

_render_sidebar()

try:
    PAGE_RENDERERS[page](user)
except Exception:  # noqa: BLE001
    logger.exception("Unhandled error while rendering page %s", page)
    st.error(
        "Something went wrong while loading this page. "
        "Please try again or contact your administrator."
    )
    st.caption(f"Reference: {st.session_state.get('correlation_id', 'n/a')}")
    if st.button("← Back to Home", key="error_home"):
        goto(PAGE_HOME, clear_project=True)
