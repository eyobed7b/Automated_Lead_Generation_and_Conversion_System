import httpx
import structlog
from typing import Optional

log = structlog.get_logger()


async def route_email(to: str, subject: str, body: str,
                      metadata: dict, settings) -> str:
    """
    Route an email to the correct recipient.
    When LIVE_OUTBOUND is False, routes to staff sink.
    """
    recipient = to if settings.live_outbound else settings.staff_sink_email
    if not settings.live_outbound:
        log.info("email_sandbox_redirect", original=to, sink=recipient)

    return await send_email(
        to=recipient,
        subject=subject,
        body=body,
        metadata=metadata,
        settings=settings,
    )


async def send_email(to: str, subject: str, body: str,
                     metadata: dict, settings) -> str:
    """Send via Resend API."""
    if not settings.resend_api_key:
        log.warning("resend_api_key_missing", to=to)
        return "mock_message_id_no_api_key"

    payload = {
        "from": settings.resend_from_email,
        "to": [to],
        "subject": subject,
        "text": body,
        "headers": {
            "X-Prospect-ID": metadata.get("prospect_id", ""),
            "X-Outbound-Variant": metadata.get("variant", ""),
            "X-Tenacious-Status": "draft",
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            message_id = data.get("id", "unknown")
            log.info("email_sent", to=to, subject=subject, message_id=message_id)
            return message_id
        except httpx.HTTPStatusError as e:
            log.error("email_send_failed", status=e.response.status_code, error=str(e))
            return f"failed_{e.response.status_code}"
        except Exception as e:
            log.error("email_send_error", error=str(e))
            return "failed_network_error"
