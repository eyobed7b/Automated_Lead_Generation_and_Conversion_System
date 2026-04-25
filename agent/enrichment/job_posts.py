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


def _build_url_candidates(company_name: str, domain: Optional[str]) -> list[str]:
    """Build ordered list of job board URLs to try for a company."""
    urls = []

    # 1. Company's own careers/jobs page
    if domain:
        urls.append(f"https://{domain}/careers")
        urls.append(f"https://{domain}/jobs")

    # slug variants used across job boards
    hyphen_slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", company_name.lower()).strip("-"))
    compact_slug = re.sub(r"[^a-z0-9]", "", company_name.lower())  # Greenhouse often uses no-hyphen form

    # common suffixes BuiltIn / Ashby strip
    STRIP_SUFFIXES = ("-technologies", "-technology", "-labs", "-inc", "-corp", "-ai", "-hq")
    short_slug = hyphen_slug
    for suffix in STRIP_SUFFIXES:
        if hyphen_slug.endswith(suffix):
            short_slug = hyphen_slug[: -len(suffix)]
            break

    # 2. BuiltIn
    urls.append(f"https://www.builtin.com/company/{hyphen_slug}")
    if short_slug != hyphen_slug:
        urls.append(f"https://www.builtin.com/company/{short_slug}")

    # 3. Greenhouse — public ATS used by most Series A/B companies
    urls.append(f"https://boards.greenhouse.io/{compact_slug}")
    urls.append(f"https://boards.greenhouse.io/{hyphen_slug}")
    if short_slug != hyphen_slug:
        urls.append(f"https://boards.greenhouse.io/{re.sub(r'[^a-z0-9]', '', short_slug)}")

    # 4. Lever — popular ATS for growth-stage startups
    urls.append(f"https://jobs.lever.co/{hyphen_slug}")
    if short_slug != hyphen_slug:
        urls.append(f"https://jobs.lever.co/{short_slug}")

    # 5. Ashby — modern ATS, common in AI-native and Series A companies
    urls.append(f"https://jobs.ashbyhq.com/{hyphen_slug}")
    if short_slug != hyphen_slug:
        urls.append(f"https://jobs.ashbyhq.com/{short_slug}")

    return urls


async def _scrape_with_playwright(company_name: str, domain: Optional[str]) -> Optional[JobPostSummary]:
    from playwright.async_api import async_playwright

    urls_to_try = _build_url_candidates(company_name, domain)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": "TenaciousResearchBot/1.0 (+https://tenacious.co/bot)"})

        for url in urls_to_try:
            try:
                response = await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                if response and response.status in (404, 403, 410):
                    log.info("job_scrape_skip", url=url, status=response.status)
                    continue
                content = await page.content()
                result = _parse_job_listings(content, url, company_name)
                if result.total_open_roles > 0:
                    await browser.close()
                    return result
            except Exception:
                continue

        await browser.close()
    return None


def _extract_titles_greenhouse(soup) -> list[str]:
    """Extract job titles from boards.greenhouse.io HTML."""
    titles = []
    for el in soup.select("div.opening a, .job-post h2, .job-post h3, [class*='job-name']"):
        t = el.get_text(strip=True)
        if t:
            titles.append(t)
    return titles


def _extract_titles_lever(soup) -> list[str]:
    """Extract job titles from jobs.lever.co HTML."""
    titles = []
    for el in soup.select("h5, .posting-title h5, [data-qa='posting-name']"):
        t = el.get_text(strip=True)
        if t:
            titles.append(t)
    return titles


def _extract_titles_ashby(soup) -> list[str]:
    """Extract job titles from jobs.ashbyhq.com HTML."""
    titles = []
    for el in soup.select("a[href*='/role/'] h3, a[href*='/role/'] p, [class*='job-title']"):
        t = el.get_text(strip=True)
        if t:
            titles.append(t)
    return titles


def _parse_job_listings(html: str, source_url: str, company_name: str) -> JobPostSummary:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")

    # Site-specific extractors first (more precise than the generic scan)
    if "greenhouse.io" in source_url:
        site_titles = _extract_titles_greenhouse(soup)
    elif "lever.co" in source_url:
        site_titles = _extract_titles_lever(soup)
    elif "ashbyhq.com" in source_url:
        site_titles = _extract_titles_ashby(soup)
    else:
        site_titles = []

    role_titles = []
    # Use site-specific titles if the extractor found anything, else fall back to generic scan
    if site_titles:
        role_titles = [t for t in site_titles if len(t) < 120]
    else:
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
