"""Email sending via Resend API."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from apps.api.config import EMAIL_FROM, RESEND_API_KEY

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


async def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    from_addr: Optional[str] = None,
) -> bool:
    """
    Send an email using Resend API.
    Returns True if sent successfully, False otherwise (e.g. not configured or API error).
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is empty; cannot send email. Check root .env")
        return False

    from_addr = (from_addr or EMAIL_FROM).strip()
    payload = {
        "from": from_addr,
        "to": [to],
        "subject": subject,
        "html": html,
    }

    logger.info("Sending email to %s via Resend (from=%s)", to, from_addr)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code in (200, 201):
                logger.info("Resend: email sent successfully to %s", to)
                return True
            try:
                err_body = resp.json()
                err_msg = err_body.get("message", err_body.get("detail", resp.text))
            except Exception:
                err_msg = resp.text
            logger.error(
                "Resend API error status=%s body=%s",
                resp.status_code,
                err_msg,
            )
            return False
    except Exception as e:
        logger.exception("Failed to send email: %s", e)
        return False
