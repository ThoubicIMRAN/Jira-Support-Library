"""Low-level Jira REST client (Cloud + Server/DC).

Auth:
  Cloud  → Basic (email, API token)
  Server → Bearer PAT  (or Basic if email provided)
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class JiraError(Exception):
    """Raised for non-success Jira API responses."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def adf_document(text: str) -> dict:
    """Plain text -> Atlassian Document Format.

    Blank lines become paragraphs and single newlines become hard breaks;
    a single text node containing "\\n" would render as one run-on line.
    """
    paragraphs = []
    for block in (text or "").replace("\r\n", "\n").split("\n\n"):
        nodes = []
        for i, line in enumerate(block.split("\n")):
            if i:
                nodes.append({"type": "hardBreak"})
            if line:
                nodes.append({"type": "text", "text": line})
        paragraphs.append({"type": "paragraph", "content": nodes} if nodes else {"type": "paragraph"})
    return {"type": "doc", "version": 1, "content": paragraphs or [{"type": "paragraph"}]}


class JiraClient:
    def __init__(
        self,
        *,
        base_url: str,
        product: str,
        email: str | None,
        secret: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.product = (product or "cloud").lower()
        self.email = (email or "").strip() or None
        self.secret = secret
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        if self.product == "cloud":
            if not self.email:
                raise JiraError("Cloud auth requires email + API token.")
            self._session.auth = (self.email, self.secret)
        else:
            # Server/DC: prefer PAT as Bearer
            self._session.headers["Authorization"] = f"Bearer {self.secret}"

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        try:
            resp = self._session.request(
                method,
                self._url(path),
                json=json,
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise JiraError(f"Network error talking to Jira: {exc}") from exc

        if resp.status_code in (204, 201) and not resp.content:
            return None

        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("message") or body.get("errorMessages") or body
            except Exception:
                detail = (resp.text or "")[:300]
            raise JiraError(
                f"Jira API {resp.status_code}: {detail}",
                status=resp.status_code,
                payload=detail,
            )

        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def myself(self) -> dict:
        return self.get("/rest/api/3/myself" if self.product == "cloud" else "/rest/api/2/myself")

    def get_issue(self, key: str, fields: str | None = None) -> dict:
        api = "3" if self.product == "cloud" else "2"
        params = {}
        if fields:
            params["fields"] = fields
        return self.get(f"/rest/api/{api}/issue/{key}", params=params or None)

    def add_comment(
        self,
        key: str,
        body_text: str,
        *,
        internal: bool = False,
        internal_role: str | None = None,
    ) -> dict:
        """Public vs internal (Jira Service Management style).

        internal=True tries Service Desk API with public=false (agent-only),
        not restricted to Administrators role.
        """
        api = "3" if self.product == "cloud" else "2"
        text = body_text or ""

        if internal:
            sd_payload = (
                {"body": adf_document(text), "public": False}
                if self.product == "cloud"
                else {"body": text, "public": False}
            )
            try:
                return self.post(f"/rest/servicedeskapi/request/{key}/comment", json=sd_payload)
            except JiraError:
                if self.product == "cloud":
                    payload = {"body": adf_document(text)}
                else:
                    payload = {"body": text}
                if internal_role:
                    payload["visibility"] = {"type": "role", "value": internal_role}
                return self.post(f"/rest/api/{api}/issue/{key}/comment", json=payload)

        # Customer-visible
        if self.product == "cloud":
            payload = {"body": adf_document(text)}
            sd_payload = {"body": adf_document(text), "public": True}
        else:
            payload = {"body": text}
            sd_payload = {"body": text, "public": True}
        try:
            return self.post(f"/rest/servicedeskapi/request/{key}/comment", json=sd_payload)
        except JiraError:
            return self.post(f"/rest/api/{api}/issue/{key}/comment", json=payload)




    def add_watcher(self, key: str, account_or_username: str) -> None:
        """Add a watcher / participant. Cloud uses accountId; Server/DC uses username."""
        api = "3" if self.product == "cloud" else "2"
        url = self._url(f"/rest/api/{api}/issue/{key}/watchers")
        # Jira expects a raw JSON string body: "username" or "accountId"
        ident = (account_or_username or "").strip()
        if not ident:
            raise JiraError("Watcher identity is empty.")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = self._session.auth
        bearer = self._session.headers.get("Authorization")
        if bearer:
            headers["Authorization"] = bearer
        import json as _json
        resp = self._session.post(
            url,
            headers=headers,
            data=_json.dumps(ident),
            auth=auth,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise JiraError(
                f"Add watcher failed HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                status=resp.status_code,
            )

    def search_users(self, query: str, max_results: int = 10) -> list[dict]:
        """User picker for mentions / watchers."""
        q = (query or "").strip()
        if not q:
            return []
        api = "3" if self.product == "cloud" else "2"
        if self.product == "cloud":
            data = self.get(
                f"/rest/api/{api}/user/search",
                params={"query": q, "maxResults": max_results},
            )
        else:
            data = self.get(
                f"/rest/api/{api}/user/search",
                params={"username": q, "maxResults": max_results},
            )
        if not isinstance(data, list):
            return []
        out = []
        for u in data:
            out.append({
                "accountId": u.get("accountId") or "",
                "name": u.get("name") or "",
                "displayName": u.get("displayName") or u.get("name") or "",
                "emailAddress": u.get("emailAddress") or "",
            })
        return out

    def add_attachment(
        self,
        key: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict:
        api = "3" if self.product == "cloud" else "2"
        url = self._url(f"/rest/api/{api}/issue/{key}/attachments")
        headers = {"Accept": "application/json", "X-Atlassian-Token": "no-check"}
        auth = self._session.auth
        bearer = self._session.headers.get("Authorization")
        if bearer:
            headers["Authorization"] = bearer
        files = {"file": (filename, content, content_type or "application/octet-stream")}
        resp = self._session.post(
            url, headers=headers, files=files, auth=auth, timeout=self.timeout
        )
        if resp.status_code >= 400:
            raise JiraError(
                f"Attachment failed HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                status=resp.status_code,
            )
        data = resp.json() if resp.content else {}
        return data[0] if isinstance(data, list) and data else (data or {})



    def add_worklog(
        self,
        key: str,
        *,
        time_spent: str,
        comment: str | None = None,
        started: str | None = None,
    ) -> dict:
        api = "3" if self.product == "cloud" else "2"
        payload: dict[str, Any] = {"timeSpent": time_spent}
        if comment:
            if self.product == "cloud":
                payload["comment"] = adf_document(comment)
            else:
                payload["comment"] = comment
        if started:
            payload["started"] = started
        return self.post(f"/rest/api/{api}/issue/{key}/worklog", json=payload)

    def list_transitions(self, key: str) -> list[dict]:
        api = "3" if self.product == "cloud" else "2"
        data = self.get(f"/rest/api/{api}/issue/{key}/transitions")
        return list((data or {}).get("transitions") or [])

    def do_transition(self, key: str, transition_id: str) -> None:
        api = "3" if self.product == "cloud" else "2"
        self.post(
            f"/rest/api/{api}/issue/{key}/transitions",
            json={"transition": {"id": str(transition_id)}},
        )


    def search_issues(self, jql: str, *, max_results: int = 10, fields: str = "summary,status,created") -> list[dict]:
        api = "3" if self.product == "cloud" else "2"
        data = self.get(
            f"/rest/api/{api}/search",
            params={"jql": jql, "maxResults": max_results, "fields": fields},
        )
        return list((data or {}).get("issues") or [])
