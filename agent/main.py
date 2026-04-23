import time
import structlog
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional

from config import get_settings, Settings
from enrichment.pipeline import enrich_prospect
from qualification.icp_classifier import classify_icp
from qualification.signal_brief import build_signal_brief
from outreach.composer import compose_outreach_email
from outreach.nurture import NurtureStateMachine
from channels.email_handler import send_email, route_email
from channels.sms_handler import send_sms, route_sms
from channels.calendar_handler import create_booking_link
from crm.hubspot import upsert_contact, log_activity
from webhooks.email_reply import handle_email_reply
from webhooks.sms_reply import handle_sms_reply

log = structlog.get_logger()
app = FastAPI(title="Tenacious Conversion Engine", version="1.0.0")
nurture = NurtureStateMachine()


# ── Models ──────────────────────────────────────────────────────────────────

class ProspectRequest(BaseModel):
    company_name: str
    company_domain: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    crunchbase_id: Optional[str] = None


class OutreachRequest(BaseModel):
    prospect_id: str
    force_segment: Optional[str] = None


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


# ── Prospect pipeline ────────────────────────────────────────────────────────

@app.post("/prospects/enrich")
async def enrich(req: ProspectRequest, background: BackgroundTasks,
                 settings: Settings = Depends(get_settings)):
    """
    Step 1: Enrich a prospect with all public signals.
    Returns hiring_signal_brief + competitor_gap_brief.
    """
    log.info("enrich_start", company=req.company_name)
    brief = await enrich_prospect(
        company_name=req.company_name,
        company_domain=req.company_domain,
        crunchbase_id=req.crunchbase_id,
        settings=settings,
    )
    classification = classify_icp(brief, settings)
    signal_brief = build_signal_brief(brief, classification)

    contact_id = await upsert_contact(
        email=req.contact_email or settings.staff_sink_email,
        name=req.contact_name or req.company_name,
        company=req.company_name,
        properties={
            "icp_segment": classification.segment,
            "icp_confidence": classification.confidence,
            "ai_maturity_score": brief.ai_maturity.score,
            "enrichment_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        settings=settings,
    )

    log.info("enrich_complete",
             company=req.company_name,
             segment=classification.segment,
             confidence=classification.confidence,
             ai_maturity=brief.ai_maturity.score)

    return {
        "contact_id": contact_id,
        "classification": classification.dict(),
        "signal_brief": signal_brief,
        "hiring_signal_brief": brief.dict(),
    }


@app.post("/prospects/{prospect_id}/outreach")
async def trigger_outreach(prospect_id: str, req: OutreachRequest,
                           background: BackgroundTasks,
                           settings: Settings = Depends(get_settings)):
    """
    Step 2: Compose and send signal-grounded outreach email.
    """
    brief_data = nurture.get_brief(prospect_id)
    if not brief_data:
        raise HTTPException(status_code=404, detail="Prospect not enriched yet. Call /prospects/enrich first.")

    email_content = await compose_outreach_email(
        brief=brief_data["hiring_signal_brief"],
        classification=brief_data["classification"],
        competitor_gap=brief_data.get("competitor_gap_brief"),
        contact_name=brief_data.get("contact_name"),
        settings=settings,
    )

    booking_link = await create_booking_link(
        prospect_name=brief_data.get("contact_name", ""),
        settings=settings,
    )
    email_content["body"] += f"\n\n{booking_link}"

    recipient = brief_data.get("contact_email") or settings.staff_sink_email
    message_id = await route_email(
        to=recipient,
        subject=email_content["subject"],
        body=email_content["body"],
        metadata={"prospect_id": prospect_id, "variant": "signal_grounded"},
        settings=settings,
    )

    await log_activity(
        contact_id=prospect_id,
        activity_type="EMAIL_SENT",
        properties={"message_id": message_id, "subject": email_content["subject"]},
        settings=settings,
    )

    nurture.transition(prospect_id, "email_sent")
    log.info("outreach_sent", prospect_id=prospect_id, message_id=message_id)
    return {"message_id": message_id, "status": "sent"}


# ── Webhooks ─────────────────────────────────────────────────────────────────

@app.post("/webhooks/email/reply")
async def email_reply_webhook(request: Request, background: BackgroundTasks,
                               settings: Settings = Depends(get_settings)):
    payload = await request.json()
    background.add_task(handle_email_reply, payload, settings)
    return {"received": True}


@app.post("/webhooks/sms/reply")
async def sms_reply_webhook(request: Request, background: BackgroundTasks,
                             settings: Settings = Depends(get_settings)):
    payload = await request.json()
    background.add_task(handle_sms_reply, payload, settings)
    return {"received": True}


# ── Error handler ─────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
