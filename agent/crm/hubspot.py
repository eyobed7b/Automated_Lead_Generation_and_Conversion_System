import httpx
import structlog
from typing import Optional

log = structlog.get_logger()

HUBSPOT_BASE = "https://api.hubapi.com"

# tenacious_status is a custom HubSpot property.
# It must be created in the HubSpot portal before the API can set it.
# If missing, we include it in the note body instead.
TENACIOUS_CUSTOM_PROPS = {"tenacious_status": "draft"}


async def upsert_contact(email: str, name: str, company: str,
                          properties: dict, settings) -> Optional[str]:
    """
    Create or update a HubSpot contact with enrichment data.
    Returns the HubSpot contact ID.
    Marks records as draft per policy Rule 6.
    """
    if not settings.hubspot_access_token:
        log.warning("hubspot_token_missing", email=email)
        return f"mock_contact_{email}"

    first, *rest = name.split() if name else ["", ""]
    last = " ".join(rest) if rest else ""

    # Use only standard HubSpot properties in the initial payload.
    # Custom properties (tenacious_status) require prior registration in the portal.
    std_payload = {
        "properties": {
            "email": email,
            "firstname": first,
            "lastname": last,
            "company": company,
            **{k: str(v) for k, v in properties.items()},
        }
    }

    headers = {
        "Authorization": f"Bearer {settings.hubspot_access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        contact_id = await _upsert(email, std_payload, headers, client)

        if contact_id:
            # Attempt to set custom draft property; ignore 400 if not registered yet.
            await _set_draft_property(contact_id, headers, client)

        return contact_id


_HUBSPOT_STD_PROPS = {"email", "firstname", "lastname", "company", "phone",
                      "website", "jobtitle", "lifecyclestage", "hs_lead_status"}


async def _upsert(email: str, payload: dict, headers: dict, client) -> Optional[str]:
    # Try PATCH first (update by email)
    for attempt_payload in [payload, _std_only(payload)]:
        try:
            resp = await client.patch(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{email}?idProperty=email",
                headers=headers,
                json=attempt_payload,
                timeout=15.0,
            )
            if resp.status_code in (200, 201):
                cid = resp.json().get("id")
                log.info("hubspot_contact_updated", email=email, id=cid)
                return cid
            if resp.status_code != 400:
                break
        except Exception:
            break

    # Fall back to POST (create) — try full payload, then standard-only on 400
    for attempt_payload in [payload, _std_only(payload)]:
        try:
            resp = await client.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts",
                headers=headers,
                json=attempt_payload,
                timeout=15.0,
            )
            if resp.status_code == 409:
                return await _get_contact_by_email(email, headers, client)
            resp.raise_for_status()
            cid = resp.json().get("id")
            log.info("hubspot_contact_created", email=email, id=cid,
                     std_only=(attempt_payload is not payload))
            return cid
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                return await _get_contact_by_email(email, headers, client)
            if e.response.status_code != 400:
                log.error("hubspot_create_failed",
                          status=e.response.status_code,
                          body=e.response.text[:200])
                return None
            # 400 → retry with standard-only properties
            log.warning("hubspot_custom_props_rejected",
                        note="Retrying with standard HubSpot properties only")
            continue
        except Exception as e:
            log.error("hubspot_create_error", error=str(e))
            return None

    return None


def _std_only(payload: dict) -> dict:
    """Return payload with only standard HubSpot contact properties."""
    props = payload.get("properties", {})
    return {"properties": {k: v for k, v in props.items() if k in _HUBSPOT_STD_PROPS}}


async def _set_draft_property(contact_id: str, headers: dict, client) -> None:
    """Set tenacious_status=draft; silently skip if custom property not registered."""
    try:
        resp = await client.patch(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
            headers=headers,
            json={"properties": {"tenacious_status": "draft"}},
            timeout=10.0,
        )
        if resp.status_code in (200, 201):
            log.info("hubspot_draft_flag_set", contact_id=contact_id)
        else:
            log.warning("hubspot_draft_flag_skipped",
                        contact_id=contact_id,
                        status=resp.status_code,
                        note="Create tenacious_status custom property in HubSpot portal")
    except Exception as e:
        log.warning("hubspot_draft_flag_error", error=str(e))


async def log_activity(contact_id: str, activity_type: str,
                        properties: dict, settings) -> None:
    """Log a CRM activity note. Skipped gracefully if contact_id is missing."""
    if not settings.hubspot_access_token:
        log.info("hubspot_activity_mock", contact_id=contact_id, type=activity_type)
        return

    if not contact_id:
        log.warning("hubspot_activity_skipped", reason="no_contact_id", type=activity_type)
        return

    headers = {
        "Authorization": f"Bearer {settings.hubspot_access_token}",
        "Content-Type": "application/json",
    }

    note_body = (f"[{activity_type}] [tenacious_status=draft] "
                 + "; ".join(f"{k}={v}" for k, v in properties.items()))

    payload = {
        "properties": {
            "hs_note_body": note_body,
            "hs_timestamp": str(int(__import__("time").time() * 1000)),
        },
        "associations": [
            {
                "to": {"id": contact_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}],
            }
        ],
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/notes",
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
            log.info("hubspot_activity_logged", contact_id=contact_id, type=activity_type)
        except Exception as e:
            log.error("hubspot_activity_failed", error=str(e))


async def _get_contact_by_email(email: str, headers: dict, client) -> Optional[str]:
    try:
        resp = await client.get(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{email}?idProperty=email",
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("id")
    except Exception:
        pass
    return None
