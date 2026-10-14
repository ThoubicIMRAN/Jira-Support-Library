"""Application configuration.

Loads from environment (and .env in development). All values have safe
defaults for development; production-critical values are validated and
emit warnings (or raise) if misconfigured.
"""
from __future__ import annotations

import json
import logging
import os
import warnings
from pathlib import Path

from dotenv import load_dotenv


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Environment detection
# --------------------------------------------------------------------------- #
ENV = os.getenv("ENV", "development").strip().lower()
APP_ENV = os.getenv("APP_ENV", ENV).strip().lower()
IS_PRODUCTION = APP_ENV == "production"

if APP_ENV not in {"development", "production", "test"}:
    APP_ENV = "development"


# --------------------------------------------------------------------------- #
# Base directory + .env
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
_ENV_FILE = BASE_DIR / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)


# --------------------------------------------------------------------------- #
# Typed env readers
# --------------------------------------------------------------------------- #
def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "t", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "f", "no", "n", "off"):
        return False
    warnings.warn(
        f"{name}={raw!r} is not a boolean; using default {default}.",
        stacklevel=2,
    )
    return default


def _int_env(name: str, default: int, *, min_value: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        warnings.warn(
            f"{name}={raw!r} is not an integer; using default {default}.",
            stacklevel=2,
        )
        return default
    return max(min_value, value)


def _csv_env(name: str, *, strip_at: bool = False) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    values = (x.strip().lower() for x in raw.split(","))
    if strip_at:
        values = (v.lstrip("@") for v in values)
    return tuple(v for v in values if v)


# --------------------------------------------------------------------------- #
# App identity
# --------------------------------------------------------------------------- #
APP_NAME = "Jira Support Library"

_raw_root = os.getenv("APP_ROOT_PATH", "").strip().strip("/")
APP_ROOT_PATH = _raw_root
if APP_ROOT_PATH:
    os.environ.setdefault(
        "STREAMLIT_SERVER_BASE_URL_PATH", f"/{APP_ROOT_PATH}"
    )

_default_app_url = "http://localhost:8501" + (
    f"/{APP_ROOT_PATH}" if APP_ROOT_PATH else ""
)
APP_URL = os.getenv("APP_URL", _default_app_url).rstrip("/")


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'data' / 'jira_support_library.db'}",
)

if DATABASE_URL.startswith("sqlite:///"):
    _db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    _db_path.parent.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Security
# --------------------------------------------------------------------------- #
_raw_secret = os.getenv("APP_SECRET_KEY", "").strip()
if not _raw_secret:
    if IS_PRODUCTION:
        _raw_secret = "development-only-change-me"
    else:
        warnings.warn(
            "APP_SECRET_KEY is not set; using an insecure development default. "
            "Do not deploy this to production.",
            stacklevel=2,
        )
        _raw_secret = "development-only-change-me"
APP_SECRET_KEY = _raw_secret

ALLOW_DEFAULT_BOOTSTRAP_ADMIN = _bool_env(
    "ALLOW_DEFAULT_BOOTSTRAP_ADMIN", not IS_PRODUCTION
)

SESSION_TIMEOUT_MINUTES = _int_env("SESSION_TIMEOUT_MINUTES", 60, min_value=0)  # 0 = no idle timeout
SESSION_ABSOLUTE_HOURS = _int_env("SESSION_ABSOLUTE_HOURS", 12, min_value=1)

LOGIN_MAX_FAILURES = _int_env("LOGIN_MAX_FAILURES", 5, min_value=1)
LOGIN_LOCK_MINUTES = _int_env("LOGIN_LOCK_MINUTES", 15, min_value=1)
RESET_TOKEN_MINUTES = _int_env("RESET_TOKEN_MINUTES", 60, min_value=1)
INVITATION_TOKEN_HOURS = _int_env("INVITATION_TOKEN_HOURS", 24, min_value=1)


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
ROLES: tuple[str, ...] = ("superadmin", "admin", "manager", "user")
ROLE_SET: frozenset[str] = frozenset(ROLES)
PRIVILEGED_ROLES: frozenset[str] = frozenset({"superadmin", "admin"})


# --------------------------------------------------------------------------- #
# OAuth — Microsoft
# --------------------------------------------------------------------------- #
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "").strip()
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "").strip()
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "organizations").strip()
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI", APP_URL).rstrip("/")
MS_ALLOWED_TENANT_IDS = _csv_env("MS_ALLOWED_TENANT_IDS")

_raw_role_map = os.getenv("MS_APP_ROLE_MAP", "").strip()
if _raw_role_map:
    try:
        MS_APP_ROLE_MAP: dict[str, str] = json.loads(_raw_role_map)
    except json.JSONDecodeError:
        warnings.warn(
            "MS_APP_ROLE_MAP is not valid JSON; ignoring.", stacklevel=2
        )
        MS_APP_ROLE_MAP = {}
else:
    MS_APP_ROLE_MAP = {}

if bool(MS_CLIENT_ID) != bool(MS_CLIENT_SECRET):
    warnings.warn(
        "MS_CLIENT_ID and MS_CLIENT_SECRET must both be set or both be "
        "empty. Microsoft sign-in will be unavailable.",
        stacklevel=2,
    )


# --------------------------------------------------------------------------- #
# OAuth — Google
# --------------------------------------------------------------------------- #
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", APP_URL).rstrip("/")

if bool(GOOGLE_CLIENT_ID) != bool(GOOGLE_CLIENT_SECRET):
    warnings.warn(
        "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must both be set or "
        "both be empty. Google sign-in will be unavailable.",
        stacklevel=2,
    )


# --------------------------------------------------------------------------- #
# OAuth — common
# --------------------------------------------------------------------------- #
OAUTH_AUTO_CREATE = _bool_env("OAUTH_AUTO_CREATE", True)
OAUTH_ALLOWED_DOMAINS = _csv_env("OAUTH_ALLOWED_DOMAINS", strip_at=True)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
HEALTH_TOKEN = os.getenv("HEALTH_TOKEN", "").strip()


# --------------------------------------------------------------------------- #
# Backups
# --------------------------------------------------------------------------- #
BACKUP_DIR = str(
    Path(os.getenv("BACKUP_DIR", str(BASE_DIR / "backups"))).expanduser()
)
BACKUP_RETENTION_DAYS = _int_env("BACKUP_RETENTION_DAYS", 30, min_value=1)


# --------------------------------------------------------------------------- #
# Startup report
# --------------------------------------------------------------------------- #
def validate_production_settings() -> None:
    if APP_ENV != "production":
        return
    if not APP_SECRET_KEY or APP_SECRET_KEY == "development-only-change-me":
        raise RuntimeError("APP_SECRET_KEY must be set explicitly in production.")


def log_config_summary() -> None:
    """Log the effective configuration (no secrets). Call after logging setup."""
    logger.info(
        "Config loaded",
        extra={
            "env": APP_ENV,
            "app_url": APP_URL,
            "root_path": APP_ROOT_PATH or "/",
            "database_backend": DATABASE_URL.split("://", 1)[0],
            "microsoft_oauth": bool(MS_CLIENT_ID and MS_CLIENT_SECRET),
            "google_oauth": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
            "session_timeout_minutes": SESSION_TIMEOUT_MINUTES,
            "oauth_allowed_domains": len(OAUTH_ALLOWED_DOMAINS),
        },
    )


validate_production_settings()

# --------------------------------------------------------------------------- #
# Local AI (Ollama – Docker service hostname "ollama")
# --------------------------------------------------------------------------- #
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://ollama:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
AI_SIMILARITY_THRESHOLD = float(os.getenv("AI_SIMILARITY_THRESHOLD", "0.82"))
AI_REQUEST_TIMEOUT = float(os.getenv("AI_REQUEST_TIMEOUT", "180"))

# --------------------------------------------------------------------------- #
# Jira integration (one site, many projects; per-user credentials)
# --------------------------------------------------------------------------- #
JIRA_ENABLED = _bool_env("JIRA_ENABLED", True)
JIRA_PRODUCT = os.getenv("JIRA_PRODUCT", "cloud").strip().lower()  # cloud | server
if JIRA_PRODUCT not in {"cloud", "server"}:
    JIRA_PRODUCT = "cloud"
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")
JIRA_REQUEST_TIMEOUT = float(os.getenv("JIRA_REQUEST_TIMEOUT", "30"))
if IS_PRODUCTION and JIRA_BASE_URL and not JIRA_BASE_URL.startswith("https://"):
    logger.warning("JIRA_BASE_URL is not HTTPS; Jira tokens would be sent unencrypted.")

CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "").strip().rstrip("/")
CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL", "").strip()
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "").strip()

# --------------------------------------------------------------------------- #
# Safety limits for Jira write operations
# --------------------------------------------------------------------------- #
BOOTSTRAP_ADMIN_USERNAME = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin").strip() or "admin"
BULK_MAX_TICKETS = max(1, int(os.getenv("BULK_MAX_TICKETS", "25")))
BULK_DELAY_SECONDS = max(0.0, float(os.getenv("BULK_DELAY_SECONDS", "0.3")))
JIRA_MAX_ATTACHMENT_MB = max(1, int(os.getenv("JIRA_MAX_ATTACHMENT_MB", "10")))
