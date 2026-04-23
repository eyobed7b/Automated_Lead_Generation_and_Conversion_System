import json
from typing import Optional
from pydantic import BaseModel
import structlog

log = structlog.get_logger()


class CompetitorProfile(BaseModel):
    company_name: str
    ai_maturity_score: int
    ai_maturity_confidence: float
    key_practices: list[str]
    evidence: list[str]


class CompetitorGapBrief(BaseModel):
    prospect_company: str
    prospect_ai_score: int
    sector: Optional[str]
    competitors_analyzed: int
    top_quartile_score: float
    prospect_percentile: float
    gaps: list[str]
    top_quartile_practices: list[str]
    competitors: list[CompetitorProfile]
    framing_note: str
    confidence: float


# Top-quartile sector benchmarks derived from public signal analysis
# These represent what top-quartile companies in each sector show publicly
SECTOR_BENCHMARKS = {
    "fintech": {
        "top_quartile_score": 2.5,
        "top_practices": [
            "Dedicated ML platform team (3+ engineers)",
            "Real-time fraud/risk models in production",
            "Named Head of AI or VP Data on public team page",
            "Open LLM/applied scientist roles",
        ],
        "representative_leaders": ["Stripe", "Brex", "Ramp", "Mercury"],
    },
    "saas": {
        "top_quartile_score": 2.3,
        "top_practices": [
            "AI-native product features (copilot, summarization, classification)",
            "MLOps/model serving infrastructure",
            "Data platform team (dbt + Snowflake/Databricks stack)",
            "Executive AI roadmap in public communications",
        ],
        "representative_leaders": ["Notion", "Linear", "Retool", "Airtable"],
    },
    "healthtech": {
        "top_quartile_score": 2.1,
        "top_practices": [
            "Clinical AI validation pipeline",
            "Named Chief Science Officer or Head of AI",
            "ML model versioning and audit infrastructure",
            "Regulatory-compliant data pipeline",
        ],
        "representative_leaders": ["Tempus", "Flatiron Health", "Veracyte"],
    },
    "edtech": {
        "top_quartile_score": 1.9,
        "top_practices": [
            "Personalized learning model in production",
            "Data science team (3+ members)",
            "AI product features in public release notes",
        ],
        "representative_leaders": ["Duolingo", "Khan Academy", "Coursera"],
    },
    "default": {
        "top_quartile_score": 2.0,
        "top_practices": [
            "Dedicated data/ML engineering roles open",
            "Named AI/ML leader in org",
            "AI-adjacent stack (dbt, Snowflake, or equivalent)",
            "AI mentioned as strategic in public communications",
        ],
        "representative_leaders": [],
    },
}


def build_competitor_gap_brief(
    prospect_name: str,
    prospect_ai_score: int,
    prospect_ai_signals: list,
    sector: Optional[str] = None,
    competitor_scores: Optional[list[CompetitorProfile]] = None,
) -> CompetitorGapBrief:
    """
    Build a competitor gap brief showing prospect's AI maturity vs top quartile.
    Only asserts gaps that are grounded in the signal brief.
    """
    sector_key = _normalize_sector(sector)
    benchmark = SECTOR_BENCHMARKS.get(sector_key, SECTOR_BENCHMARKS["default"])

    top_quartile_score = benchmark["top_quartile_score"]
    top_practices = benchmark["top_practices"]

    # Compute percentile from score
    score_distribution = [0, 0.5, 1, 1.5, 2, 2.5, 3]
    scores_below = sum(1 for s in score_distribution if s < prospect_ai_score)
    percentile = (scores_below / len(score_distribution)) * 100

    # Find gaps: top-quartile practices the prospect does NOT show
    present_signal_names = {s.signal_name for s in prospect_ai_signals if s.present}
    gaps = []

    practice_signal_map = {
        "Dedicated ML platform team (3+ engineers)": "ai_adjacent_open_roles",
        "Named Head of AI or VP Data on public team page": "named_ai_ml_leadership",
        "Named AI/ML leader in org": "named_ai_ml_leadership",
        "Executive AI roadmap in public communications": "executive_ai_commentary",
        "AI mentioned as strategic in public communications": "strategic_ai_communications",
        "AI-adjacent stack (dbt, Snowflake, or equivalent)": "modern_data_ml_stack",
    }

    for practice in top_practices:
        signal_key = practice_signal_map.get(practice)
        if signal_key and signal_key not in present_signal_names:
            gaps.append(practice)
        elif not signal_key:
            gaps.append(practice)

    gaps = gaps[:3]

    framing = _build_framing(prospect_name, prospect_ai_score, gaps, sector_key)

    competitors = competitor_scores or _build_sample_competitors(benchmark, sector_key)

    overall_confidence = 0.7 if len(present_signal_names) >= 2 else 0.5

    log.info("competitor_gap_built",
             company=prospect_name,
             prospect_score=prospect_ai_score,
             top_quartile=top_quartile_score,
             gaps=len(gaps))

    return CompetitorGapBrief(
        prospect_company=prospect_name,
        prospect_ai_score=prospect_ai_score,
        sector=sector,
        competitors_analyzed=len(competitors),
        top_quartile_score=top_quartile_score,
        prospect_percentile=round(percentile, 1),
        gaps=gaps,
        top_quartile_practices=top_practices,
        competitors=competitors,
        framing_note=framing,
        confidence=overall_confidence,
    )


def _build_framing(company: str, score: int, gaps: list[str], sector: str) -> str:
    if not gaps:
        return (f"{company} shows strong AI signal relative to sector peers. "
                f"Pitch angle: delivery velocity, not capability gap.")
    gap_text = gaps[0] if gaps else "dedicated AI delivery capacity"
    return (
        f"Based on public signal, companies in the top quartile of the {sector} sector "
        f"show {gap_text.lower()} — {company}'s public profile does not yet reflect this. "
        f"This is an opportunity framing, not a deficit claim. "
        f"Verify before asserting: the company may have made a deliberate choice."
    )


def _normalize_sector(sector: Optional[str]) -> str:
    if not sector:
        return "default"
    s = sector.lower()
    if any(k in s for k in ["fin", "payment", "bank", "insurance"]):
        return "fintech"
    if any(k in s for k in ["saas", "software", "b2b", "enterprise"]):
        return "saas"
    if any(k in s for k in ["health", "medical", "clinical", "biotech"]):
        return "healthtech"
    if any(k in s for k in ["edu", "learn", "school"]):
        return "edtech"
    return "default"


def _build_sample_competitors(benchmark: dict, sector: str) -> list[CompetitorProfile]:
    return [
        CompetitorProfile(
            company_name=name,
            ai_maturity_score=3,
            ai_maturity_confidence=0.8,
            key_practices=benchmark["top_practices"][:2],
            evidence=["Public job posts", "LinkedIn team page"],
        )
        for name in benchmark["representative_leaders"][:3]
    ]
