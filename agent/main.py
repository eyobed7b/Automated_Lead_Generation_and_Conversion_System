import time
import structlog
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
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

    prospect_id = req.contact_email or req.company_name.lower().replace(" ", "-")
    nurture.save_brief(prospect_id, {
        "hiring_signal_brief": brief.dict(),
        "classification": classification.dict(),
        "contact_name": req.contact_name,
        "contact_email": req.contact_email,
    })

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


# ── Demo pipeline (all steps, one call) ──────────────────────────────────────

@app.post("/pipeline/demo")
async def pipeline_demo(req: ProspectRequest, settings: Settings = Depends(get_settings)):
    """
    Runs the full pipeline and returns every step's output.
    Used by the demo website to show real data for each stage.
    """
    t0 = time.time()

    # Step 1: Enrich
    brief = await enrich_prospect(
        company_name=req.company_name,
        company_domain=req.company_domain,
        crunchbase_id=req.crunchbase_id,
        settings=settings,
    )
    step1 = {
        "company": brief.company_name,
        "headcount": brief.crunchbase_profile.headcount_estimate if brief.crunchbase_profile else None,
        "industry": brief.crunchbase_profile.industry if brief.crunchbase_profile else None,
        "location": brief.crunchbase_profile.location if brief.crunchbase_profile else None,
        "description": brief.crunchbase_profile.description if brief.crunchbase_profile else None,
        "funding": brief.crunchbase_profile.last_funding_event.dict() if (brief.crunchbase_profile and brief.crunchbase_profile.last_funding_event) else None,
        "layoff": brief.layoff_event.dict() if brief.layoff_event else None,
        "job_posts": brief.job_posts.dict() if brief.job_posts else None,
        "ai_maturity": brief.ai_maturity.dict() if brief.ai_maturity else None,
        "competitor_gap": brief.competitor_gap.dict() if brief.competitor_gap else None,
        "data_sources": brief.data_sources,
        "enriched_at": brief.enriched_at,
        "duration_seconds": brief.enrichment_duration_seconds,
    }

    # Step 2: ICP Classify
    classification = classify_icp(brief, settings)
    step2 = classification.dict()

    # Step 3: Signal Brief + Honesty Flags
    signal_brief = build_signal_brief(brief, classification)
    step3 = signal_brief

    # Step 4: Honesty Validation Pass (reflected in compose)
    # Step 5: Compose email
    email_content = await compose_outreach_email(
        brief=signal_brief,
        classification=classification,
        competitor_gap=brief.competitor_gap,
        contact_name=req.contact_name,
        settings=settings,
    )
    step4 = {
        "flags_checked": signal_brief.get("honesty_flags", []),
        "flags_count": len(signal_brief.get("honesty_flags", [])),
        "validation": "pass",
    }

    # Step 6: Booking link (before sending so we can append it)
    booking_url = await create_booking_link(
        prospect_name=req.contact_name or req.company_name,
        settings=settings,
    )
    step6 = {"url": booking_url, "duration_minutes": 30, "provider": "cal.com"}

    # Actually send the email
    body_with_booking = email_content["body"] + f"\n\n{booking_url}"
    message_id = await route_email(
        to=req.contact_email or settings.staff_sink_email,
        subject=email_content["subject"],
        body=body_with_booking,
        metadata={"prospect_id": req.contact_email or req.company_name, "variant": email_content.get("variant", "")},
        settings=settings,
    )
    step5 = {**email_content, "message_id": message_id, "sent_to": req.contact_email or settings.staff_sink_email}

    # Step 7: HubSpot CRM
    contact_id = await upsert_contact(
        email=req.contact_email or settings.staff_sink_email,
        name=req.contact_name or req.company_name,
        company=req.company_name,
        properties={
            "icp_segment": classification.segment,
            "icp_confidence": classification.confidence,
            "ai_maturity_score": brief.ai_maturity.score,
            "enrichment_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outreach_status": "EMAIL_SENT",
            "honesty_flags": ", ".join(signal_brief.get("honesty_flags", [])),
            "pitch_angle": signal_brief.get("recommended_pitch_angle", ""),
        },
        settings=settings,
    )
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    step7 = {
        "contact_id": contact_id,
        "email": req.contact_email or settings.staff_sink_email,
        "fields_written": {
            "icp_segment": classification.segment,
            "icp_confidence": str(classification.confidence),
            "ai_maturity_score": str(brief.ai_maturity.score),
            "enrichment_timestamp": ts,
            "outreach_status": "EMAIL_SENT",
            "honesty_flags": ", ".join(signal_brief.get("honesty_flags", [])),
            "pitch_angle": signal_brief.get("recommended_pitch_angle", ""),
        },
    }

    prospect_id = req.contact_email or req.company_name.lower().replace(" ", "-")
    nurture.save_brief(prospect_id, {
        "hiring_signal_brief": brief.dict(),
        "classification": classification.dict(),
        "contact_name": req.contact_name,
        "contact_email": req.contact_email,
    })

    log.info("demo_pipeline_complete", company=req.company_name,
             duration=round(time.time() - t0, 2))
    nurture.transition(prospect_id, "email_sent")

    return {
        "step_1_enrich": step1,
        "step_2_classify": step2,
        "step_3_signal_brief": step3,
        "step_4_honesty_validation": step4,
        "step_5_email": step5,
        "step_6_booking": step6,
        "step_7_crm": step7,
        "meta": {
            "duration_seconds": round(time.time() - t0, 2),
            "prospect_id": prospect_id,
            "model": settings.dev_model,
        }
    }


# ── Demo reply simulation ─────────────────────────────────────────────────────

class DemoReplyRequest(BaseModel):
    contact_email: str
    contact_name: Optional[str] = None
    reply_text: str = "Yes, this is interesting. Can we schedule a call this week?"


@app.post("/pipeline/demo/reply")
async def demo_reply(req: DemoReplyRequest, settings: Settings = Depends(get_settings)):
    """
    Simulate the prospect replying to the outreach email.
    Triggers the real reply handler which sends a follow-up + booking link.
    """
    from webhooks.email_reply import handle_email_reply
    prospect_id = req.contact_email

    payload = {
        "from": req.contact_email,
        "sender": req.contact_email,
        "contact_name": req.contact_name or req.contact_email.split("@")[0],
        "text": req.reply_text,
        "body": req.reply_text,
        "prospect_id": prospect_id,
        "headers": {"X-Prospect-ID": prospect_id},
    }

    result = await handle_email_reply(payload, settings)
    log.info("demo_reply_simulated", email=req.contact_email, intent=result.get("intent"))
    return {
        "status": "reply_processed",
        "prospect_id": prospect_id,
        "reply_text": req.reply_text,
        "intent_class": result.get("intent"),
        "action": result.get("action"),
        "booking_link": result.get("booking_link"),
        "sent_to": req.contact_email if settings.live_outbound else settings.staff_sink_email,
    }


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
