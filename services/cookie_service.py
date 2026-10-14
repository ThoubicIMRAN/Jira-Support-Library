"""Production-grade session persistence for Streamlit.

Problem
-------
Streamlit cannot emit HTTP Set-Cookie from Python for custom auth.
CookieManager (iframe JS) often fails to write a cookie the server can see.
Query-param tokens work locally but are NOT production-safe (URL, history,
logs, Referer).

Production approach
-------------------
WRITE: inject JS that sets document.cookie on window.parent (the real page),
       not only inside the component iframe.
READ:  st.context.cookies on the next full page load (synchronous, no race).

Cookie attributes (production):
  Path=/; Max-Age=<SESSION_ABSOLUTE_HOURS>; SameSite=Lax; Secure (when HTTPS)

Server-side: AppSession table still validates the opaque token (hash lookup,
idle + absolute expiry, revocation). The browser only holds the raw token.

Optional local-only fallback:
  ALLOW_URL_SESSION=true  → also mirror token in ?jsl_st= (dev only)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import streamlit as st
import streamlit.components.v1 as components

try:
    from config import SESSION_ABSOLUTE_HOURS, APP_ROOT_PATH
except Exception:
    SESSION_ABSOLUTE_HOURS = 12
    APP_ROOT_PATH = ""

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "jira_support_session_token"
SESSION_QP = "jsl_st"
# Dev-only escape hatch — never enable in production
ALLOW_URL_SESSION = os.getenv("ALLOW_URL_SESSION", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _is_https() -> bool:
    try:
        # Prefer explicit env (behind reverse proxy)
        if os.getenv("FORCE_HTTPS", "").strip().lower() in ("1", "true", "yes"):
            return True
        headers = st.context.headers
        proto = None
        if hasattr(headers, "get"):
            proto = headers.get("X-Forwarded-Proto") or headers.get("x-forwarded-proto")
        if proto and str(proto).split(",")[0].strip().lower() == "https":
            return True
        # Local http://localhost → no Secure flag
        return False
    except Exception:
        return False


def _cookie_path() -> str:
    if APP_ROOT_PATH:
        return f"/{str(APP_ROOT_PATH).strip('/')}"
    return "/"


def _read_native_cookie() -> Optional[str]:
    try:
        cookies = st.context.cookies
        if hasattr(cookies, "to_dict"):
            value = cookies.to_dict().get(SESSION_COOKIE_NAME)
        elif hasattr(cookies, "get"):
            value = cookies.get(SESSION_COOKIE_NAME)
        else:
            try:
                value = cookies[SESSION_COOKIE_NAME]
            except Exception:
                value = None
        if value and isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        logger.debug("native cookie read failed", exc_info=True)
    return None


def get_session_cookie() -> Optional[str]:
    """Restore session token after a full browser reload."""
    # 1) Native cookies from the HTTP/WebSocket upgrade request (production path)
    token = _read_native_cookie()
    if token:
        return token

    # 2) Dev-only URL fallback
    if ALLOW_URL_SESSION:
        try:
            qp = st.query_params.get(SESSION_QP)
            if isinstance(qp, (list, tuple)):
                qp = qp[0] if qp else None
            if qp and str(qp).strip():
                return str(qp).strip()
        except Exception:
            pass
    return None


def set_session_cookie(session_token: str) -> None:
    """Persist token so the next hard reload can restore the session."""
    if not session_token:
        return

    max_age = int(SESSION_ABSOLUTE_HOURS) * 3600
    path = _cookie_path()
    secure = _is_https()
    # Escape token for JS string (opaque urlsafe — still escape quotes/backslashes)
    safe = (
        session_token.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("<", "")
        .replace(">", "")
    )
    secure_part = "; Secure" if secure else ""
    # Write on the PARENT document so the next full navigation sends the cookie
    # to Streamlit. Iframe-only document.cookie often never reaches st.context.
    js = f"""
    <script>
    (function() {{
      var c = "{SESSION_COOKIE_NAME}=" + encodeURIComponent("{safe}")
            + "; path={path}; max-age={max_age}; SameSite=Lax{secure_part}";
      try {{
        window.parent.document.cookie = c;
      }} catch (e) {{
        try {{ document.cookie = c; }} catch (e2) {{}}
      }}
    }})();
    </script>
    """
    try:
        components.html(js, height=0, width=0)
        logger.info(
            "Session cookie write injected (path=%s max_age=%ss secure=%s)",
            path,
            max_age,
            secure,
        )
    except Exception:
        logger.exception("Failed to inject session cookie script")

    # Dev-only URL mirror
    if ALLOW_URL_SESSION:
        try:
            st.query_params[SESSION_QP] = session_token
        except Exception:
            logger.exception("Failed to set dev query-param session")


def delete_session_cookie() -> None:
    """Clear cookie (and dev query param) on logout."""
    path = _cookie_path()
    secure = _is_https()
    secure_part = "; Secure" if secure else ""
    js = f"""
    <script>
    (function() {{
      var c = "{SESSION_COOKIE_NAME}=; path={path}; max-age=0; SameSite=Lax{secure_part}";
      try {{ window.parent.document.cookie = c; }} catch (e) {{
        try {{ document.cookie = c; }} catch (e2) {{}}
      }}
    }})();
    </script>
    """
    try:
        components.html(js, height=0, width=0)
    except Exception:
        logger.exception("Failed to inject cookie delete script")

    if ALLOW_URL_SESSION:
        try:
            if SESSION_QP in st.query_params:
                del st.query_params[SESSION_QP]
        except Exception:
            try:
                st.query_params.pop(SESSION_QP, None)
            except Exception:
                pass
