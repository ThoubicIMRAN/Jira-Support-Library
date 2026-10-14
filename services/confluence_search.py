"""Search Confluence pages via CQL for resolution notes picker."""
from __future__ import annotations

import logging
from typing import Any

import requests

from config import JIRA_REQUEST_TIMEOUT
from services.confluence_client import ConfluenceError

logger = logging.getLogger(__name__)


def search_pages(user_id: int, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    from services.confluence_service import resolve_auth

    q = (query or "").strip()
    if len(q) < 2:
        return []
    auth = resolve_auth(user_id)
    base = (auth.get("base_url") or "").rstrip("/")
    secret = auth["secret"]
    if not base or not secret:
        raise ConfluenceError("Confluence is not configured.")

    # CQL text search
    cql = f'siteSearch ~ "{q.replace(chr(34), "")}" AND type=page'
    url = f"{base}/rest/api/content/search"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {secret}"}
    try:
        resp = requests.get(
            url,
            params={"cql": cql, "limit": limit, "expand": "space"},
            headers=headers,
            timeout=JIRA_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ConfluenceError(f"Confluence search network error: {exc}") from exc

    if resp.status_code >= 400:
        # fallback simpler CQL
        cql2 = f'title ~ "{q.replace(chr(34), "")}" AND type=page'
        resp = requests.get(
            url,
            params={"cql": cql2, "limit": limit, "expand": "space"},
            headers=headers,
            timeout=JIRA_REQUEST_TIMEOUT,
        )
    if resp.status_code >= 400:
        raise ConfluenceError(f"Confluence search HTTP {resp.status_code}")

    data = resp.json() if resp.content else {}
    results = []
    for r in data.get("results") or []:
        links = (r.get("_links") or {})
        webui = links.get("webui") or ""
        page_url = f"{base}{webui}" if webui.startswith("/") else (webui or f"{base}/pages/{r.get('id')}")
        results.append(
            {
                "id": str(r.get("id") or ""),
                "title": r.get("title") or "Untitled",
                "url": page_url,
                "space": ((r.get("space") or {}).get("key") or ""),
            }
        )
    return results
