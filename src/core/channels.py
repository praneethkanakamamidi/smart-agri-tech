"""
Outbound message channels. Each channel picks a provider from the environment:

    EMAIL_PROVIDER    = smtp | log        (default: smtp when SMTP settings exist, else log)
    SMS_PROVIDER      = log | webhook     (+ SMS_WEBHOOK_URL, SMS_WEBHOOK_TOKEN)
    PUSH_PROVIDER     = log | webhook     (+ PUSH_WEBHOOK_URL, PUSH_WEBHOOK_TOKEN)
    WHATSAPP_PROVIDER = log | webhook     (+ WHATSAPP_WEBHOOK_URL, WHATSAPP_WEBHOOK_TOKEN)

"log" writes the message to the application log (development). "webhook" POSTs JSON
{to, title, body, data} to your gateway (an SMS/WhatsApp/FCM bridge), so any Indian
messaging provider can be plugged in without code changes.
"""
import asyncio
import os

import httpx

from src.helpers.logging_config import get_logger

logger = get_logger(__name__)


class DeliveryError(Exception):
    pass


async def _log_send(channel: str, to: str, title: str, body: str, data: dict | None):
    logger.info(f"[{channel}] to={to} title={title!r} body={body!r} data={data or {}}")


async def _webhook_send(channel: str, to: str, title: str, body: str, data: dict | None):
    prefix = channel.upper()
    url = os.getenv(f"{prefix}_WEBHOOK_URL")
    if not url:
        raise DeliveryError(f"{prefix}_WEBHOOK_URL is not configured")
    headers = {}
    token = os.getenv(f"{prefix}_WEBHOOK_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json={"to": to, "title": title, "body": body, "data": data or {}}, headers=headers)
    if response.status_code >= 300:
        raise DeliveryError(f"{channel} gateway returned HTTP {response.status_code}")


async def _smtp_send(to: str, title: str, body: str):
    from src.helpers.smtp_config import SmtpService

    sent = await asyncio.to_thread(SmtpService().send_email_alert, to, title, body)
    if not sent:
        raise DeliveryError("SMTP send failed")


def _email_provider() -> str:
    configured = os.getenv("EMAIL_PROVIDER")
    if configured:
        return configured
    return "smtp" if os.getenv("EMAIL_SMTP_SERVER") and os.getenv("EMAIL_SENDER_ADDRESS") else "log"


async def send(channel: str, to: str, title: str, body: str, data: dict | None = None):
    """Send one message. Raises DeliveryError on failure (the caller records and retries)."""
    if not to:
        raise DeliveryError(f"No {channel} address for recipient")
    if channel == "email":
        if _email_provider() == "smtp":
            await _smtp_send(to, title, body)
        else:
            await _log_send(channel, to, title, body, data)
        return
    provider = os.getenv(f"{channel.upper()}_PROVIDER", "log")
    if provider == "webhook":
        await _webhook_send(channel, to, title, body, data)
    else:
        await _log_send(channel, to, title, body, data)
