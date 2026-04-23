import re
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

LOOKBACK_DAYS = 90
LEADERSHIP_TITLES = [
    "chief technology officer", "cto", "vp engineering", "vice president engineering",
    "vice president of engineering", "head of engineering", "svp engineering",
    "director of engineering", "chief engineer", "vp of engineering",
]


class LeadershipChange(BaseModel):
    role: str
    person_name: Optional[str]
    announced_date: Optional[str]
    days_ago: Optional[int]
    is_recent: bool
    source: str
    confidence: float


async def detect_leadership_changes(company_name: str,
                                     crunchbase_data: Optional[dict] = None) -> Optional[LeadershipChange]:
    """
    Detect new CTO/VP Engineering appointments in the last 90 days.
    Uses Crunchbase data first, then falls back to press release detection.
    """
    if crunchbase_data:
        result = _check_crunchbase_people(company_name, crunchbase_data)
        if result:
            return result

    result = await _check_press_signals(company_name)
    return result


def _check_crunchbase_people(company_name: str, data: dict) -> Optional[LeadershipChange]:
    people = data.get("people", []) or data.get("current_team", [])
    cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)

    for person in people:
        title = (person.get("title") or person.get("job_title") or "").lower()
        started = person.get("started_on") or person.get("start_date") or ""

        if not any(t in title for t in LEADERSHIP_TITLES):
            continue

        if started:
            try:
                start_date = datetime.strptime(started[:10], "%Y-%m-%d")
                days_ago = (datetime.utcnow() - start_date).days
                is_recent = start_date >= cutoff

                if is_recent:
                    return LeadershipChange(
                        role=person.get("title", "CTO/VP Engineering"),
                        person_name=person.get("name") or person.get("full_name"),
                        announced_date=started[:10],
                        days_ago=days_ago,
                        is_recent=True,
                        source="crunchbase",
                        confidence=0.9,
                    )
            except ValueError:
                continue

    return None


async def _check_press_signals(company_name: str) -> Optional[LeadershipChange]:
    """
    Lightweight press signal check. In production this would query a news API.
    For the challenge, returns None if no data available.
    """
    log.info("press_leadership_check", company=company_name,
             note="Production would query news API here")
    return None


def leadership_signal_text(change: Optional[LeadershipChange]) -> str:
    if not change:
        return "No recent leadership change detected."
    if change.is_recent:
        name_part = f" ({change.person_name})" if change.person_name else ""
        return (f"New {change.role}{name_part} appointed "
                f"{change.days_ago} days ago. "
                f"Confidence: {change.confidence:.0%} (source: {change.source}).")
    return f"Leadership change detected but outside 90-day window ({change.days_ago} days ago)."
