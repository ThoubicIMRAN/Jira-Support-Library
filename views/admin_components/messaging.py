from __future__ import annotations

import logging
import streamlit as st
from sqlalchemy import select

from database import SessionLocal, SMTPConfig
from email_service import branded_email, send_html_email
from utils.security import encrypt_secret

log = logging.getLogger(__name__)


def render(user) -> None:
    if user.role != "superadmin":
        st.error("Only superadmins can configure SMTP.")
        return

    st.subheader("SMTP & Messaging")
    st.caption("Configure the mail server used for password resets, invitations and system notifications.")

    with SessionLocal() as db:
        cfg = db.scalar(select(SMTPConfig).order_by(SMTPConfig.id.desc()))
        values = {
            "host": cfg.host if cfg else "", "port": cfg.port if cfg else 587,
            "username": cfg.username if cfg else "", "sender_email": cfg.sender_email if cfg else "",
            "sender_name": cfg.sender_name if cfg else "Jira Support Library",
            "use_tls": cfg.use_tls if cfg else True, "use_ssl": cfg.use_ssl if cfg else False,
            "active": cfg.is_active if cfg else True,
        }

    with st.form("admin_center_smtp"):
        c1, c2 = st.columns([3, 1])
        host = c1.text_input("SMTP server", values["host"])
        port = c2.number_input("Port", min_value=1, max_value=65535, value=int(values["port"]))
        username = st.text_input("Username", values["username"])
        password = st.text_input("Password", type="password", help="Leave blank to keep the existing encrypted password.")
        c3, c4 = st.columns(2)
        sender_email = c3.text_input("Sender email", values["sender_email"])
        sender_name = c4.text_input("Sender name", values["sender_name"])
        c5, c6, c7 = st.columns(3)
        use_tls = c5.checkbox("STARTTLS", values["use_tls"])
        use_ssl = c6.checkbox("Implicit SSL", values["use_ssl"])
        active = c7.checkbox("Active", values["active"])
        save = st.form_submit_button("Save SMTP configuration", type="primary")

    if save:
        if not host.strip() or not sender_email.strip():
            st.error("SMTP server and sender email are required.")
        elif use_tls and use_ssl:
            st.error("Choose STARTTLS or implicit SSL, not both.")
        else:
            with SessionLocal() as db:
                row = db.scalar(select(SMTPConfig).order_by(SMTPConfig.id.desc()))
                if row is None:
                    row = SMTPConfig(host=host.strip(), port=int(port), sender_email=sender_email.strip())
                    db.add(row)
                row.host = host.strip(); row.port = int(port); row.username = username.strip()
                row.sender_email = sender_email.strip(); row.sender_name = sender_name.strip() or "Jira Support Library"
                row.use_tls = use_tls; row.use_ssl = use_ssl; row.is_active = active
                if password:
                    row.encrypted_password = encrypt_secret(password)
                db.commit()
            st.success("SMTP configuration saved securely.")
            st.rerun()

    with st.form("admin_center_smtp_test"):
        recipient = st.text_input("Test recipient email")
        test = st.form_submit_button("Send test email")
    if test:
        if not recipient.strip():
            st.error("Enter a test recipient email address.")
        else:
            try:
                send_html_email(recipient.strip(), "Jira Support Library SMTP test", branded_email("SMTP test successful", "<p>Your SMTP configuration is working.</p>"))
                st.success("Test email sent successfully.")
            except Exception:
                log.exception("SMTP test failed for administrator %s", user.id)
                st.error("Test email failed. Verify the SMTP settings and credentials.")
