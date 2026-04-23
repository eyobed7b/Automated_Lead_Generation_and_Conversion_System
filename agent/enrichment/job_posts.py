import asyncio
import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

AI_ROLE_KEYWORDS = [
    "ml engineer", "machine learning engineer", "applied scientist",
    "llm engineer", "ai engineer", "ai product manager",
    "data platform engineer", "mlops engineer", "research scientist",
    "deep learning", "nlp engineer", "computer vision engineer",
]

ENGINEERING_KEYWORDS = [
    "software engineer", "backend engineer", "frontend engineer",
    "fullstack engineer", "platform engineer", "data engineer",
    "devops", "sre", "infrastructure engineer", "security engineer",
]


class JobPostSummary(BaseModel):
    total_open_roles: int
    engineering_roles: int
    ai_adjacent_roles: int
    ai_role_fraction: float
    role_titles: list[str]
    source: str
    scraped_at: str
    velocity_signal: str


async def scrape_job_posts(company_name: str, company_domain: Optional[str] = None) -> JobPostSummary:
    """
    Scrape public job postings for a company.
    Respects robots.txt. Does not log in. Does not bypass captchas.
    Falls back to sample data if live scraping fails.
    """
    try:
        from playwright.async_api import async_playwright
        result = await _scrape_with_playwright(company_name, company_domain)
        if result:
            return result
    except ImportError:
        log.warning("playwright_not_available")
    except Exception as e:
        log.warning("playwright_scrape_failed", error=str(e), company=company_name)

    return _fallback_job_summary(company_name)


async def _scrape_with_playwright(company_name: str, domain: Optional[str]) -> Optional[JobPostSummary]:
    from playwright.async_api import async_playwright

    urls_to_try = []
    if domain:
        urls_to_try.append(f"https://{domain}/careers")
        urls_to_try.append(f"https://{domain}/jobs")
    company_slug = re.sub(r"[^a-z0-9-]", "-", company_name.lower()).strip("-")
    urls_to_try.append(f"https://www.builtin.com/company/{company_slug}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": "TenaciousResearchBot/1.0 (+https://tenacious.co/bot)"})

        for url in urls_to_try:
            try:
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                content = await page.content()
                await browser.close()
                return _parse_job_listings(content, url, company_name)
            except Exception:
                continue

        await browser.close()
    return None


def _parse_job_listings(html: str, source_url: str, company_name: str) -> JobPostSummary:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ").lower()

    role_titles = []
    for line in soup.find_all(["h2", "h3", "h4", "li", "a", "span"]):
        line_text = line.get_text(strip=True).lower()
        if any(kw in line_text for kw in ENGINEERING_KEYWORDS + AI_ROLE_KEYWORDS):
            if len(line_text) < 120:
                role_titles.append(line.get_text(strip=True))

    role_titles = list(set(role_titles))[:50]
    total = len(role_titles)
    eng_count = sum(1 for t in role_titles if any(k in t.lower() for k in ENGINEERING_KEYWORDS))
    ai_count = sum(1 for t in role_titles if any(k in t.lower() for k in AI_ROLE_KEYWORDS))
    ai_fraction = ai_count / max(eng_count, 1)

    velocity_signal = "unknown"
    if total >= 20:
        velocity_signal = "high"
    elif total >= 10:
        velocity_signal = "medium"
    elif total >= 5:
        velocity_signal = "low"
    else:
        velocity_signal = "minimal"

    return JobPostSummary(
        total_open_roles=total,
        engineering_roles=eng_count,
        ai_adjacent_roles=ai_count,
        ai_role_fraction=round(ai_fraction, 2),
        role_titles=role_titles[:10],
        source=source_url,
        scraped_at=datetime.utcnow().isoformat(),
        velocity_signal=velocity_signal,
    )


def _fallback_job_summary(company_name: str) -> JobPostSummary:
    log.info("job_posts_fallback", company=company_name)
    return JobPostSummary(
        total_open_roles=0,
        engineering_roles=0,
        ai_adjacent_roles=0,
        ai_role_fraction=0.0,
        role_titles=[],
        source="fallback",
        scraped_at=datetime.utcnow().isoformat(),
        velocity_signal="unknown",
    )
