import json
import os
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import structlog

log = structlog.get_logger()


class FundingEvent(BaseModel):
    round_type: str
    amount_usd: Optional[float]
    announced_date: str
    days_ago: int


class CrunchbaseProfile(BaseModel):
    company_name: str
    crunchbase_id: Optional[str]
    domain: Optional[str]
    description: Optional[str]
    industry: Optional[str]
    location: Optional[str]
    headcount_range: Optional[str]
    headcount_estimate: Optional[int]
    founded_year: Optional[int]
    total_funding_usd: Optional[float]
    last_funding_event: Optional[FundingEvent]
    founders: list[str] = []
    confidence: float = 1.0


def load_crunchbase_data(data_path: str) -> list[dict]:
    if not os.path.exists(data_path):
        log.warning("crunchbase_data_not_found", path=data_path)
        return []
    with open(data_path) as f:
        return json.load(f)


def lookup_company(company_name: str, data_path: str,
                   company_domain: Optional[str] = None,
                   crunchbase_id: Optional[str] = None) -> Optional[CrunchbaseProfile]:
    records = load_crunchbase_data(data_path)
    if not records:
        return None

    name_lower = company_name.lower()
    match = None

    for record in records:
        # Support both ODM field names ("id") and our sample schema ("crunchbase_id")
        rec_id = record.get("id") or record.get("crunchbase_id", "")
        if crunchbase_id and rec_id == crunchbase_id:
            match = record
            break
        rec_domain = record.get("domain", "").lower()
        if company_domain and rec_domain == company_domain.lower():
            match = record
            break
        # Support both "name" (ODM) and "company_name" (our schema)
        rec_name = (record.get("name") or record.get("company_name", "")).lower()
        if rec_name == name_lower or name_lower in rec_name:
            match = record
            break

    if not match:
        log.warning("crunchbase_no_match", company=company_name)
        return None

    funding_event = None
    # Support ODM flat fields and our nested last_funding_event dict
    nested_fe = match.get("last_funding_event") or {}
    last_funding = (match.get("last_funding_on") or match.get("last_funding_date")
                    or nested_fe.get("closed_at"))
    if last_funding:
        try:
            funding_date = datetime.strptime(last_funding[:10], "%Y-%m-%d")
            days_ago = (datetime.utcnow() - funding_date).days
            funding_event = FundingEvent(
                round_type=(match.get("last_funding_type")
                            or nested_fe.get("round_type", "unknown")),
                amount_usd=_parse_amount(
                    match.get("last_funding_total_usd")
                    or match.get("raised_amount_usd")
                    or nested_fe.get("amount_usd")
                ),
                announced_date=last_funding[:10],
                days_ago=days_ago,
            )
        except Exception:
            pass

    # Support headcount as a range string (ODM) or direct integer (our schema)
    raw_headcount = match.get("employee_count") or match.get("num_employees_enum", "")
    headcount_range = str(raw_headcount) if raw_headcount else ""
    headcount_estimate = (int(match["headcount_estimate"])
                          if isinstance(match.get("headcount_estimate"), (int, float))
                          else _estimate_headcount(headcount_range))

    # Support founded_year as int (our schema) or founded_on date string (ODM)
    founded_year = None
    if isinstance(match.get("founded_year"), int):
        founded_year = match["founded_year"]
    elif match.get("founded_on", ""):
        try:
            founded_year = int(match["founded_on"][:4])
        except (ValueError, TypeError):
            pass

    return CrunchbaseProfile(
        company_name=match.get("name") or match.get("company_name", company_name),
        crunchbase_id=match.get("id") or match.get("crunchbase_id"),
        domain=match.get("domain") or match.get("website"),
        description=match.get("short_description") or match.get("description"),
        industry=match.get("category_list") or match.get("industry"),
        location=match.get("city") or match.get("country_code") or match.get("headquarters"),
        headcount_range=headcount_range,
        headcount_estimate=headcount_estimate,
        founded_year=founded_year,
        total_funding_usd=_parse_amount(match.get("total_funding_usd")),
        last_funding_event=funding_event,
        founders=[f for f in [match.get("founder_names")] if f],
    )


def _parse_amount(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return None


def _estimate_headcount(headcount_range: str) -> Optional[int]:
    mapping = {
        "1-10": 5, "11-50": 30, "51-100": 75, "101-250": 175,
        "251-500": 375, "501-1000": 750, "1001-5000": 3000,
        "5001-10000": 7500, "10001+": 15000,
        "c_00001_00010": 5, "c_00011_00050": 30, "c_00051_00100": 75,
        "c_00101_00250": 175, "c_00251_00500": 375, "c_00501_01000": 750,
    }
    for k, v in mapping.items():
        if k.lower() in headcount_range.lower():
            return v
    return None
