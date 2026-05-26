"""Minimal SMTP email sender for transactional emails (password reset).

If SMTP is not configured (SMTP_HOST unset), the reset link is written to the
application log so local dev still works without a mail server.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


def _smtp_config() -> Optional[dict]:
    """Return SMTP config dict or None if SMTP_HOST is not set."""
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_addr": (
            os.getenv("SMTP_FROM", "").strip()
            or os.getenv("SMTP_USER", "").strip()
            or "noreply@example.com"
        ),
    }


def send_password_reset_email(*, to_email: str, reset_link: str) -> None:
    """Send a password-reset email.

    Falls back to log output when SMTP is not configured (development mode).
    SMTP errors are caught and logged — the caller always gets a clean return
    so the API endpoint can return 200 regardless of mail delivery status.
    """
    cfg = _smtp_config()
    if cfg is None:
        logger.info(
            "email_service smtp_not_configured — password reset link (dev only): "
            "to=%s link=%s",
            to_email,
            reset_link,
        )
        return

    # Log what config is being used (never log the password).
    logger.info(
        "email_service smtp_attempt host=%s port=%s user=%s from_addr=%s to=%s",
        cfg["host"],
        cfg["port"],
        cfg["user"] or "(empty)",
        cfg["from_addr"],
        to_email,
    )

    subject = "Obnovení hesla — Marketingový přehled"
    body_text = (
        "Dobrý den,\n\n"
        f"klikněte na odkaz pro obnovení hesla:\n{reset_link}\n\n"
        "Odkaz je platný 1 hodinu. Pokud jste o obnovení nežádali, "
        "ignorujte tento email."
    )
    body_html = (
        "<html><body>"
        "<p>Dobrý den,</p>"
        "<p>klikněte na odkaz pro obnovení hesla:<br>"
        f'<a href="{reset_link}">{reset_link}</a></p>'
        "<p>Odkaz je platný 1 hodinu. Pokud jste o obnovení nežádali, "
        "ignorujte tento email.</p>"
        "</body></html>"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_addr"], [to_email], msg.as_string())
        logger.info(
            "email_service smtp_sent host=%s from=%s to=%s",
            cfg["host"],
            cfg["from_addr"],
            to_email,
        )
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "email_service smtp_auth_failed host=%s port=%s user=%s — "
            "check SMTP_USER and SMTP_PASSWORD on Render",
            cfg["host"],
            cfg["port"],
            cfg["user"] or "(empty)",
            exc_info=True,
        )
    except smtplib.SMTPConnectError:
        logger.error(
            "email_service smtp_connect_failed host=%s port=%s — "
            "check SMTP_HOST and SMTP_PORT on Render",
            cfg["host"],
            cfg["port"],
            exc_info=True,
        )
    except smtplib.SMTPRecipientsRefused as exc:
        logger.error(
            "email_service smtp_recipient_refused to=%s recipients=%s",
            to_email,
            exc.recipients,
            exc_info=True,
        )
    except Exception:
        logger.exception(
            "email_service smtp_error host=%s port=%s from=%s to=%s",
            cfg["host"],
            cfg["port"],
            cfg["from_addr"],
            to_email,
        )
    # Do not re-raise — endpoint always returns 200 to avoid email enumeration
