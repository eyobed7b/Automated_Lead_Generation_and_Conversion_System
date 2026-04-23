"""
End-to-end test with a synthetic prospect.
Simulates the full pipeline: enrich → classify → compose → send → log to CRM.

Run: python test_end_to_end.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))


async def run_test():
    from config import get_settings
    from enrichment.pipeline import enrich_prospect
    from qualification.icp_classifier import classify_icp
    from qualification.signal_brief import build_signal_brief
    from outreach.composer import compose_outreach_email
    from channels.calendar_handler import create_booking_link
    from channels.email_handler import route_email
    from channels.sms_handler import route_sms, build_scheduling_sms
    from crm.hubspot import upsert_contact, log_activity

    settings = get_settings()

    print("=" * 60)
    print("TENACIOUS CONVERSION ENGINE — END-TO-END TEST")
    print(f"LIVE_OUTBOUND: {settings.live_outbound}")
    print(f"Staff sink: {settings.staff_sink_email}")
    print("=" * 60)

    # SYNTHETIC PROSPECT (not a real person)
    # contact_email uses a valid format required by HubSpot; kill-switch routes actual
    # outbound to staff sink regardless of what address is here.
    prospect = {
        "company_name": "DataFlow Technologies",
        "company_domain": "dataflow.io",
        "contact_name": "Sarah Chen (SYNTHETIC)",
        "contact_email": "synthetic.sarah.chen@example.com",
        "contact_phone": settings.staff_sink_phone,
        "crunchbase_id": "cb_techcorp_001",
    }

    print(f"\n[1] Enriching: {prospect['company_name']}")
    start = time.monotonic()
    brief = await enrich_prospect(
        company_name=prospect["company_name"],
        company_domain=prospect["company_domain"],
        crunchbase_id=prospect["crunchbase_id"],
        settings=settings,
    )
    enrich_time = time.monotonic() - start
    print(f"    Done in {enrich_time:.2f}s")
    print(f"    AI maturity: {brief.ai_maturity.score}/3 ({brief.ai_maturity.confidence_label})")
    print(f"    Sources: {brief.data_sources}")

    print(f"\n[2] Classifying ICP segment")
    classification = classify_icp(brief, settings)
    print(f"    Segment: {classification.segment}")
    print(f"    Confidence: {classification.confidence:.2f}")
    print(f"    Abstain: {classification.abstain}")
    if classification.abstain:
        print(f"    Reason: {classification.abstain_reason}")

    signal_brief = build_signal_brief(brief, classification)
    print(f"    Honesty flags: {signal_brief.get('honesty_flags', [])}")

    print(f"\n[3] Creating HubSpot contact")
    contact_id = await upsert_contact(
        email=prospect["contact_email"],
        name=prospect["contact_name"],
        company=prospect["company_name"],
        properties={
            "icp_segment": classification.segment or "unknown",
            "icp_confidence": str(classification.confidence),
            "ai_maturity_score": str(brief.ai_maturity.score),
            "enrichment_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        settings=settings,
    )
    print(f"    Contact ID: {contact_id}")

    print(f"\n[4] Composing outreach email")
    email = await compose_outreach_email(
        brief=signal_brief,
        classification=classification,
        competitor_gap=brief.competitor_gap,
        contact_name=prospect["contact_name"],
        settings=settings,
    )
    print(f"    Subject: {email['subject']}")
    print(f"    Variant: {email.get('variant', 'unknown')}")
    print(f"    Body preview: {email['body'][:100]}...")

    print(f"\n[5] Getting Cal.com booking link")
    booking_link = await create_booking_link(prospect["contact_name"], settings)
    print(f"    Link: {booking_link}")

    print(f"\n[6] Sending email (→ staff sink: {settings.staff_sink_email})")
    body_with_link = email["body"] + f"\n\nBook a 30-minute call: {booking_link}"
    message_id = await route_email(
        to=prospect["contact_email"],
        subject=email["subject"],
        body=body_with_link,
        metadata={"prospect_id": contact_id or "test", "variant": email.get("variant")},
        settings=settings,
    )
    print(f"    Message ID: {message_id}")

    print(f"\n[7] Logging email activity to HubSpot")
    await log_activity(
        contact_id=contact_id,
        activity_type="EMAIL_SENT",
        properties={"message_id": message_id, "subject": email["subject"]},
        settings=settings,
    )
    print(f"    Activity logged")

    # Simulate warm reply → SMS
    print(f"\n[8] Simulating warm reply → SMS scheduling (→ sink: {settings.staff_sink_phone})")
    sms_message = build_scheduling_sms(prospect["contact_name"], booking_link)
    sms_id = await route_sms(
        to=prospect["contact_phone"],
        message=sms_message,
        metadata={"prospect_id": contact_id or "test"},
        settings=settings,
    )
    print(f"    SMS ID: {sms_id}")
    print(f"    SMS text: {sms_message}")

    print("\n" + "=" * 60)
    print("END-TO-END TEST COMPLETE")
    print(f"Total time: {time.monotonic() - start:.2f}s")

    # Write test report
    report = {
        "test_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prospect": prospect["company_name"],
        "enrichment_duration_s": round(enrich_time, 2),
        "icp_segment": classification.segment,
        "icp_confidence": classification.confidence,
        "ai_maturity_score": brief.ai_maturity.score,
        "email_subject": email["subject"],
        "email_variant": email.get("variant"),
        "message_id": message_id,
        "sms_id": sms_id,
        "booking_link": booking_link,
        "honesty_flags": signal_brief.get("honesty_flags", []),
        "data_sources": brief.data_sources,
    }

    report_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "test_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to data/test_report.json")


if __name__ == "__main__":
    asyncio.run(run_test())
