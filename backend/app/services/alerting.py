"""Alert dispatch service for control failure notifications (FR-19, FR-20, FR-21).

Sends email and/or Slack webhook notifications when a control transitions
to Fail status. Includes control ID, failure reason, and dashboard link.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_failure_alert(
    control_id: UUID,
    control_id_code: str,
    title: str,
    reason: str,
) -> None:
    """Dispatch failure alert via configured channels."""
    dashboard_link = f"{settings.FRONTEND_URL}/projects/controls/{control_id}"
    message = (
        f"Control {control_id_code} ({title}) has transitioned to FAIL.\n\n"
        f"Reason: {reason}\n\n"
        f"View details: {dashboard_link}"
    )

    if settings.SLACK_WEBHOOK_URL:
        await _send_slack_alert(message)

    if settings.SMTP_USER:
        await _send_email_alert(
            subject=f"[SentinellAI] Control Failure: {control_id_code}",
            body=message,
        )


async def _send_slack_alert(message: str) -> None:
    """Send alert via Slack incoming webhook."""
    payload = {
        "text": message,
        "username": "SentinellAI",
        "icon_emoji": ":warning:",
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(settings.SLACK_WEBHOOK_URL, json=payload)
    except httpx.HTTPError:
        logger.exception("Failed to send Slack alert")


async def _send_email_alert(subject: str, body: str) -> None:
    """Send alert via SMTP email."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = settings.SMTP_USER

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except smtplib.SMTPException:
        logger.exception("Failed to send email alert")
