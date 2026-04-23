import re
import structlog
from channels.sms_handler import build_scheduling_sms, route_sms
from channels.calendar_handler import create_booking_link
from channels.email_handler import route_email
from crm.hubspot import log_activity
from outreach.nurture import NurtureStateMachine

log = structlog.get_logger()
nurture = NurtureStateMachine()

BOOKING_KEYWORDS = ["book", "schedule", "call", "time", "calendar", "available", "meet", "chat"]
STOP_KEYWORDS = ["unsubscribe", "remove", "stop", "opt out", "not interested"]
POSITIVE_KEYWORDS = ["yes", "interested", "tell me more", "sounds good", "open to", "let's talk"]


async def handle_email_reply(payload: dict, settings) -> None:
    """
    Handle inbound email reply from Resend webhook.
    Classify intent and take appropriate action.
    """
    from_email = payload.get("from") or payload.get("sender", "")
    text = (payload.get("text") or payload.get("body", "")).lower()
    prospect_id = _extract_prospect_id(payload)
    contact_name = payload.get("contact_name", "")

    log.info("email_reply_received", from_email=from_email, prospect_id=prospect_id)

    # Transition state
    nurture.transition(prospect_id, "email_replied")

    # Log to CRM
    await log_activity(
        contact_id=prospect_id,
        activity_type="EMAIL_REPLY_RECEIVED",
        properties={"from": from_email, "snippet": text[:200]},
        settings=settings,
    )

    # Hard stop
    if any(kw in text for kw in STOP_KEYWORDS):
        nurture.transition(prospect_id, "closed")
        log.info("prospect_opted_out", prospect_id=prospect_id)
        return

    # Wants to book
    if any(kw in text for kw in BOOKING_KEYWORDS):
        await _handle_booking_request(prospect_id, from_email, contact_name, settings)
        return

    # Positive / exploratory reply
    if any(kw in text for kw in POSITIVE_KEYWORDS):
        await _send_follow_up_with_booking(prospect_id, from_email, contact_name, settings)
        return

    # Objection or unclear — queue for human
    log.info("email_reply_needs_human_review", prospect_id=prospect_id, snippet=text[:100])
    await log_activity(
        contact_id=prospect_id,
        activity_type="HUMAN_REVIEW_NEEDED",
        properties={"reason": "reply_intent_unclear", "snippet": text[:200]},
        settings=settings,
    )


async def _handle_booking_request(prospect_id: str, email: str,
                                   name: str, settings) -> None:
    booking_link = await create_booking_link(name, settings)
    body = (
        f"Great — here's a direct link to book a 30-minute discovery call:\n\n"
        f"{booking_link}\n\n"
        f"I'll send a calendar invite once you pick a time. "
        f"Happy to adjust if none of those slots work."
    )
    await route_email(
        to=email,
        subject="Re: Discovery call link",
        body=body,
        metadata={"prospect_id": prospect_id, "variant": "booking_follow_up"},
        settings=settings,
    )
    await log_activity(
        contact_id=prospect_id,
        activity_type="BOOKING_LINK_SENT",
        properties={"booking_link": booking_link},
        settings=settings,
    )


async def _send_follow_up_with_booking(prospect_id: str, email: str,
                                        name: str, settings) -> None:
    first = name.split()[0] if name else "there"
    booking_link = await create_booking_link(name, settings)
    body = (
        f"Thanks {first} — happy to walk through this in more detail.\n\n"
        f"Here's a 30-minute slot if it's easier than back-and-forth: {booking_link}\n\n"
        f"Or let me know what works on your end."
    )
    await route_email(
        to=email,
        subject="Re: Quick follow-up",
        body=body,
        metadata={"prospect_id": prospect_id, "variant": "warm_follow_up"},
        settings=settings,
    )


def _extract_prospect_id(payload: dict) -> str:
    headers = payload.get("headers") or {}
    pid = headers.get("X-Prospect-ID") or payload.get("prospect_id") or ""
    if pid:
        return pid
    return payload.get("from", "unknown").replace("@", "_at_")
