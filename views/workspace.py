"""My Workspace page.

Renders four sections — Global search, Favorites, Recently viewed, and
Saved searches — over the response library.

Data fetching is lazy per tab, all service calls are wrapped in helpers,
and layout/UX is centralised. Navigation goes through the shared
`utils.navigation.goto` contract.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import streamlit as st

from components.cards import page_header

from services.workspace_service import (
    delete_saved_search,
    designation_overrides,
    favorite_ids,
    global_search,
    project_filter_options,
    record_view,
    response_records,
    response_tag_names,
    save_search,
    saved_searches,
    toggle_favorite,
)
from utils.navigation import (
    PAGE_PROJECT,
    SESSION_WORKSPACE_TAB,
    SESSION_WORKSPACE_TAB_INTENT,
    WORKSPACE_TAB_FAVORITES,
    WORKSPACE_TAB_RECENT,
    WORKSPACE_TAB_SAVED,
    WORKSPACE_TAB_SEARCH,
    goto,
)
from utils.personalization import personalize

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
MAX_FAVORITES_EXPORT = 500
RECENT_LIMIT_DEFAULT = 50
SEARCH_LIMIT_OPTIONS = (25, 50, 100, 200)
SEARCH_LIMIT_DEFAULT = 100
GRID_COLUMNS_DEFAULT = 3
GRID_COLUMNS_MIN = 1

# Visible workspace sections (Recently viewed / Saved searches removed from UI)
ACTIVE_WORKSPACE_TABS = (WORKSPACE_TAB_SEARCH, WORKSPACE_TAB_FAVORITES)

TAB_LABELS: dict[str, str] = {
    WORKSPACE_TAB_SEARCH: "🔍 Global search",
    WORKSPACE_TAB_FAVORITES: "★ Favorites",
}


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #
def _selectbox_index(options: Sequence[Any], value: Any) -> int:
    """Return the index of *value* in *options*, falling back to 0."""
    try:
        return options.index(value)
    except (ValueError, AttributeError):
        return 0


def _has_filters(term: str, project_id: Any, category_id: Any, tag: Any) -> bool:
    return bool((term or "").strip() or project_id or category_id or tag)


def _format_option(value: Any, label_all: str, lookup: dict[Any, str]) -> str:
    if value is None:
        return label_all
    return lookup.get(value, str(value))


@st.cache_data(ttl=60, show_spinner=False)
def _cached_tag_names(response_ids: tuple[int, ...]) -> dict[int, list[str]]:
    """Cache tag-name lookups; keyed on the tuple of response IDs."""
    return response_tag_names(list(response_ids))


def _invalidate_user_caches() -> None:
    """Drop caches after a mutation."""
    _cached_tag_names.clear()


# --------------------------------------------------------------------------- #
# Data containers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FilterOptions:
    project_ids: list[Any]
    project_lookup: dict[Any, str]
    category_ids: list[Any]
    category_lookup: dict[Any, str]
    tag_names: list[Any]


def _load_filter_options(project_id: Any = None) -> FilterOptions:
    """Load projects/categories/tags once and derive selection lists.

    Categories are filtered to the given project when one is selected.
    """
    projects, categories, tags = project_filter_options()

    applicable_categories = [
        c for c in categories if project_id is None or c.project_id == project_id
    ]

    return FilterOptions(
        project_ids=[None] + [p.id for p in projects],
        project_lookup={p.id: p.name for p in projects},
        category_ids=[None] + [c.id for c in applicable_categories],
        category_lookup={c.id: c.name for c in applicable_categories},
        tag_names=[None] + [t.name for t in tags],
    )


# --------------------------------------------------------------------------- #
# Tile & grid
# --------------------------------------------------------------------------- #
def _response_tile(
    user,
    row,
    favorites: set,
    key_prefix: str,
    tags: dict,
    overrides: dict,
) -> None:
    project = row.category.project
    text = personalize(row.response_body, user, project.id, overrides)
    is_fav = row.id in favorites

    with st.container(border=True):
        st.markdown(f"**{row.title}**")
        st.caption(f"{project.icon} {project.name} · 📂 {row.category.name}")

        row_tags = tags.get(row.id) or []
        if row_tags:
            st.caption(" · ".join(f"🏷️ {tag}" for tag in row_tags))
        if row.preview:
            st.caption(row.preview)

        st.code(text, language=None, wrap_lines=True)

        col_fav, col_open = st.columns(2)

        fav_label = "★ Remove favorite" if is_fav else "☆ Add favorite"
        if col_fav.button(
            fav_label,
            key=f"{key_prefix}_fav_{row.id}",
            help="Add or remove favorite",
            width="stretch",
        ):
            try:
                toggle_favorite(user.id, row.id)
            except Exception:  # noqa: BLE001
                logger.exception("Favorite toggle failed for user %s response %s", user.id, row.id)
                st.error("Could not update favorite. Please try again.")
                return
            _invalidate_user_caches()
            st.rerun()

        if col_open.button(
            "Open project",
            key=f"{key_prefix}_open_{row.id}",
            width="stretch",
        ):
            try:
                record_view(user.id, row.id)
            except Exception:  # noqa: BLE001
                # A failed view record shouldn't block navigation.
                pass
            goto(PAGE_PROJECT, project_id=project.id)


def _grid(user, rows: Iterable, favorites: set[int], prefix: str) -> None:
    rows = list(rows)
    if not rows:
        st.info("Nothing to show here yet.")
        return

    response_ids = tuple(row.id for row in rows)
    tags = _cached_tag_names(response_ids)

    count = int(
        st.session_state.get("user_preferences", {}).get(
            "card_columns", GRID_COLUMNS_DEFAULT
        )
    )
    count = max(GRID_COLUMNS_MIN, count)

    overrides = designation_overrides(user.id)
    cols = st.columns(count, gap="medium")
    for i, row in enumerate(rows):
        with cols[i % count]:
            _response_tile(user, row, favorites, prefix, tags, overrides)


# --------------------------------------------------------------------------- #
# Tab: Global search
# --------------------------------------------------------------------------- #
def _render_search_tab(user, favorites: set[int]) -> None:
    saved = saved_searches(user.id)
    saved_lookup = {item.id: item for item in saved}

    loaded = None
    if saved:
        selected = st.selectbox(
            "Load saved search",
            [None] + list(saved_lookup),
            format_func=lambda value: (
                "Select a saved search"
                if value is None
                else saved_lookup[value].name
            ),
            key="workspace_saved_search_select",
        )
        loaded = saved_lookup.get(selected)

    # Project selector is outside the form so downstream category options
    # react to the chosen project.
    options = _load_filter_options()

    project_id = st.selectbox(
        "Project",
        options.project_ids,
        index=_selectbox_index(
            options.project_ids, loaded.project_id if loaded else None
        ),
        format_func=lambda value: _format_option(
            value, "All projects", options.project_lookup
        ),
        key="workspace_search_project",
    )

    # Re-derive category options for the selected project.
    options = _load_filter_options(project_id)

    with st.form("workspace_search_form", clear_on_submit=False):
        term = st.text_input(
            "Search the complete response library",
            value=loaded.query if loaded else "",
            placeholder="Title, project, category, preview or response content",
        )

        col_cat, col_tag, col_limit = st.columns(3)

        category_id = col_cat.selectbox(
            "Category",
            options.category_ids,
            index=_selectbox_index(
                options.category_ids, loaded.category_id if loaded else None
            ),
            format_func=lambda value: _format_option(
                value, "All categories", options.category_lookup
            ),
        )

        tag = col_tag.selectbox(
            "Tag",
            options.tag_names,
            index=_selectbox_index(
                options.tag_names, loaded.tag if loaded else None
            ),
            format_func=lambda value: "All tags" if value is None else value,
        )

        limit = col_limit.select_slider(
            "Maximum results",
            options=list(SEARCH_LIMIT_OPTIONS),
            value=SEARCH_LIMIT_DEFAULT,
        )

        save_name = st.text_input(
            "Save current search as",
            placeholder="Example: Account support",
        )

        col_search, col_save, col_reset = st.columns([1, 1, 1])
        submitted = col_search.form_submit_button("🔍 Search", width="stretch")
        save_clicked = col_save.form_submit_button("💾 Save search", width="stretch")
        reset_clicked = col_reset.form_submit_button("♻️ Reset", width="stretch")

    if reset_clicked:
        for key in (
            "workspace_search_project",
            "workspace_saved_search_select",
        ):
            st.session_state.pop(key, None)
        st.rerun()

    if save_clicked:
        try:
            save_search(user.id, save_name, term, project_id, category_id, tag)
        except ValueError:
            logger.exception("Saved search validation failed for user %s", user.id)
            st.error("Please enter a valid saved search name and try again.")
        except Exception:  # noqa: BLE001
            logger.exception("Saved search creation failed for user %s", user.id)
            st.error("Could not save search. Please try again.")
        else:
            st.session_state["workspace_flash"] = "Search saved."
            st.rerun()

    if not submitted:
        st.caption("Enter a term or pick a filter, then press **Search**.")
        return

    if not _has_filters(term, project_id, category_id, tag):
        st.info("Provide a search term or at least one filter.")
        return

    with st.spinner("Searching…"):
        try:
            results = global_search(term, project_id, category_id, tag, limit, viewer=user)
        except Exception:  # noqa: BLE001
            logger.exception("Workspace search failed for user %s", user.id)
            st.error("Search failed. Please try again.")
            return

    st.caption(f"{len(results)} result(s)")
    if not results:
        st.info("No matches. Try loosening your filters.")
        return

    _grid(user, results, favorites, "search")


# --------------------------------------------------------------------------- #
# Tab: Favorites
# --------------------------------------------------------------------------- #
def _render_favorites_tab(user, favorites: set[int]) -> None:
    try:
        rows = response_records(user.id, "favorites", MAX_FAVORITES_EXPORT)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load favorites for user %s", user.id)
        st.error("Could not load favorites. Please try again.")
        return

    if not rows:
        st.info("No favorites yet. Select ☆ on any response to add it here.")
        return

    export_payload = [
        {
            "id": row.id,
            "title": row.title,
            "project": row.category.project.name,
            "category": row.category.name,
            "response_body": row.response_body,
        }
        for row in rows
    ]

    st.download_button(
        "⬇️ Export favorites (JSON)",
        data=json.dumps(export_payload, ensure_ascii=False, indent=2),
        file_name="jira_favorites.json",
        mime="application/json",
        width="content",
        key="workspace_export_favorites",
        help="Exports the raw response body. Review before sharing.",
    )

    _grid(user, rows, favorites, "favorite")


# --------------------------------------------------------------------------- #
# Tab: Recently viewed
# --------------------------------------------------------------------------- #
def _render_recent_tab(user, favorites: set[int]) -> None:
    try:
        rows = response_records(user.id, "recent", RECENT_LIMIT_DEFAULT)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load recent items for user %s", user.id)
        st.error("Could not load recent items. Please try again.")
        return

    if not rows:
        st.info("Recently viewed responses will appear here.")
        return

    st.caption(f"Showing the last {RECENT_LIMIT_DEFAULT} viewed responses.")
    _grid(user, rows, favorites, "recent")


# --------------------------------------------------------------------------- #
# Tab: Saved searches
# --------------------------------------------------------------------------- #
def _render_saved_tab(user) -> None:
    try:
        rows = saved_searches(user.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load saved searches for user %s", user.id)
        st.error("Could not load saved searches. Please try again.")
        return

    if not rows:
        st.info("No saved searches yet.")
        return

    for item in rows:
        col_info, col_action = st.columns([6, 1])
        col_info.write(f"**{item.name}** · `{item.query or 'Filters only'}`")

        with col_action.popover("Delete"):
            st.warning(f"Delete saved search **{item.name}**?")
            if st.button(
                "Yes, delete",
                key=f"confirm_delete_saved_{item.id}",
                type="primary",
                width="stretch",
            ):
                try:
                    delete_saved_search(user.id, item.id)
                except Exception:  # noqa: BLE001
                    logger.exception("Delete saved search failed for user %s search %s", user.id, item.id)
                    st.error("Could not delete saved search. Please try again.")
                else:
                    st.session_state["workspace_flash"] = "Saved search deleted."
                    st.rerun()


# --------------------------------------------------------------------------- #
# Tab selection
# --------------------------------------------------------------------------- #
def _resolve_tab() -> str:
    """Return the active workspace tab, honouring cross-page intent.

    Other pages set `SESSION_WORKSPACE_TAB_INTENT` before navigating to
    the workspace. We consume it here to override the radio widget's
    sticky value on the first render after navigation.
    """
    incoming = st.session_state.pop(SESSION_WORKSPACE_TAB_INTENT, None)
    if incoming in ACTIVE_WORKSPACE_TABS:
        st.session_state[SESSION_WORKSPACE_TAB] = incoming
        st.session_state["workspace_tab_radio"] = incoming

    current = st.session_state.get(SESSION_WORKSPACE_TAB, WORKSPACE_TAB_SEARCH)
    if current not in ACTIVE_WORKSPACE_TABS:
        current = WORKSPACE_TAB_SEARCH
    return current


def _render_tab_selector() -> str:
    """Horizontal radio used as a tab bar (st.tabs can't be selected
    programmatically)."""
    default = _resolve_tab()
    default_index = ACTIVE_WORKSPACE_TABS.index(default)

    choice = st.radio(
        "Workspace section",
        options=list(ACTIVE_WORKSPACE_TABS),
        index=default_index,
        format_func=lambda key: TAB_LABELS.get(key, key),
        horizontal=True,
        label_visibility="collapsed",
        key="workspace_tab_radio",
    )

    st.session_state[SESSION_WORKSPACE_TAB] = choice
    return choice


# --------------------------------------------------------------------------- #
# Flash message helper
# --------------------------------------------------------------------------- #
def _render_flash() -> None:
    """Display a one-shot success message that survives a rerun."""
    flash = st.session_state.pop("workspace_flash", None)
    if flash:
        st.success(flash)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def render(user) -> None:
    page_header("My Workspace", "Search, favourites, recently viewed and saved searches.", icon="⭐")

    _render_flash()

    favorites = set(favorite_ids(user.id))
    tab = _render_tab_selector()

    if tab == WORKSPACE_TAB_SEARCH:
        _render_search_tab(user, favorites)
    elif tab == WORKSPACE_TAB_FAVORITES:
        _render_favorites_tab(user, favorites)
    elif tab == WORKSPACE_TAB_RECENT:
        _render_recent_tab(user, favorites)
    elif tab == WORKSPACE_TAB_SAVED:
        _render_saved_tab(user)