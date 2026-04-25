"""
Run once to register all custom contact properties in HubSpot.
Usage:  cd agent && python3 crm/setup_hubspot_properties.py
"""
import asyncio
import httpx
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import get_settings

HUBSPOT_BASE = "https://api.hubapi.com"

CUSTOM_PROPERTIES = [
    {
        "name": "icp_segment",
        "label": "ICP Segment",
        "type": "string",
        "fieldType": "text",
        "description": "Tenacious ICP segment: segment_1_series_a_b | segment_2_mid_market_restructure | segment_3_leadership_transition | segment_4_specialized_capability",
    },
    {
        "name": "icp_confidence",
        "label": "ICP Confidence Score",
        "type": "number",
        "fieldType": "number",
        "description": "ICP classification confidence 0.0–1.0",
    },
    {
        "name": "ai_maturity_score",
        "label": "AI Maturity Score",
        "type": "number",
        "fieldType": "number",
        "description": "AI maturity 0–3 scored from public signals",
    },
    {
        "name": "outreach_status",
        "label": "Outreach Status",
        "type": "string",
        "fieldType": "text",
        "description": "Current outreach state: EMAIL_SENT | EMAIL_REPLIED | BOOKING_LINK_SENT | CALL_BOOKED",
    },
    {
        "name": "enrichment_timestamp",
        "label": "Enrichment Timestamp",
        "type": "string",
        "fieldType": "text",
        "description": "ISO timestamp of last enrichment run",
    },
    {
        "name": "tenacious_status",
        "label": "Tenacious Status",
        "type": "string",
        "fieldType": "text",
        "description": "Internal status: draft | approved | sent",
    },
    {
        "name": "honesty_flags",
        "label": "Honesty Flags",
        "type": "string",
        "fieldType": "text",
        "description": "Comma-separated honesty flags applied during enrichment",
    },
    {
        "name": "pitch_angle",
        "label": "Recommended Pitch Angle",
        "type": "string",
        "fieldType": "text",
        "description": "Signal-grounded pitch angle from enrichment pipeline",
    },
]


async def create_property(client: httpx.AsyncClient, headers: dict, prop: dict) -> dict:
    resp = await client.post(
        f"{HUBSPOT_BASE}/crm/v3/properties/contacts",
        headers=headers,
        json={
            "name": prop["name"],
            "label": prop["label"],
            "type": prop["type"],
            "fieldType": prop["fieldType"],
            "groupName": "contactinformation",
            "description": prop.get("description", ""),
        },
        timeout=15.0,
    )
    return {"name": prop["name"], "status": resp.status_code, "body": resp.json()}


async def main():
    settings = get_settings()
    if not settings.hubspot_access_token:
        print("ERROR: HUBSPOT_ACCESS_TOKEN not set in .env")
        return

    headers = {
        "Authorization": f"Bearer {settings.hubspot_access_token}",
        "Content-Type": "application/json",
    }

    print(f"Creating {len(CUSTOM_PROPERTIES)} custom properties in HubSpot...\n")

    async with httpx.AsyncClient() as client:
        for prop in CUSTOM_PROPERTIES:
            result = await create_property(client, headers, prop)
            status = result["status"]
            if status == 201:
                print(f"  ✓ Created:  {prop['name']}")
            elif status == 409:
                print(f"  ● Exists:   {prop['name']} (already registered — OK)")
            else:
                msg = result["body"].get("message", str(result["body"]))
                print(f"  ✗ Failed:   {prop['name']} — {status}: {msg}")

    print("\nDone. Run the pipeline again — all fields will now write to HubSpot.")


if __name__ == "__main__":
    asyncio.run(main())
