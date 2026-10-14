"""Confluence page fetch — Server/DC + Cloud, multiple auth modes."""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import requests

from config import JIRA_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

SPACE_PAGES_RE = re.compile(r"/spaces/[^/]+/pages/(\d+)", re.I)
PAGE_ID_RE = re.compile(r"/pages/(\d+)", re.I)
VIEWPAGE_RE = re.compile(r"[?&]pageId=(\d+)", re.I)


class ConfluenceError(Exception):
    pass


def parse_page_id(url: str) -> str | None:
    text = (url or "").strip()
    for rx in (SPACE_PAGES_RE, PAGE_ID_RE, VIEWPAGE_RE):
        m = rx.search(text)
        if m:
            return m.group(1)
    return text if text.isdigit() else None


def derive_base_url(url: str) -> str | None:
    text = (url or "").strip()
    if not text.startswith("http"):
        return None
    p = urlparse(text)
    if p.scheme and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    return None


def _is_html(resp: requests.Response) -> bool:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    body = (resp.text or "").lstrip()[:40].lower()
    return "html" in ctype or body.startswith("<!doctype") or body.startswith("<html")


def _safe_json(resp: requests.Response) -> dict[str, Any]:
    text = (resp.text or "").strip()
    if not text or _is_html(resp) or not (text.startswith("{") or text.startswith("[")):
        raise ConfluenceError(
            f"HTTP {resp.status_code}: non-JSON response (login page or gateway). "
            "API auth is not accepted for this Confluence site."
        )
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise ConfluenceError(f"Invalid JSON (HTTP {resp.status_code}): {exc}") from exc
    if not isinstance(data, dict):
        raise ConfluenceError("Unexpected JSON shape from Confluence.")
    return data


def _attempts(username: str | None, secret: str) -> list[tuple[str, dict, Any]]:
    """(label, headers, auth) combinations for Server/DC PATs."""
    secret = (secret or "").strip()
    user = (username or "").strip()
    out: list[tuple[str, dict, Any]] = []

    # Official Confluence Server/DC PAT style
    out.append(("Bearer", {"Authorization": f"Bearer {secret}"}, None))
    # Some proxies expect Token scheme
    out.append(("Token", {"Authorization": f"Token {secret}"}, None))

    if user:
        out.append(("Basic", {}, (user, secret)))
        if "@" in user:
            out.append(("Basic-local", {}, (user.split("@", 1)[0], secret)))

    return out


def fetch_page(
    url_or_id: str,
    *,
    base_url: str,
    email: str | None,
    secret: str,
) -> dict[str, Any]:
    derived = derive_base_url(url_or_id)
    base = (derived or base_url or "").rstrip("/")
    if not base:
        raise ConfluenceError("Confluence base URL missing. Paste a full https://… page link.")
    if not (secret or "").strip():
        raise ConfluenceError(
            "No Confluence token configured. "
            "Settings → Jira connection → Confluence: uncheck 'Use Jira credentials', "
            "enter Confluence username + Personal Access Token, Save."
        )

    page_id = parse_page_id(url_or_id)
    if not page_id:
        raise ConfluenceError("Could not parse page id from the URL (.../pages/12345/...).")

    paths = [
        f"{base}/rest/api/content/{page_id}",
        f"{base}/wiki/rest/api/content/{page_id}",
    ]
    params = {"expand": "body.storage,space,version,body.view"}
    accept = {"Accept": "application/json"}

    statuses: list[str] = []
    data: dict[str, Any] | None = None

    for api_url in paths:
        for label, extra_headers, auth in _attempts(email, secret):
            headers = {**accept, **extra_headers}
            try:
                resp = requests.get(
                    api_url,
                    params=params,
                    headers=headers,
                    auth=auth,
                    timeout=JIRA_REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                statuses.append(f"{label}: network {exc}")
                continue

            code = resp.status_code
            if code in (401, 403):
                statuses.append(f"{label}: HTTP {code}")
                continue
            if code == 404:
                statuses.append(f"{label}: HTTP 404")
                continue
            if code >= 400:
                statuses.append(f"{label}: HTTP {code}")
                continue
            try:
                data = _safe_json(resp)
                logger.info("Confluence success via %s %s", label, api_url)
                break
            except ConfluenceError as exc:
                statuses.append(f"{label}: {exc}")
                continue
        if data is not None:
            break

    if data is None:
        raise ConfluenceError(
            "Confluence API rejected all auth methods (401/403). "
            "This Confluence instance requires a valid **Confluence** Personal Access Token "
            "for the user who can open the page in the browser. "
            "If your company uses SSO-only API lockdown, use **Paste page text** in the dialog instead. "
            f"Details: {'; '.join(statuses[:8])}"
        )

    title = data.get("title") or "Confluence page"
    body = data.get("body") or {}
    raw = (body.get("storage") or {}).get("value") or (body.get("view") or {}).get("value") or ""
    excerpt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()[:1200]
    space = (data.get("space") or {}).get("key") or ""
    link = url_or_id if str(url_or_id).startswith("http") else f"{base}/spaces/{space}/pages/{page_id}"
    return {"id": page_id, "title": title, "excerpt": excerpt, "link": link, "base_url": base}
