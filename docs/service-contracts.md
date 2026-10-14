# Service contracts

This document records the actual public project functions used by the app shell and view layer as they exist in the checked-in code.

## App shell and navigation

- `set_page(page: str, *, project_id: int | None = None, clear_project: bool = False) -> None`
  - Defined in `app.py`
  - Used for page changes and project-scoped navigation.

- `current_page() -> str`
  - Defined in `app.py`
  - Returns the active app page.

- `BREADCRUMB_LABELS: dict[str, str | None]`
  - Defined in `app.py`
  - Contains breadcrumb titles for page labels.

## Navigation helper

- `goto(page: str, *, workspace_tab: str | None = None, project_id: int | None = None, clear_project: bool = False) -> None`
  - Defined in `utils/navigation.py`
  - Validates known page names and updates session state before rerunning.

## Theme and preference contracts

- `resolve_theme(preferences: Mapping[str, Any] | None) -> str`
  - Defined in `services/preference_service.py`
  - Resolves a stored theme preference to a concrete `dark` or `light` theme.

- `preference_css(preferences: Mapping[str, Any] | None) -> str`
  - Defined in `services/preference_service.py`
  - Returns the full CSS block based on resolved theme and saved preferences.

- `get_portal_safe_css(theme: str | None = None) -> str`
  - Defined in `services/theme.py`
  - Accepts a resolved theme string or `None` and returns the portal-safe CSS block.

## Cookie service contracts

- `get_cookie_manager() -> object`
  - Defined in `services/cookie_service.py`
  - Returns a per-session cookie manager object or the fallback manager.

- `get_session_cookie() -> Optional[str]`
  - Defined in `services/cookie_service.py`
  - Reads the active session cookie without exposing the token to user-visible logs.

- `set_session_cookie(session_token: str) -> None`
  - Defined in `services/cookie_service.py`
  - Saves the session token when available.

- `delete_session_cookie() -> None`
  - Defined in `services/cookie_service.py`
  - Removes the session cookie during logout or expired-session cleanup.

## Session and auth contracts

- `create_session(user_id, auth_method='local') -> str`
  - Defined in `auth.py` / `services/session_service.py` execution path
  - Creates a signed session token and persists it server-side.

- `validate_session(raw) -> int | None`
  - Defined in `services/session_service.py`
  - Validates a session token and returns the user id when valid.

- `revoke_session(raw) -> None`
  - Defined in `services/session_service.py`
  - Marks a session as revoked.

## View API shape

- `render(user) -> None`
  - Used by all views in `views/*.py`
  - Page renderers are invoked by the app shell dispatcher only.
