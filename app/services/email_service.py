"""Transactional email sender for auth notifications.

Primary:  Brevo HTTP API (BREVO_API_KEY) — works on all Render tiers (port 443).
Fallback: SMTP via smtplib (SMTP_HOST) — blocked by Render on free tier.
Dev:      No config → message written to application log only.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

_BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _brevo_api_key() -> str:
    return os.getenv("BREVO_API_KEY", "").strip()


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


def _from_addr() -> str:
    """Sender address — works for both Brevo API and SMTP paths."""
    return (
        os.getenv("SMTP_FROM", "").strip()
        or os.getenv("SMTP_USER", "").strip()
        or "noreply@example.com"
    )


# ---------------------------------------------------------------------------
# Brevo HTTP API sender (primary — no SMTP port needed)
# ---------------------------------------------------------------------------

def _send_via_brevo_api(
    *,
    api_key: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    from_addr: str,
) -> None:
    payload = json.dumps(
        {
            "sender": {"email": from_addr},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_body,
            "textContent": text_body,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        _BREVO_API_URL,
        data=payload,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    logger.info(
        "email_service brevo_api_attempt from=%s to=%s",
        from_addr,
        to_email,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
        logger.info(
            "email_service brevo_api_sent status=%s to=%s body=%s",
            status,
            to_email,
            body[:120],
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        logger.error(
            "email_service brevo_api_http_error status=%s to=%s body=%s",
            exc.code,
            to_email,
            body[:300],
            exc_info=True,
        )
        raise
    except Exception:
        logger.exception(
            "email_service brevo_api_error to=%s",
            to_email,
        )
        raise


# ---------------------------------------------------------------------------
# SMTP sender (fallback — blocked on Render free tier)
# ---------------------------------------------------------------------------

def _send_via_smtp(
    *,
    cfg: dict,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    logger.info(
        "email_service smtp_attempt host=%s port=%s user=%s from=%s to=%s",
        cfg["host"],
        cfg["port"],
        cfg["user"] or "(empty)",
        cfg["from_addr"],
        to_email,
    )
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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def send_verification_email(*, to_email: str, verify_link: str) -> None:
    """Send an email-verification link after registration. Never raises."""
    subject = "Ověřte svůj email — Marketingový přehled"
    text_body = (
        "Dobrý den,\n\n"
        f"klikněte na odkaz pro ověření emailové adresy:\n{verify_link}\n\n"
        "Odkaz je platný 24 hodin."
    )
    html_body = (
        "<html><body>"
        "<p>Dobrý den,</p>"
        "<p>klikněte na odkaz pro ověření emailové adresy:<br>"
        f'<a href="{verify_link}">{verify_link}</a></p>'
        "<p>Odkaz je platný 24 hodin.</p>"
        "</body></html>"
    )

    api_key = _brevo_api_key()
    if api_key:
        try:
            _send_via_brevo_api(
                api_key=api_key,
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                from_addr=_from_addr(),
            )
        except Exception:
            pass
        return

    try:
        cfg = _smtp_config()
    except Exception:
        logger.exception("email_service _smtp_config failed (verification)")
        return

    if cfg is None:
        logger.info(
            "email_service not_configured — verification link (dev only): to=%s link=%s",
            to_email,
            verify_link,
        )
        return

    try:
        _send_via_smtp(cfg=cfg, to_email=to_email, subject=subject, html_body=html_body, text_body=text_body)
    except Exception:
        logger.exception("email_service smtp_error sending verification to=%s", to_email)


def send_password_reset_email(*, to_email: str, reset_link: str) -> None:
    """Send a password-reset email.

    Tries Brevo HTTP API first (BREVO_API_KEY), then SMTP (SMTP_HOST).
    Falls back to log output when neither is configured (development mode).
    Never raises — endpoint always returns 200 to avoid email enumeration.
    """
    subject = "Obnovení hesla — Marketingový přehled"
    text_body = (
        "Dobrý den,\n\n"
        f"klikněte na odkaz pro obnovení hesla:\n{reset_link}\n\n"
        "Odkaz je platný 1 hodinu. Pokud jste o obnovení nežádali, "
        "ignorujte tento email."
    )
    html_body = (
        "<html><body>"
        "<p>Dobrý den,</p>"
        "<p>klikněte na odkaz pro obnovení hesla:<br>"
        f'<a href="{reset_link}">{reset_link}</a></p>'
        "<p>Odkaz je platný 1 hodinu. Pokud jste o obnovení nežádali, "
        "ignorujte tento email.</p>"
        "</body></html>"
    )

    # --- Path 1: Brevo HTTP API (works on all Render tiers) -----------------
    api_key = _brevo_api_key()
    if api_key:
        try:
            _send_via_brevo_api(
                api_key=api_key,
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                from_addr=_from_addr(),
            )
        except Exception:
            # Error already logged inside _send_via_brevo_api
            pass
        return

    # --- Path 2: SMTP fallback (blocked on Render free tier) ----------------
    try:
        cfg = _smtp_config()
    except Exception:
        logger.exception("email_service _smtp_config failed")
        return

    if cfg is None:
        logger.info(
            "email_service not_configured — no BREVO_API_KEY and no SMTP_HOST. "
            "Password reset link (dev only): to=%s link=%s",
            to_email,
            reset_link,
        )
        return

    try:
        _send_via_smtp(
            cfg=cfg,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "email_service smtp_auth_failed host=%s user=%s — "
            "check SMTP_USER and SMTP_PASSWORD",
            cfg["host"],
            cfg["user"] or "(empty)",
            exc_info=True,
        )
    except smtplib.SMTPConnectError:
        logger.error(
            "email_service smtp_connect_failed host=%s port=%s — "
            "check SMTP_HOST and SMTP_PORT (Render free tier blocks port 587)",
            cfg["host"],
            cfg["port"],
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


def send_password_changed_notification(*, to_email: str) -> None:
    """Notify the user that their password was changed.

    Sent as a background task from the change-password endpoint so it never
    blocks the response.  Never raises — failure is only logged.
    """
    subject = "Heslo bylo změněno — Marketingový přehled"
    text_body = (
        "Dobrý den,\n\n"
        "vaše heslo bylo právě úspěšně změněno.\n\n"
        "Pokud jste tuto změnu neprovedli, okamžitě si obnovte heslo na adrese "
        "https://marketingovy-prehled.cz/forgot-password nebo nás kontaktujte.\n\n"
        "S pozdravem,\nTým Marketingový přehled"
    )
    html_body = (
        "<html><body>"
        "<p>Dobrý den,</p>"
        "<p>vaše heslo bylo právě úspěšně změněno.</p>"
        "<p>Pokud jste tuto změnu neprovedli, okamžitě si "
        '<a href="https://marketingovy-prehled.cz/forgot-password">obnovte heslo</a> '
        "nebo nás kontaktujte.</p>"
        "<p>S pozdravem,<br>Tým Marketingový přehled</p>"
        "</body></html>"
    )

    # --- Path 1: Brevo HTTP API (works on all Render tiers) -----------------
    api_key = _brevo_api_key()
    if api_key:
        try:
            _send_via_brevo_api(
                api_key=api_key,
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                from_addr=_from_addr(),
            )
        except Exception:
            pass
        return

    # --- Path 2: SMTP fallback (blocked on Render free tier) ----------------
    try:
        cfg = _smtp_config()
    except Exception:
        logger.exception("email_service _smtp_config failed (password_changed)")
        return

    if cfg is None:
        logger.info(
            "email_service not_configured — password changed notification skipped (dev only): to=%s",
            to_email,
        )
        return

    try:
        _send_via_smtp(cfg=cfg, to_email=to_email, subject=subject, html_body=html_body, text_body=text_body)
    except Exception:
        logger.exception("email_service smtp_error sending password_changed to=%s", to_email)
