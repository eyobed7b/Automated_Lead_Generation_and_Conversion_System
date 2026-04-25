import structlog
from channels.calendar_handler import create_booking_link
from channels.email_handler import route_email
from crm.hubspot import log_activity, upsert_contact
from outreach.nurture import NurtureStateMachine

log = structlog.get_logger()
nurture = NurtureStateMachine()

# ── 5-class taxonomy from warm.md ────────────────────────────────────────────
# Class 1: Engaged — substantive reply with specific question or context
ENGAGED_KEYWORDS = [
    "what exactly", "how does", "tell me more", "what does", "how do you",
    "are these", "what is", "how many", "what stack", "what timezone",
    "what's the", "sounds interesting", "curious", "walk me through",
]
# Class 2: Curious — "tell me more" or generic interest
CURIOUS_KEYWORDS = [
    "tell me more", "what do you do", "more info", "sounds good",
    "interesting", "open to", "worth a call",
]
# Class 3: Hard no — opt-out
HARD_NO_KEYWORDS = [
    "not interested", "unsubscribe", "remove me", "stop emailing",
    "please remove", "opt out", "take me off", "stop contacting",
    "don't contact", "do not contact",
]
# Class 4: Soft defer — "not now"
SOFT_DEFER_KEYWORDS = [
    "not right now", "not at the moment", "too busy", "ask me in",
    "check back", "q3", "q4", "next quarter", "next year",
    "not the right time", "bad timing",
]
# Class 5: Objection — price, incumbent, scope
OBJECTION_KEYWORDS = [
    "cheaper", "india", "cheaper option", "already have", "current vendor",
    "in-house", "too expensive", "pricing", "cost", "budget",
    "small poc", "just a poc", "pilot",
]
# Booking intent (sub-class of Engaged)
BOOKING_KEYWORDS = [
    "book", "schedule", "calendar", "available", "free on", "meet",
    "30 min", "15 min", "call this week",
]


def classify_reply(text: str) -> str:
    """Classify reply into one of 5 warm.md classes."""
    t = text.lower()
    if any(k in t for k in HARD_NO_KEYWORDS):
        return "hard_no"
    if any(k in t for k in SOFT_DEFER_KEYWORDS):
        return "soft_defer"
    if any(k in t for k in OBJECTION_KEYWORDS):
        return "objection"
    if any(k in t for k in BOOKING_KEYWORDS):
        return "engaged_booking"
    if any(k in t for k in ENGAGED_KEYWORDS):
        return "engaged"
    if any(k in t for k in CURIOUS_KEYWORDS):
        return "curious"
    return "unclear"


async def handle_email_reply(payload: dict, settings) -> dict:
    """
    Handle inbound email reply. Classifies using warm.md 5-class taxonomy.
    Returns classification + action taken.
    """
    from_email = payload.get("from") or payload.get("sender", "")
    text = (payload.get("text") or payload.get("body", ""))
    prospect_id = _extract_prospect_id(payload)
    contact_name = payload.get("contact_name", "")
    first = contact_name.split()[0] if contact_name else "there"

    intent = classify_reply(text)
    log.info("email_reply_classified", from_email=from_email,
             prospect_id=prospect_id, intent=intent)

    nurture.transition(prospect_id, "email_replied")

    await log_activity(
        contact_id=prospect_id,
        activity_type="EMAIL_REPLY_RECEIVED",
        properties={"intent": intent, "snippet": text[:200]},
        settings=settings,
    )

    # ── Class 3: Hard no ──────────────────────────────────────────────────────
    if intent == "hard_no":
        nurture.transition(prospect_id, "closed")
        await log_activity(
            contact_id=prospect_id,
            activity_type="OPTED_OUT",
            properties={"reason": "hard_no"},
            settings=settings,
        )
        log.info("prospect_opted_out", prospect_id=prospect_id)
        return {"intent": intent, "action": "closed_no_reply"}

    # ── Class 4: Soft defer ───────────────────────────────────────────────────
    if intent == "soft_defer":
        body = (
            f"{first},\n\n"
            f"Understood — timing matters. "
            f"I'll set a reminder to reach out again in Q3 with fresh research on your sector at that point. "
            f"Until then, good luck with the work.\n\n"
            f"Alex\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
        )
        await route_email(
            to=from_email,
            subject="Re: Will check back in Q3",
            body=body,
            metadata={"prospect_id": prospect_id, "variant": "soft_defer_close"},
            settings=settings,
        )
        return {"intent": intent, "action": "gracious_close_sent", "reengagement": "Q3"}

    # ── Class 5: Objection ────────────────────────────────────────────────────
    if intent == "objection":
        t = text.lower()
        if any(k in t for k in ["cheaper", "india", "cost", "expensive", "pricing", "budget"]):
            body = (
                f"{first},\n\n"
                f"Fair — and we're rarely the cheapest. "
                f"We compete on reliability rather than hourly rate: average engineer tenure is 18 months, "
                f"3-hour minimum overlap with your time zone, and a dedicated project manager on every engagement.\n\n"
                f"The cost comparison worth making is usually not $/hour but delivered-output/$ over the engagement. "
                f"Happy to walk through what that looks like for your specific stack.\n\n"
                f"→ [Cal link]\n\n"
                f"Alex\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
            )
            variant = "objection_price"
        elif any(k in t for k in ["already have", "current vendor", "in-house"]):
            body = (
                f"{first},\n\n"
                f"That makes sense — your core scope is likely well-covered. "
                f"Where we tend to add value is specialized capability the incumbent doesn't carry, "
                f"or capacity for new initiatives where a 6-month hiring cycle doesn't fit the timeline.\n\n"
                f"Worth a 15-minute conversation to see if there's a gap worth filling?\n\n"
                f"Alex\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
            )
            variant = "objection_incumbent"
        else:
            body = (
                f"{first},\n\n"
                f"Starting with a small scope is the right move. "
                f"Our starter project floor is $18K — a time-boxed delivery with a clear definition of done.\n\n"
                f"Happy to get on a 30-minute call to scope the smallest deliverable that would prove value.\n\n"
                f"Alex\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
            )
            variant = "objection_scope"

        booking_link = await create_booking_link(contact_name, settings)
        body = body.replace("→ [Cal link]", f"→ {booking_link}")
        await route_email(
            to=from_email,
            subject="Re: Your question",
            body=body,
            metadata={"prospect_id": prospect_id, "variant": variant},
            settings=settings,
        )
        return {"intent": intent, "action": variant + "_reply_sent"}

    # ── Class 1+2: Engaged / Curious / Booking ────────────────────────────────
    booking_link = await create_booking_link(contact_name, settings)

    if intent == "engaged_booking":
        body = (
            f"{first},\n\n"
            f"Here's a direct link to book a 30-minute discovery call:\n\n"
            f"{booking_link}\n\n"
            f"I'll send a calendar invite once you pick a time. "
            f"Happy to adjust if none of those slots work.\n\n"
            f"Alex\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
        )
        subject = "Re: Discovery call link"
        variant = "booking_follow_up"

    elif intent == "engaged":
        body = (
            f"{first},\n\n"
            f"Good question. Our engineers are full-time Tenacious employees — salaried, benefits, based in Addis Ababa. "
            f"They join your standups, your Slack, your PR review. We carry HR and payroll; you direct the work.\n\n"
            f"A typical squad for your stage is 3 engineers (1 senior + 2 mid-level ICs) plus a fractional PM. "
            f"Minimum 1-month engagement, extensions in 2-week blocks.\n\n"
            f"Free for 30 minutes this week? → {booking_link}\n\n"
            f"Alex\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
        )
        subject = "Re: How the squad model works"
        variant = "engaged_reply"

    else:  # curious or unclear
        body = (
            f"{first},\n\n"
            f"Glad this landed. Two-line version: Tenacious is a managed engineering delivery firm — "
            f"we run dedicated squads out of Addis Ababa for US and EU scale-ups, "
            f"with 3–5 hours of daily time-zone overlap. "
            f"We're most useful when in-house hiring is slower than the work needs.\n\n"
            f"15 minutes this week to see if there's a fit? → {booking_link}\n\n"
            f"Alex\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
        )
        subject = "Re: Quick context on Tenacious"
        variant = "curious_reply"

    await route_email(
        to=from_email,
        subject=subject,
        body=body,
        metadata={"prospect_id": prospect_id, "variant": variant},
        settings=settings,
    )
    await log_activity(
        contact_id=prospect_id,
        activity_type="WARM_REPLY_SENT",
        properties={"variant": variant, "booking_link": booking_link},
        settings=settings,
    )

    return {"intent": intent, "action": variant + "_sent", "booking_link": booking_link}


def _extract_prospect_id(payload: dict) -> str:
    headers = payload.get("headers") or {}
    pid = headers.get("X-Prospect-ID") or payload.get("prospect_id") or ""
    if pid:
        return pid
    return payload.get("from", "unknown").replace("@", "_at_")
