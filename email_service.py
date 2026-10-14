"""Robust SMTP send + diagnostics for invitations, resets, and test mail."""
from __future__ import annotations

import logging
import os
import smtplib
import socket
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from sqlalchemy import select

from config import APP_NAME
from database import SMTPConfig, SessionLocal
from utils.security import decrypt_secret

logger = logging.getLogger(__name__)


def get_active_smtp(db):
    return db.scalar(
        select(SMTPConfig)
        .where(SMTPConfig.is_active.is_(True))
        .order_by(SMTPConfig.id.desc())
    )


def _env_smtp_override() -> dict | None:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "username": os.getenv("SMTP_USERNAME", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "sender_email": os.getenv("SMTP_FROM", os.getenv("SMTP_USERNAME", "")).strip(),
        "sender_name": os.getenv("SMTP_FROM_NAME", APP_NAME).strip() or APP_NAME,
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
        "use_ssl": os.getenv("SMTP_USE_SSL", "false").lower() in ("1", "true", "yes"),
    }


def _normalize_flags(port: int, use_tls: bool, use_ssl: bool) -> tuple[bool, bool]:
    port = int(port)
    if use_tls and use_ssl:
        return (False, True) if port == 465 else (True, False)
    if port == 465:
        return False, True
    if port == 587 and not use_tls and not use_ssl:
        return True, False
    return bool(use_tls), bool(use_ssl)


def _load_config() -> dict:
    env = _env_smtp_override()
    if env:
        return {**env, "source": "env"}

    with SessionLocal() as db:
        cfg = get_active_smtp(db)
        if not cfg:
            raise RuntimeError(
                "No active SMTP configuration. "
                "Open Admin Settings → Security & SMTP, fill the form, tick Active, and Save. "
                "Or set SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD in the environment."
            )
        try:
            password = decrypt_secret(cfg.encrypted_password or "") or ""
        except Exception as exc:
            logger.exception("SMTP password decrypt failed")
            raise RuntimeError(
                "Could not decrypt the stored SMTP password (FERNET_KEY / APP_SECRET_KEY "
                "may have changed). Re-enter the password and Save, or set SMTP_PASSWORD in env."
            ) from exc

        return {
            "host": (cfg.host or "").strip(),
            "port": int(cfg.port or 587),
            "username": (cfg.username or "").strip(),
            "password": password,
            "sender_email": (cfg.sender_email or "").strip(),
            "sender_name": (cfg.sender_name or APP_NAME).strip() or APP_NAME,
            "use_tls": bool(cfg.use_tls),
            "use_ssl": bool(cfg.use_ssl),
            "source": "database",
        }


def _open_client(host: str, port: int, use_tls: bool, use_ssl: bool, timeout: float = 30.0):
    context = ssl.create_default_context()
    if use_ssl:
        client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        client.ehlo()
        return client
    client = smtplib.SMTP(host, port, timeout=timeout)
    client.ehlo()
    if use_tls:
        client.starttls(context=context)
        client.ehlo()
    return client


def diagnose_smtp() -> dict:
    info: dict = {"ok": False, "steps": []}
    try:
        cfg = _load_config()
    except Exception as exc:
        info["steps"].append(f"Config: FAIL — {exc}")
        info["error"] = str(exc)
        return info

    info["source"] = cfg["source"]
    info["host"] = cfg["host"]
    info["port"] = cfg["port"]
    use_tls, use_ssl = _normalize_flags(cfg["port"], cfg["use_tls"], cfg["use_ssl"])
    info["mode"] = "SSL" if use_ssl else ("STARTTLS" if use_tls else "plain")
    info["steps"].append(f"Config OK (source={cfg['source']}, mode={info['mode']})")

    if not cfg["host"]:
        info["error"] = "SMTP host is empty"
        info["steps"].append("Host: FAIL — empty")
        return info

    try:
        socket.create_connection((cfg["host"], int(cfg["port"])), timeout=10).close()
        info["steps"].append(f"TCP {cfg['host']}:{cfg['port']}: OK")
    except OSError as exc:
        info["error"] = f"Cannot reach {cfg['host']}:{cfg['port']} — {exc}"
        info["steps"].append(f"TCP: FAIL — {exc}")
        return info

    client = None
    try:
        client = _open_client(cfg["host"], cfg["port"], use_tls, use_ssl, timeout=20)
        info["steps"].append("SMTP handshake: OK")
        if cfg["username"]:
            if not cfg["password"]:
                info["error"] = "Username set but password is empty"
                info["steps"].append("Auth: FAIL — no password")
                return info
            client.login(cfg["username"], cfg["password"])
            info["steps"].append("Auth (LOGIN): OK")
        else:
            info["steps"].append("Auth: skipped (no username)")
        info["ok"] = True
    except smtplib.SMTPAuthenticationError as exc:
        info["error"] = (
            "Authentication failed. For Microsoft 365 / Google use an app password "
            "if MFA is enabled. Username is usually the full email address."
        )
        info["steps"].append(f"Auth: FAIL — {exc}")
    except smtplib.SMTPException as exc:
        info["error"] = f"SMTP error: {exc}"
        info["steps"].append(f"SMTP: FAIL — {exc}")
    except OSError as exc:
        info["error"] = f"Network/TLS error: {exc}"
        info["steps"].append(f"Network: FAIL — {exc}")
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass
    return info


def send_html_email(recipient: str, subject: str, html_body: str) -> None:
    recipient = (recipient or "").strip()
    if not recipient or "@" not in recipient:
        raise RuntimeError("A valid recipient email address is required.")

    cfg = _load_config()
    if not cfg["host"] or not cfg["sender_email"]:
        raise RuntimeError("SMTP host and sender email are required.")

    if cfg["username"] and not cfg["password"]:
        raise RuntimeError(
            "SMTP username is set but password is empty. "
            "Re-save the password in Admin Settings or set SMTP_PASSWORD."
        )

    use_tls, use_ssl = _normalize_flags(cfg["port"], cfg["use_tls"], cfg["use_ssl"])

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = formataddr((cfg["sender_name"], cfg["sender_email"]))
    message["To"] = recipient
    message.attach(MIMEText(html_body, "html", "utf-8"))

    client = None
    try:
        client = _open_client(cfg["host"], int(cfg["port"]), use_tls, use_ssl, timeout=30)
        if cfg["username"]:
            client.login(cfg["username"], cfg["password"])
        refused = client.sendmail(cfg["sender_email"], [recipient], message.as_string())
        if refused:
            raise RuntimeError(f"Server refused recipients: {refused}")
    except smtplib.SMTPAuthenticationError as exc:
        logger.exception("SMTP auth failed")
        raise RuntimeError(
            "SMTP authentication failed. Check username/password "
            "(Office 365 / Gmail often require an app password with MFA)."
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise RuntimeError(f"Recipient refused by server: {exc}") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise RuntimeError(
            f"Sender refused. From address must be allowed on this SMTP account: {exc}"
        ) from exc
    except smtplib.SMTPConnectError as exc:
        raise RuntimeError(
            f"Could not connect to {cfg['host']}:{cfg['port']}. "
            "Check host, port, firewall, and SSL vs STARTTLS."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(f"SMTP connection timed out ({cfg['host']}:{cfg['port']}).") from exc
    except ssl.SSLError as exc:
        raise RuntimeError(
            f"TLS/SSL error: {exc}. Try port 587 + STARTTLS, or port 465 + Implicit SSL."
        ) from exc
    except OSError as exc:
        logger.exception("SMTP network error")
        raise RuntimeError(f"SMTP network error: {exc}") from exc
    except smtplib.SMTPException as exc:
        logger.exception("SMTP failed")
        raise RuntimeError(f"SMTP error: {exc}") from exc
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass


def branded_email(title, message, action_label=None, action_url=None):
    action = (
        f'<p><a href="{action_url}" style="display:inline-block;background:#0c46ce;'
        f'color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;'
        f'font-weight:700">{action_label}</a></p>'
        if action_label and action_url
        else ""
    )
    return (
        f'<!doctype html><html><body style="margin:0;background:#f0f4fb;'
        f'font-family:Arial,sans-serif;color:#111827">'
        f'<div style="max-width:640px;margin:30px auto;background:#fff;'
        f'border-radius:14px;overflow:hidden;border:1px solid #dde3f0">'
        f'<div style="background:#0c1f6e;color:#fff;padding:24px">'
        f'<h2 style="margin:0">🎯 {APP_NAME}</h2></div>'
        f'<div style="padding:28px"><h2>{title}</h2>'
        f'<div style="line-height:1.65">{message}</div>{action}'
        f'<p style="color:#657391;font-size:12px">'
        f'If you did not request this action, you can ignore this email.</p>'
        f'</div></div></body></html>'
    )
