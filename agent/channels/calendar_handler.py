import httpx
import structlog
from typing import Optional
from urllib.parse import quote_plus

log = structlog.get_logger()

CAL_API = "https://api.cal.com/v2"
CAL_BOOK = "https://cal.com"


def _cal_headers(settings) -> dict:
    return {
        "Authorization": f"Bearer {settings.calcom_api_key}",
        "cal-api-version": "2024-06-14",
    }


async def create_booking_link(prospect_name: str, settings) -> str:
    """
    Generate a Cal.com booking link for a discovery call.
    Cloud API v2: https://api.cal.com/v2  — auth via Bearer header.
    Falls back to a static link if key or username is missing.
    """
    if not settings.calcom_api_key or not settings.calcom_username:
        log.warning("calcom_config_missing",
                    has_key=bool(settings.calcom_api_key),
                    has_username=bool(settings.calcom_username))
        return _fallback_link(settings)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CAL_API}/event-types/{settings.calcom_event_type_id}",
                headers=_cal_headers(settings),
                timeout=10.0,
            )
            if resp.status_code == 200:
                body = resp.json()
                data = body.get("data") or body
                slug = data.get("slug", "discovery-call")
                safe_name = quote_plus(prospect_name)
                link = f"{CAL_BOOK}/{settings.calcom_username}/{slug}?name={safe_name}"
                log.info("calcom_link_created", slug=slug, prospect=prospect_name)
                return link
            log.warning("calcom_event_type_fetch_failed", status=resp.status_code,
                        body=resp.text[:200])
    except Exception as e:
        log.warning("calcom_link_failed", error=str(e))

    return _fallback_link(settings)


async def list_available_slots(date: str, settings) -> list[dict]:
    """Return available discovery call slots for a given date (YYYY-MM-DD)."""
    if not settings.calcom_api_key:
        return []

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CAL_API}/slots/available",
                headers=_cal_headers(settings),
                params={
                    "eventTypeId": settings.calcom_event_type_id,
                    "startTime": f"{date}T00:00:00Z",
                    "endTime": f"{date}T23:59:59Z",
                },
                timeout=10.0,
            )
            if resp.status_code == 200:
                body = resp.json()
                return body.get("data", {}).get("slots", [])
    except Exception as e:
        log.warning("calcom_slots_failed", error=str(e))

    return []


async def confirm_booking(slot_id: str, prospect_email: str,
                           prospect_name: str, settings) -> Optional[dict]:
    """Confirm a specific booking slot."""
    if not settings.calcom_api_key:
        return None

    payload = {
        "eventTypeId": settings.calcom_event_type_id,
        "start": slot_id,
        "attendee": {
            "email": prospect_email,
            "name": prospect_name,
            "timeZone": "UTC",
            "language": "en",
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{CAL_API}/bookings",
                headers={**_cal_headers(settings), "Content-Type": "application/json"},
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            log.info("booking_confirmed", prospect=prospect_email, slot=slot_id)
            return data
        except Exception as e:
            log.error("booking_failed", error=str(e))
            return None


def _fallback_link(settings) -> str:
    username = settings.calcom_username or "tenacious"
    return f"{CAL_BOOK}/{username}/discovery-call"
