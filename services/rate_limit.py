"""In-process rate limiting for auth and sensitive actions.

Uses a sliding window in memory (per worker). For multi-replica deploys,
prefer Redis later; this still stops casual brute-force on a single instance.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque

_lock = threading.Lock()
_buckets: dict[str, Deque[float]] = defaultdict(deque)


class RateLimitExceeded(ValueError):
    def __init__(self, message: str = "Too many attempts. Try again later.", *, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


def _rate_limits_disabled() -> bool:
    """Skip limiting in unit tests (APP_ENV=test or pytest)."""
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    if env == "test":
        return True
    if os.getenv("RATE_LIMIT_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return True
    # pytest sets this when running the test suite
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return False


def _prune(q: Deque[float], window: float, now: float) -> None:
    while q and q[0] <= now - window:
        q.popleft()


def check_rate_limit(
    key: str,
    *,
    max_calls: int,
    window_seconds: float,
) -> None:
    """Raise RateLimitExceeded if key exceeded max_calls in window."""
    if _rate_limits_disabled():
        return
    if max_calls <= 0 or window_seconds <= 0:
        return
    now = time.monotonic()
    with _lock:
        q = _buckets[key]
        _prune(q, window_seconds, now)
        if len(q) >= max_calls:
            retry = int(max(1, window_seconds - (now - q[0])))
            raise RateLimitExceeded(retry_after=retry)
        q.append(now)


def clear_rate_limit(key: str) -> None:
    with _lock:
        _buckets.pop(key, None)


# Presets used by the app
def limit_admin_action(actor_id: int) -> None:
    check_rate_limit(f"admin:{actor_id}", max_calls=30, window_seconds=60)


def limit_content_write(user_id: int) -> None:
    check_rate_limit(f"content:{user_id}", max_calls=60, window_seconds=60)


def limit_login(identity: str, client_ip: str = "") -> None:
    # Per identity: 10 / 15 min; per IP: 30 / 15 min
    check_rate_limit(f"login:id:{identity.lower()}", max_calls=10, window_seconds=900)
    if client_ip:
        check_rate_limit(f"login:ip:{client_ip}", max_calls=30, window_seconds=900)


def limit_signup(client_ip: str = "") -> None:
    check_rate_limit(f"signup:ip:{client_ip or 'unknown'}", max_calls=5, window_seconds=3600)


def limit_password_reset(email_or_ip: str) -> None:
    check_rate_limit(f"reset:{email_or_ip.lower()}", max_calls=5, window_seconds=3600)


def limit_sensitive_api(user_id: int, action: str = "api") -> None:
    check_rate_limit(f"{action}:uid:{user_id}", max_calls=120, window_seconds=60)


def limit_jira_write(user_id: int) -> None:
    """Jira comments, transitions, worklogs, attachments: 30 / minute."""
    check_rate_limit(f"jira_write:uid:{user_id}", max_calls=30, window_seconds=60)


def limit_avatar_upload(user_id: int) -> None:
    """Avatar uploads: 5 / minute."""
    check_rate_limit(f"avatar:uid:{user_id}", max_calls=5, window_seconds=60)


def limit_password_change(user_id: int) -> None:
    """Admin password resets + self password changes: 5 / 5 minutes."""
    check_rate_limit(f"pw_change:uid:{user_id}", max_calls=5, window_seconds=300)


def limit_bulk_run(user_id: int) -> None:
    """Bulk comment / bulk transition runs: 5 / 5 minutes."""
    check_rate_limit(f"bulk:uid:{user_id}", max_calls=5, window_seconds=300)


def limit_ai_call(user_id: int) -> None:
    """AI similarity / generation calls: 30 / minute."""
    check_rate_limit(f"ai:uid:{user_id}", max_calls=30, window_seconds=60)
