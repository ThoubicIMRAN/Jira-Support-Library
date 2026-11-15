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
                "mismatch or corrupt ciphertext). Re-save the password in Admin Settings."
            ) from exc
        use_tls, use_ssl = _normalize_flags(cfg.port, bool(cfg.use_tls), bool(cfg.use_ssl))
        return {
            "host": (cfg.host or "").strip(),
            "port": int(cfg.port or 587),
            "username": (cfg.username or "").strip(),
            "password": password,
            "sender_email": (cfg.sender_email or cfg.username or "").strip(),
            "sender_name": (cfg.sender_name or APP_NAME).strip() or APP_NAME,
            "use_tls": use_tls,
            "use_ssl": use_ssl,
            "source": "database",
        }

def send_email(to_email, subject, html_body):
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        raise RuntimeError("Recipient email is missing or invalid.")

    cfg = _load_config()
    host = cfg["host"]
    port = int(cfg["port"])
    username = cfg["username"]
    password = cfg["password"]
    sender_email = cfg["sender_email"] or username
    sender_name = cfg["sender_name"]
    use_tls, use_ssl = _normalize_flags(port, cfg["use_tls"], cfg["use_ssl"])

    if not host:
        raise RuntimeError("SMTP host is empty.")
    if not sender_email:
        raise RuntimeError("Sender email is empty. Set From email in SMTP settings.")

    try:
        socket.getaddrinfo(host, port)
    except socket.gaierror as exc:
        raise RuntimeError(f"Cannot resolve SMTP host {host!r}: {exc}") from exc

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    timeout = float(os.getenv("SMTP_TIMEOUT", "30") or 30)
    client = None
    try:
        if use_ssl:
            context = ssl.create_default_context()
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
            client.ehlo()
            if use_tls:
                context = ssl.create_default_context()
                client.starttls(context=context)
                client.ehlo()

        if username:
            client.login(username, password or "")

        refused = client.sendmail(sender_email, [to_email], msg.as_string())
        if refused:
            raise RuntimeError(f"SMTP refused recipient(s): {refused}")

        logger.info(
            "Email sent via %s:%s (%s) to %s subject=%r",
            host, port, cfg.get("source"), to_email, subject,
        )
        return True

    except smtplib.SMTPAuthenticationError as exc:
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
