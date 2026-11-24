"""My Dashboard — assignee queue + charts (all projects) + SLA badges."""

from __future__ import annotations

import logging
import re
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st

from components.cards import page_header
from config import JIRA_BASE_URL
from services import jira_service
from services.jira_service import JiraError
from services.rate_limit import RateLimitExceeded, limit_sensitive_api
from services.sla_utils import badge_label, issue_badges
from utils.errors import log_ignored, safe_message

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


def urgency_score(issue: dict) -> int:
    """Higher = more urgent. Used as primary sort key."""
    score = 0
    if _has_badge(issue, "overdue"):
        score += 100
    if _has_badge(issue, "due_soon"):
        score += 50
    if _has_badge(issue, "blocked"):
        score += 25
    if _has_badge(issue, "stale"):
        score += 10
    return score


def _load_queue(user, max_n: int, include_unassigned: bool = False) -> list[dict]:
    try:
        limit_sensitive_api(user.id, "my_queue")
        with st.spinner("Loading your Jira queue…"):
            if include_unassigned:
                return (
                    jira_service.fetch_my_queue(
                        user.id,
                        max_results=int(max_n),
                        include_unassigned=True,
                    )
                    or []
                )
            return jira_service.fetch_my_queue(user.id, max_results=int(max_n)) or []
    except RateLimitExceeded as exc:
        st.warning(safe_message(exc))
    except JiraError as exc:
        st.error(safe_message(exc))
    except TypeError:
        # include_unassigned not supported by the service — degrade gracefully
        st.warning(
            "Backend does not support `include_unassigned` yet; "
            "showing assigned issues only."
        )
        try:
            return jira_service.fetch_my_queue(user.id, max_results=int(max_n)) or []
        except Exception:
            logger.exception("My queue load failed (fallback)")
    except Exception:
        logger.exception("My queue load failed")
        st.error("Could not load your queue. Check Jira connection in Settings.")
    return []


def _enrich(issues: list[dict]) -> list[dict]:
    """Attach computed badge + urgency without mutating input."""
    out = []
    for it in issues:
        badges = issue_badges(it) or []
        out.append(
            {
                **it,
                "_badges": badges,
                "_labels": [badge_label(b) for b in badges],
                "_urgency": urgency_score(it),
            }
        )
    return out


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
def render(user) -> None:
    page_header("📊 My Dashboard")
    st.caption(
        "Your open Jira issues (`assignee = currentUser()`), all projects. "
        "Connect Jira under **Personal settings** if empty. "
        "Click **🎫** on a row to queue it for the next Jira action dialog."
    )

    # ---- controls ----
    c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
    refresh = c1.button("🔄 Refresh", key=f"mq_refresh_{user.id}")
    max_n = c2.slider("Max issues", 20, 200, 100, 10, key=f"mq_max_{user.id}")
    show_unassigned = c3.checkbox(
        "Include Unassigned",
        value=False,
        key=f"mq_unassigned_{user.id}",
    )

    pending = st.session_state.get("mq_prefill_queue") or []
    if pending:
        c4.success(
            f"🎫 **{len(pending)}** ticket(s) queued — last: "
            f"`{_safe_text(pending[-1], 20)}`"
        )
        if c4.button("Clear queue", key=f"mq_clear_q_{user.id}"):
            st.session_state["mq_prefill_queue"] = []
            st.rerun()
    else:
        c4.caption("No tickets queued for the next Jira action.")

    cache_key = f"my_queue_{user.id}_{max_n}_{show_unassigned}"
    if refresh or cache_key not in st.session_state:
        # prune older queue caches for this user
        for k in list(st.session_state.keys()):
            if k.startswith(f"my_queue_{user.id}_") and k != cache_key:
                del st.session_state[k]
        st.session_state[cache_key] = _load_queue(
            user, max_n, include_unassigned=show_unassigned
        )

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

    dash = jira_service.aggregate_queue_dashboard(issues) or {}

    # ---- KPI row ----
    n_overdue = sum(1 for it in issues if _has_badge(it, "overdue"))
    n_stale = sum(1 for it in issues if _has_badge(it, "stale"))
    n_due_soon = sum(1 for it in issues if _has_badge(it, "due_soon"))
    n_blocked = sum(1 for it in issues if _has_badge(it, "blocked"))
    n_unassigned = sum(1 for it in issues if not it.get("assignee"))
    n_assigned = len(issues) - n_unassigned

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Assigned", n_assigned)
    m2.metric("Unassigned", n_unassigned)
    m3.metric("🔴 Overdue", n_overdue)
    m4.metric("🟠 Due soon", n_due_soon)
    m5.metric(f"🟡 Stale ({_STALE_DAYS}d+)", n_stale)
    m6.metric("⛔ Blocked", n_blocked)

    with st.expander("Badge legend", expanded=False):
        for _k, v in _SLA_BADGE_LEGEND.items():
            st.caption(v)

    tab_charts, tab_queue, tab_unassigned, tab_aging = st.tabs(
        ["📈 Charts", "🎯 My Queue", "📭 Unassigned", "⏳ Aging"]
    )

    # ==================================================================
    # Charts
    # ==================================================================
    with tab_charts:
        # ---- SLA donut ----
        st.subheader("SLA Health")
        healthy = max(len(issues) - n_overdue - n_due_soon, 0)
        sla_df = pd.DataFrame(
            {
                "Status": ["Overdue", "Due Soon", "Healthy"],
                "Count": [n_overdue, n_due_soon, healthy],
            }
        )
        if sla_df["Count"].sum() > 0:
            fig = px.pie(
                sla_df,
                names="Status",
                values="Count",
                hole=0.6,
                color="Status",
                color_discrete_map={
                    "Overdue": "red",
                    "Due Soon": "orange",
                    "Healthy": "green",
                },
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No SLA data.")

        # ---- Project / status treemap ----
        flat = dash.get("flat_project_status") or []
        st.subheader("Issues by project & status")
        if flat and {"project", "status", "count"}.issubset(flat[0].keys()):
            df = pd.DataFrame(flat)
            projects_sorted = (
                df.groupby("project")["count"].sum().sort_values(ascending=False)
            )
            top_projects = list(projects_sorted.index[:_TOP_N_PROJECTS])
            only_top = st.checkbox(
                f"Show only top {_TOP_N_PROJECTS} projects",
                value=len(projects_sorted) > _TOP_N_PROJECTS,
                key=f"mq_top_projects_{user.id}",
            )
            plot_df = df[df["project"].isin(top_projects)] if only_top else df
            pivot = plot_df.pivot_table(
                index="project",
                columns="status",
                values="count",
                aggfunc="sum",
                fill_value=0,
            )
            chart_kind = st.radio(
                "Chart type",
                ["Treemap", "Stacked bar", "Grouped bar", "Heatmap (table)"],
                horizontal=True,
                key=f"mq_chart_kind_{user.id}",
            )
            if chart_kind == "Heatmap (table)":
                st.dataframe(pivot, width="stretch")
            elif chart_kind == "Treemap":
                tmp = plot_df.copy()
                if not tmp.empty and (tmp["count"] > 0).any():
                    tmp["count"] = tmp["count"].astype(float).clip(lower=0.0)
                    fig = px.treemap(
                        tmp,
                        path=["project", "status"],
                        values="count",
                        color="count",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.caption("No nonzero data to plot.")
            else:
                st.bar_chart(pivot, stack=chart_kind == "Stacked bar")
            with st.expander("Raw table"):
                st.dataframe(pivot, width="stretch")
                st.download_button(
                    "⬇️ Download CSV",
                    data=pivot.to_csv().encode(),
                    file_name="my_queue_project_status.csv",
                    mime="text/csv",
                    key=f"mq_dl_ps_{user.id}",
                )
        else:
            st.caption("No project/status data available.")

        st.subheader("Status distribution")
        status_counts = Counter(it.get("status") or "—" for it in issues)
        if status_counts:
            sdf = pd.DataFrame(
                {
                    "status": list(status_counts.keys()),
                    "count": list(status_counts.values()),
                }
            ).set_index("status")
            st.bar_chart(sdf)
        else:
            st.caption("No status data.")

        st.subheader("Due dates")
        due = dash.get("due_buckets") or {}
        if due:
            due_df = pd.DataFrame(
                {"bucket": list(due.keys()), "count": list(due.values())}
            ).set_index("bucket")
            st.bar_chart(due_df)
            overdue = due.get("Overdue") or 0
            if overdue:
                st.warning(f"**{overdue}** issue(s) overdue.")
            with st.expander("Due-date breakdown"):
                st.dataframe(due_df, width="stretch")

        st.subheader("Priority mix")
        prio = Counter((it.get("priority") or "Unset") for it in issues)
        if prio:
            p_df = pd.DataFrame(
                {"priority": list(prio.keys()), "count": list(prio.values())}
            ).set_index("priority")
            st.bar_chart(p_df)

    # ==================================================================
    # Queue
    # ==================================================================
    with tab_queue:
        f1, f2, f3, f4 = st.columns(4)
        statuses = sorted({it.get("status") or "—" for it in issues})
        types = sorted({it.get("type") or "—" for it in issues})
        projects = sorted(
            {(it.get("key") or "").split("-", 1)[0] for it in issues if it.get("key")}
        )

        pick_status = f1.multiselect("Status", statuses, key=f"mq_fs_{user.id}")
        pick_type = f2.multiselect("Type", types, key=f"mq_ft_{user.id}")
        pick_proj = f3.multiselect("Project", projects, key=f"mq_fp_{user.id}")
        only_overdue = f4.checkbox("Only overdue / due soon", key=f"mq_fod_{user.id}")

        def _keep(it: dict) -> bool:
            if pick_status and (it.get("status") or "—") not in pick_status:
                return False
            if pick_type and (it.get("type") or "—") not in pick_type:
                return False
            if pick_proj and ((it.get("key") or "").split("-", 1)[0] not in pick_proj):
                return False
            if only_overdue and not (
                _has_badge(it, "overdue") or _has_badge(it, "due_soon")
            ):
                return False
            return True

        filtered = [it for it in issues if _keep(it)]

        # ---- sort: urgency first, user-selected as tiebreaker ----
        sort_key = st.radio(
            "Sort by",
            ["Urgency", "Due date", "Priority", "Status", "Key"],
            horizontal=True,
            key=f"mq_sort_{user.id}",
        )
        prio_rank = {
            "Highest": 0,
            "High": 1,
            "Medium": 2,
            "Low": 3,
            "Lowest": 4,
            "Unset": 5,
        }
        if sort_key == "Urgency":
            filtered.sort(key=lambda it: (-it.get("_urgency", 0), it.get("key") or ""))
        elif sort_key == "Due date":
            filtered.sort(
                key=lambda it: (
                    -it.get("_urgency", 0),
                    it.get("duedate") or "9999-99-99",
                )
            )
        elif sort_key == "Priority":
            filtered.sort(
                key=lambda it: (
                    -it.get("_urgency", 0),
                    prio_rank.get(it.get("priority") or "Unset", 9),
                )
            )
        elif sort_key == "Status":
            filtered.sort(
                key=lambda it: (
                    -it.get("_urgency", 0),
                    (it.get("status") or "").lower(),
                )
            )
        elif sort_key == "Key":
            filtered.sort(key=lambda it: it.get("key") or "")

        st.caption(f"{len(filtered)} of {len(issues)} issues shown.")

        # ---- bulk pre-fill ----
        if filtered:
            keys_filtered = [it["key"] for it in filtered if _valid_key(it.get("key"))]
            b1, b2 = st.columns([1, 3])
            if b1.button(
                f"🎫 Queue all {len(keys_filtered)}",
                key=f"mq_queue_all_{user.id}",
                disabled=not keys_filtered,
            ):
                st.session_state["mq_prefill_queue"] = (
                    st.session_state.get("mq_prefill_queue") or []
                ) + keys_filtered
                st.session_state["mq_prefill_ticket"] = keys_filtered[-1]
                st.session_state["jira_last_ticket_global"] = keys_filtered[-1]
                st.toast(f"Queued {len(keys_filtered)} ticket(s)")
                st.rerun()

        # ---- list ----
        tree = jira_service.group_queue_by_project_type(filtered)
        for project_key in sorted(tree.keys()):
            types_map = tree[project_key]
            n_proj = sum(len(v) for v in types_map.values())
            with st.expander(
                f"**{_safe_text(project_key, 24)}** ({n_proj})",
                expanded=n_proj <= 8,
            ):
                for itype in sorted(types_map.keys()):
                    rows = types_map[itype]
                    st.markdown(f"**{_safe_text(itype, 40)}** · {len(rows)}")
                    for it in rows:
                        key = it.get("key") or ""
                        due = _safe_text(it.get("duedate") or "—", 12)
                        badge_txt = " ".join(it.get("_labels") or []) or "—"
                        cols = st.columns([1.4, 3.2, 1.2, 1.2, 1.4, 0.7, 0.7, 0.7])
                        cols[0].markdown(f"`{_safe_text(key, 20)}`")
                        cols[1].caption(_safe_text(it.get("summary") or ""))
                        cols[2].caption(_safe_text(it.get("status") or ""))
                        cols[3].caption(f"Due {due}")
                        cols[4].caption(badge_txt)

                        if cols[5].button(
                            "🎫",
                            key=f"mq_open_{user.id}_{key}",
                            help="Pre-fill this ticket for the next Jira action",
                        ):
                            q = st.session_state.get("mq_prefill_queue") or []
                            if key and key not in q:
                                q.append(key)
                            st.session_state["mq_prefill_queue"] = q
                            st.session_state["mq_prefill_ticket"] = key
                            st.session_state["jira_last_ticket_global"] = key
                            st.toast(f"Queued {key}")

                        if cols[6].button(
                            "🔗",
                            key=f"mq_link_{user.id}_{key}",
                            help="Open in Jira",
                        ):
                            url = _jira_url(key)
                            if url:
                                st.markdown(f"[Open {_safe_text(key)} ↗]({url})")
                            else:
                                st.warning("Jira base URL not configured.")

                        if cols[7].button(
                            "📌",
                            key=f"mq_pin_{user.id}_{key}",
                            help="Show raw JSON (debug)",
                        ):
                            with st.popover(f"Raw {_safe_text(key, 20)}"):
                                st.json(it)
                st.markdown("---")

    # ==================================================================
    # Unassigned
    # ==================================================================
    with tab_unassigned:
        unassigned = [i for i in issues if not i.get("assignee")]
        if not unassigned:
            st.info("No unassigned tickets.")
        else:
            df = pd.DataFrame(
                [
                    {
                        "Key": i.get("key"),
                        "Summary": _safe_text(i.get("summary") or ""),
                        "Project": i.get("project")
                        or (i.get("key") or "").split("-", 1)[0],
                        "Status": i.get("status"),
                        "Priority": i.get("priority"),
                        "Due": i.get("duedate"),
                    }
                    for i in unassigned
                ]
            )
            st.dataframe(df, width="stretch", hide_index=True)
            st.download_button(
                "⬇️ Download unassigned CSV",
                data=df.to_csv(index=False).encode(),
                file_name="my_queue_unassigned.csv",
                mime="text/csv",
                key=f"mq_dl_unassigned_{user.id}",
            )

    # ==================================================================
    # Aging
    # ==================================================================
    with tab_aging:
        st.subheader("Time since last update")

        def _days_since(it: dict) -> int | None:
            for k in ("updated", "updated_at", "last_updated"):
                v = it.get(k)
                if not v:
                    continue
                try:
                    ts = pd.to_datetime(v, utc=True, errors="coerce")
                    if pd.isna(ts):
                        continue
                    return max(0, int((pd.Timestamp.utcnow() - ts).days))
                except Exception:
                    continue
            return None

        buckets = {"0-2d": 0, "3-7d": 0, "8-14d": 0, "15-30d": 0, "30d+": 0}
        rows = []
        for it in issues:
            d = _days_since(it)
            if d is None:
                continue
            if d <= 2:
                buckets["0-2d"] += 1
            elif d <= 7:
                buckets["3-7d"] += 1
            elif d <= 14:
                buckets["8-14d"] += 1
            elif d <= 30:
                buckets["15-30d"] += 1
            else:
                buckets["30d+"] += 1
            rows.append(
                {
                    "key": it.get("key"),
                    "days_since_update": d,
                    "status": it.get("status"),
                }
            )

        if rows:
            adf = pd.DataFrame(rows).set_index("key")
            st.dataframe(
                adf.sort_values("days_since_update", ascending=False),
                width="stretch",
            )
            st.bar_chart(
                pd.DataFrame(
                    {"bucket": list(buckets), "count": list(buckets.values())}
                ).set_index("bucket")
            )
        else:
            st.caption("No update timestamps available on your Jira payload.")
