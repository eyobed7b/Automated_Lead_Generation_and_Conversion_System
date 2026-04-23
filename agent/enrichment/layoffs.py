import csv
import os
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

LOOKBACK_DAYS = 120


class LayoffEvent(BaseModel):
    company: str
    date: str
    headcount_cut: Optional[int]
    percentage_cut: Optional[float]
    source: Optional[str]
    days_ago: int
    is_recent: bool


def check_layoffs(company_name: str, data_path: str) -> Optional[LayoffEvent]:
    """Check layoffs.fyi CSV for a layoff event in the last 120 days."""
    if not os.path.exists(data_path):
        log.warning("layoffs_data_not_found", path=data_path)
        return None

    name_lower = company_name.lower()
    cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)

    try:
        with open(data_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_company = (row.get("Company") or row.get("company") or "").lower()
                if name_lower not in row_company and row_company not in name_lower:
                    continue

                date_str = row.get("Date") or row.get("date") or ""
                if not date_str:
                    continue

                try:
                    event_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
                except ValueError:
                    try:
                        event_date = datetime.strptime(date_str, "%m/%d/%Y")
                    except ValueError:
                        continue

                days_ago = (datetime.utcnow() - event_date).days
                is_recent = event_date >= cutoff

                headcount_raw = row.get("Laid_Off") or row.get("laid_off") or row.get("Headcount") or ""
                pct_raw = row.get("Percentage") or row.get("percentage") or ""

                return LayoffEvent(
                    company=row.get("Company") or company_name,
                    date=date_str[:10],
                    headcount_cut=_safe_int(headcount_raw),
                    percentage_cut=_safe_float(pct_raw),
                    source=row.get("Source") or row.get("source"),
                    days_ago=days_ago,
                    is_recent=is_recent,
                )
    except Exception as e:
        log.error("layoffs_parse_error", error=str(e), company=company_name)

    return None


def _safe_int(val: str) -> Optional[int]:
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _safe_float(val: str) -> Optional[float]:
    try:
        return float(str(val).replace("%", "").strip())
    except (ValueError, TypeError):
        return None
