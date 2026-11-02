"""Optional Active Directory / Entra enrichment for ticket reporters.

Disabled by default. Enable with AD_ENABLED=true and configure LDAP/Graph later.
Until then ad_enabled() is False and enrich_from_reporter() returns None.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def ad_enabled() -> bool:
    return os.getenv("AD_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def enrich_from_reporter(
    reporter_display_name: str,
    reporter_username: str = "",
) -> dict[str, Any] | None:
    """Look up directory attributes for a Jira reporter.

    Returns dict with keys such as display_name, username, title, department, email,
    or None when AD is off or no match is found.
    """
    if not ad_enabled():
        return None
    # Placeholder: real LDAP/Graph integration lands in Phase 4.
    logger.debug(
        "AD enrichment requested for display=%r user=%r (not implemented)",
        reporter_display_name,
        reporter_username,
    )
    return None
