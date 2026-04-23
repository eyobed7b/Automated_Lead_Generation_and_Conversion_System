import asyncio
import json
import os
import time
from typing import Optional
from pydantic import BaseModel
import structlog

from enrichment.crunchbase import lookup_company, CrunchbaseProfile
from enrichment.layoffs import check_layoffs, LayoffEvent
from enrichment.job_posts import scrape_job_posts, JobPostSummary
from enrichment.leadership import detect_leadership_changes, LeadershipChange
from enrichment.ai_maturity import score_ai_maturity, AIMaturityScore
from enrichment.competitor_gap import build_competitor_gap_brief, CompetitorGapBrief

log = structlog.get_logger()


class HiringSignalBrief(BaseModel):
    company_name: str
    crunchbase_profile: Optional[CrunchbaseProfile]
    layoff_event: Optional[LayoffEvent]
    job_posts: Optional[JobPostSummary]
    leadership_change: Optional[LeadershipChange]
    ai_maturity: AIMaturityScore
    competitor_gap: Optional[CompetitorGapBrief]
    enriched_at: str
    enrichment_duration_seconds: float
    data_sources: list[str]


async def enrich_prospect(
    company_name: str,
    company_domain: Optional[str],
    crunchbase_id: Optional[str],
    settings,
) -> HiringSignalBrief:
    """
    Full enrichment pipeline. Runs all signal sources and merges into brief.
    """
    start = time.monotonic()
    data_sources = []

    log.info("enrichment_start", company=company_name)

    # Run all enrichment tasks concurrently
    crunchbase_task = asyncio.create_task(
        _safe(lambda: lookup_company(
            company_name, settings.crunchbase_data_path,
            company_domain, crunchbase_id
        ))
    )
    layoffs_task = asyncio.create_task(
        _safe(lambda: check_layoffs(company_name, settings.layoffs_data_path))
    )
    job_posts_task = asyncio.create_task(
        scrape_job_posts(company_name, company_domain)
    )

    crunchbase_profile = await crunchbase_task
    layoff_event = await layoffs_task
    job_posts = await job_posts_task

    if crunchbase_profile:
        data_sources.append("crunchbase_odm")
    if layoff_event:
        data_sources.append("layoffs_fyi")
    if job_posts and job_posts.source != "fallback":
        data_sources.append("job_posts_scraper")

    # Leadership detection uses Crunchbase data
    crunchbase_dict = crunchbase_profile.dict() if crunchbase_profile else None
    leadership_change = await detect_leadership_changes(company_name, crunchbase_dict)
    if leadership_change:
        data_sources.append("leadership_detection")

    # AI maturity scoring
    ai_maturity = score_ai_maturity(
        job_posts=job_posts,
        company_description=crunchbase_profile.description if crunchbase_profile else None,
        stack_signals=_infer_stack_from_description(
            crunchbase_profile.description if crunchbase_profile else ""
        ),
        has_ai_leadership=False,
        has_github_ai=False,
        has_executive_ai_commentary=False,
        has_strategic_ai_comms=False,
    )
    data_sources.append("ai_maturity_scorer")

    # Competitor gap brief
    competitor_gap = build_competitor_gap_brief(
        prospect_name=company_name,
        prospect_ai_score=ai_maturity.score,
        prospect_ai_signals=ai_maturity.signals,
        sector=crunchbase_profile.industry if crunchbase_profile else None,
    )
    data_sources.append("competitor_gap_analysis")

    duration = time.monotonic() - start

    brief = HiringSignalBrief(
        company_name=company_name,
        crunchbase_profile=crunchbase_profile,
        layoff_event=layoff_event,
        job_posts=job_posts,
        leadership_change=leadership_change,
        ai_maturity=ai_maturity,
        competitor_gap=competitor_gap,
        enriched_at=__import__("datetime").datetime.utcnow().isoformat(),
        enrichment_duration_seconds=round(duration, 2),
        data_sources=data_sources,
    )

    # Save to disk for CRM reference
    await _save_brief(brief, settings)

    log.info("enrichment_complete",
             company=company_name,
             duration=duration,
             ai_score=ai_maturity.score,
             sources=data_sources)

    return brief


async def _safe(fn):
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            return await result
        return result
    except Exception as e:
        log.error("enrichment_step_failed", error=str(e))
        return None


def _infer_stack_from_description(description: Optional[str]) -> list[str]:
    if not description:
        return []
    AI_STACK = ["dbt", "snowflake", "databricks", "spark", "pytorch",
                "tensorflow", "mlflow", "kubeflow", "ray", "vllm",
                "weights and biases", "wandb", "airflow", "kafka"]
    desc_lower = (description or "").lower()
    return [s for s in AI_STACK if s in desc_lower]


async def _save_brief(brief: HiringSignalBrief, settings) -> None:
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "briefs")
    os.makedirs(output_dir, exist_ok=True)
    safe_name = brief.company_name.lower().replace(" ", "_").replace("/", "_")
    path = os.path.join(output_dir, f"{safe_name}_brief.json")
    try:
        with open(path, "w") as f:
            f.write(brief.model_dump_json(indent=2))
    except Exception as e:
        log.error("brief_save_failed", error=str(e))
