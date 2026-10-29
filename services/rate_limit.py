"""In-process rate limiting for auth and sensitive actions.

Uses a sliding window in memory (per worker). For multi-replica deploys,
prefer Redis later; this still stops casual brute-force on a single instance.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque

_lock = threading.Lock()
_buckets: dict[str, Deque[float]] = defaultdict(deque)


class RateLimitExceeded(Exception):
    def __init__(self, message: str = "Too many attempts. Try again later.", *, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


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
