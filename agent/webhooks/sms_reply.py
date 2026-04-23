import structlog
from channels.calendar_handler import create_booking_link
from channels.sms_handler import route_sms
from crm.hubspot import log_activity
from outreach.nurture import NurtureStateMachine

log = structlog.get_logger()
nurture = NurtureStateMachine()

BOOKING_KEYWORDS = ["book", "schedule", "yes", "ok", "sure", "sounds good", "when", "time", "available"]
STOP_KEYWORDS = ["stop", "unsubscribe", "remove", "quit"]


async def handle_sms_reply(payload: dict, settings) -> None:
    """
    Handle inbound SMS reply from Africa's Talking webhook.
    SMS is secondary channel — only warm leads who replied by email.
    """
    from_phone = payload.get("from") or payload.get("phoneNumber", "")
    text = (payload.get("text") or payload.get("message", "")).lower().strip()
    prospect_id = payload.get("prospect_id") or from_phone

    log.info("sms_reply_received", from_phone=from_phone, text=text[:50])

    nurture.transition(prospect_id, "email_replied")

    await log_activity(
        contact_id=prospect_id,
        activity_type="SMS_REPLY_RECEIVED",
        properties={"from": from_phone, "text": text[:200]},
        settings=settings,
    )

    if any(kw in text for kw in STOP_KEYWORDS):
        nurture.transition(prospect_id, "closed")
        log.info("sms_opt_out", prospect_id=prospect_id)
        return

    if any(kw in text for kw in BOOKING_KEYWORDS):
        contact_name = payload.get("contact_name", "")
        booking_link = await create_booking_link(contact_name, settings)
        reply = f"Book here: {booking_link} — 30 min, pick any slot."
        await route_sms(
            to=from_phone,
            message=reply,
            metadata={"prospect_id": prospect_id},
            settings=settings,
        )
        nurture.transition(prospect_id, "sms_sent")
        await log_activity(
            contact_id=prospect_id,
            activity_type="BOOKING_LINK_SENT_SMS",
            properties={"link": booking_link},
            settings=settings,
        )
        return

    # Unclear — log for human
    log.info("sms_reply_needs_human", prospect_id=prospect_id, text=text[:50])
    await log_activity(
        contact_id=prospect_id,
        activity_type="HUMAN_REVIEW_NEEDED",
        properties={"channel": "sms", "text": text[:200]},
        settings=settings,
    )
