import structlog
from typing import Optional

log = structlog.get_logger()


async def route_sms(to: str, message: str, metadata: dict, settings) -> str:
    """
    Route SMS to correct recipient.
    SMS is secondary channel — only for warm leads who have replied by email.
    When LIVE_OUTBOUND is False, routes to staff sink.
    """
    recipient = to if settings.live_outbound else settings.staff_sink_phone
    if not settings.live_outbound:
        log.info("sms_sandbox_redirect", original=to, sink=recipient)

    return await send_sms(
        to=recipient,
        message=message,
        metadata=metadata,
        settings=settings,
    )


async def send_sms(to: str, message: str, metadata: dict, settings) -> str:
    """Send via Africa's Talking sandbox."""
    if not settings.africastalking_api_key:
        log.warning("africastalking_api_key_missing", to=to)
        return "mock_sms_id_no_api_key"

    try:
        import africastalking
        africastalking.initialize(
            username=settings.africastalking_username,
            api_key=settings.africastalking_api_key,
        )
        sms = africastalking.SMS

        response = sms.send(
            message=message,
            recipients=[to],
            sender_id=settings.africastalking_sender_id,
        )

        recipients_data = response.get("SMSMessageData", {}).get("Recipients", [])
        if recipients_data:
            msg_id = recipients_data[0].get("messageId", "unknown")
            status = recipients_data[0].get("status", "unknown")
            log.info("sms_sent", to=to, message_id=msg_id, status=status)
            return msg_id

        return "unknown_sms_id"

    except ImportError:
        log.warning("africastalking_not_installed")
        return "mock_sms_id_no_library"
    except Exception as e:
        log.error("sms_send_error", error=str(e), to=to)
        return "sms_sandbox_timeout"


def build_scheduling_sms(contact_name: str, booking_link: str) -> str:
    name_part = f"Hi {contact_name.split()[0]}" if contact_name else "Hi"
    return (
        f"{name_part}, following up from Tenacious — "
        f"happy to keep this to text if easier. "
        f"Book a 30-min call here: {booking_link}"
    )
