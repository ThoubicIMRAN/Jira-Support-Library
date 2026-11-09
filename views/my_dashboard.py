"""My Dashboard — assignee queue + charts (all projects) + SLA badges."""
from __future__ import annotations

import logging
import re
from collections import Counter

import pandas as pd
import streamlit as st

from components.cards import page_header
from config import JIRA_BASE_URL
from services import jira_service
from services.jira_service import JiraError
from services.rate_limit import limit_sensitive_api, RateLimitExceeded
from services.sla_utils import issue_badges, badge_label
from utils.errors import safe_message, log_ignored

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}-\d{1,8}$")
_STALE_DAYS = 14
_TOP_N_PROJECTS = 12
_SLA_BADGE_LEGEND = {
    "overdue": "🔴 overdue",
    "due_soon": "🟠 due soon",
    "stale": "🟡 stale (no update 14d+)",
    "blocked": "⛔ blocked",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _safe_text(v, limit: int = 120) -> str:
    s = str(v or "")
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", "", s)
    s = re.sub(r"[\[\]<>`]", "", s)
    return s[:limit]


def _valid_key(k: str) -> bool:
    return bool(_KEY_RE.match((k or "").strip().upper()))


def _has_badge(it: dict, name: str) -> bool:
    """Tolerant badge check — some backends return labels, not ids."""
    try:
        badges = issue_badges(it) or []
    except Exception:
        return False
    for b in badges:
        if isinstance(b, str) and (b == name or name in b.lower()):
            return True
    return False


def _jira_url(key: str) -> str | None:
    if not _valid_key(key) or not JIRA_BASE_URL:
        return None
    return f"{JIRA_BASE_URL.rstrip('/')}/browse/{key}"


def _load_queue(user, max_n: int) -> list[dict]:
    try:
        limit_sensitive_api(user.id, "my_queue")
        with st.spinner("Loading your Jira queue…"):
            return jira_service.fetch_my_queue(user.id, max_results=int(max_n)) or []
    except RateLimitExceeded as exc:
        st.warning(safe_message(exc))
    except JiraError as exc:
        st.error(safe_message(exc))
    except Exception:
        logger.exception("My queue load failed")
        st.error("Could not load your queue. Check Jira connection in Settings.")
    return []


def _enrich(issues: list[dict]) -> list[dict]:
    """Attach computed badge + urgency without mutating input."""
    out = []
    for it in issues:
        badges = issue_badges(it) if it else []
        try:
            labels = [badge_label(b) if not isinstance(b, str) else b for b in (badges or [])]
        except Exception:
            labels = list(badges or [])
        row = dict(it)
        row["_badges"] = labels
        out.append(row)
    return out


def render(user) -> None:
    page_header("My Dashboard")
    st.caption(
        "Your open assigned Jira issues across projects. "
        "Click **🎫** to pre-fill that ticket for the next Jira action."
    )

    c1, c2, c3 = st.columns([1, 1, 3])
    refresh = c1.button("🔄 Refresh", key=f"mq_refresh_{user.id}")
    max_n = c2.slider("Max issues", 20, 200, 100, 10, key=f"mq_max_{user.id}")
    pending = st.session_state.get("mq_prefill_queue") or []
    if pending:
        c3.success(
            f"🎫 **{len(pending)}** ticket(s) queued — last: `{_safe_text(pending[-1], 20)}`"
        )
        if c3.button("Clear queue", key=f"mq_clear_q_{user.id}"):
            st.session_state["mq_prefill_queue"] = []
            st.rerun()
    else:
        c3.caption("No tickets queued for the next Jira action.")

    cache_key = f"my_queue_{user.id}_{max_n}"
    if refresh or cache_key not in st.session_state:
        # prune older queue caches for this user
        for k in list(st.session_state.keys()):
            if k.startswith(f"my_queue_{user.id}_") and k != cache_key:
                del st.session_state[k]
        st.session_state[cache_key] = _load_queue(user, max_n)

    issues = _enrich(st.session_state.get(cache_key) or [])

    if not issues:
        st.info("No open issues assigned to you, or Jira is not connected.")
        if st.button("🔗 Open Jira Settings", key=f"mq_goto_{user.id}"):
            try:
                st.session_state["nav_target"] = "settings_jira"
                st.rerun()
            except Exception:
                log_ignored("my_dashboard.open_jira_settings")
        return
