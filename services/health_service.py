"""Operational health checks for admin dashboard."""
from __future__ import annotations

import logging
import os

import requests
from sqlalchemy import text

from config import (
    CONFLUENCE_BASE_URL,
    JIRA_BASE_URL,
    JIRA_ENABLED,
    OLLAMA_BASE,
)
from database import engine

logger = logging.getLogger(__name__)


def health() -> dict:
    result: dict = {
        "status": "ok",
        "database": "unknown",
        "ollama": "unknown",
        "smtp": "unknown",
        "jira_config": "unknown",
        "confluence_config": "unknown",
    }

    # Database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        result["database"] = "ok"
    except Exception as exc:
        logger.exception("health db")
        result["database"] = "error"
        result["status"] = "degraded"
        result["database_error"] = str(exc)[:120]

    # Ollama
    try:
        base = (OLLAMA_BASE or "").rstrip("/")
        if not base:
            result["ollama"] = "not_configured"
        else:
            r = requests.get(f"{base}/api/tags", timeout=5)
            result["ollama"] = "ok" if r.status_code < 400 else f"http_{r.status_code}"
            if r.status_code >= 400:
                result["status"] = "degraded"
    except Exception as exc:
        result["ollama"] = "unreachable"
        result["status"] = "degraded"
        result["ollama_error"] = str(exc)[:120]

    # SMTP (active config present)
    try:
        from database import SessionLocal, SMTPConfig
        from sqlalchemy import select

        with SessionLocal() as db:
            cfg = db.scalar(
                select(SMTPConfig)
                .where(SMTPConfig.is_active.is_(True))
                .order_by(SMTPConfig.id.desc())
            )
        if not cfg:
            # env override
            if os.getenv("SMTP_HOST", "").strip():
                result["smtp"] = "env_configured"
            else:
                result["smtp"] = "not_configured"
        else:
            result["smtp"] = "active"
    except Exception as exc:
        result["smtp"] = "error"
        result["smtp_error"] = str(exc)[:80]

    # Jira
    if not JIRA_ENABLED:
        result["jira_config"] = "disabled"
    elif not (JIRA_BASE_URL or "").strip():
        result["jira_config"] = "not_configured"
        result["status"] = "degraded"
    else:
        result["jira_config"] = "configured"
        try:
            r = requests.get(
                f"{JIRA_BASE_URL.rstrip('/')}/status",
                timeout=5,
            )
            # many Jira servers expose /status
            if r.status_code < 500:
                result["jira_config"] = "reachable"
            else:
                result["jira_config"] = f"http_{r.status_code}"
        except Exception:
            result["jira_config"] = "configured"  # URL set; may need auth for ping

    # Confluence
    base = (CONFLUENCE_BASE_URL or "").strip().rstrip("/")
    if not base:
        result["confluence_config"] = "not_configured"
    else:
        result["confluence_config"] = "configured"
        try:
            r = requests.get(f"{base}/status", timeout=5)
            if r.status_code < 500:
                result["confluence_config"] = "reachable"
        except Exception:
            result["confluence_config"] = "configured"

    return result
