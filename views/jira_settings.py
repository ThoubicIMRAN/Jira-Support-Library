"""Jira + Confluence — matching two-column layout."""
from __future__ import annotations

import logging

import streamlit as st

from config import CONFLUENCE_BASE_URL, JIRA_BASE_URL, JIRA_ENABLED, JIRA_PRODUCT
from services import confluence_service, jira_service
from services.confluence_client import ConfluenceError
from services.jira_client import JiraError

logger = logging.getLogger(__name__)


def render_jira_settings(user) -> None:
    if not JIRA_ENABLED:
        st.info("Jira integration is disabled.")
        return

    left, right = st.columns(2)

    # ========== JIRA ==========
    with left:
        st.markdown("##### 🎫 Jira")
        st.caption((JIRA_BASE_URL or "Set JIRA_BASE_URL") + f" · {JIRA_PRODUCT}")
        status = jira_service.credential_status(user.id)
        if status.get("connected"):
            st.success(f"Connected as **{status.get('display_name')}**")
        else:
            st.info("Not connected")

        product = st.selectbox(
            "Product",
            ["cloud", "server"],
            index=0 if (status.get("product") or JIRA_PRODUCT) == "cloud" else 1,
            format_func=lambda x: "Cloud (email + API token)" if x == "cloud" else "Server / DC (PAT)",
            key="jira_set_product",
        )
        email = ""
        if product == "cloud":
            email = st.text_input(
                "Username / email",
                value=status.get("email") or "",
                key="jira_set_email",
            )
        else:
            email = st.text_input(
                "Username (optional)",
                value=status.get("email") or "",
                key="jira_set_email_server",
            )
        secret = st.text_input("Personal Access Token / API token", type="password", key="jira_set_secret")

        b1, b2 = st.columns(2)
        if b1.button("Save & test", type="primary", key="jira_save_cred"):
            if not secret.strip():
                st.error("Token is required.")
            elif product == "cloud" and not (email or "").strip():
                st.error("Email is required for Cloud.")
            else:
                with st.spinner("Testing Jira connection…"):
                    try:
                        info = jira_service.save_user_credentials(
                            user.id, product=product, email=email or None, secret=secret
                        )
                        st.session_state.pop("jira_set_secret", None)
                        st.toast(f"Jira connected: {info.get('display_name')}", icon="✅")
                        st.rerun()
                    except JiraError as exc:
                        st.error(str(exc))
                    except Exception:
                        logger.exception("Jira connect")
                        st.error("Jira connection failed.")
        if status.get("connected") and b2.button("Disconnect", key="jira_disconnect"):
            jira_service.disconnect_user(user.id)
            st.rerun()

    # ========== CONFLUENCE ==========
    with right:
        st.markdown("##### 📘 Confluence")
        base = (CONFLUENCE_BASE_URL or "").rstrip("/") or "Set CONFLUENCE_BASE_URL"
        st.caption(base)
        conf = confluence_service.status(user.id)
        if conf.get("configured"):
            st.success("Connected (PAT saved)")
        else:
            st.info("Not connected")

        st.selectbox(
            "Product",
            ["Server / DC (PAT)"],
            disabled=True,
            key="conf_product_display",
            help="Confluence Server/DC uses a Personal Access Token",
        )
        conf_user = st.text_input(
            "Username / email",
            value=conf.get("email") or "",
            key="conf_email",
        )
        conf_secret = st.text_input(
            "Personal Access Token / API token",
            type="password",
            key="conf_secret",
        )

        c1, c2 = st.columns(2)
        if c1.button("Save & test", type="primary", key="conf_save_test"):
            if not (conf_secret or "").strip() and not conf.get("configured"):
                st.error("Token is required.")
            else:
                with st.spinner("Testing Confluence connection…"):
                    try:
                        if (conf_secret or "").strip() or conf_user:
                            confluence_service.save_credentials(
                                user.id, email=conf_user, secret=conf_secret or None
                            )
                        result = confluence_service.test_connection(user.id)
                        st.session_state.pop("conf_secret", None)
                        if result.get("ok"):
                            st.success(f"Confluence OK ({result.get('worked')})")
                        else:
                            st.error(result.get("error") or "Failed")
                    except ConfluenceError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(str(exc))
        if conf.get("configured") and c2.button("Disconnect", key="conf_clear"):
            confluence_service.disconnect(user.id)
            st.rerun()
