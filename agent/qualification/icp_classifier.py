from typing import Optional
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

SEGMENTS = [
    "segment_1_series_a_b",
    "segment_2_mid_market_restructure",
    "segment_3_leadership_transition",
    "segment_4_specialized_capability",
]


class ICPClassification(BaseModel):
    segment: Optional[str]
    confidence: float
    reason: str
    disqualified: bool
    disqualify_reason: Optional[str]
    abstain: bool
    abstain_reason: Optional[str]
    all_segment_scores: dict[str, float]


def classify_icp(brief, settings) -> ICPClassification:
    """
    Classify a prospect into one of the four ICP segments.
    Returns confidence score and abstains if below threshold.
    """
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}

    profile = brief.crunchbase_profile
    layoff = brief.layoff_event
    job_posts = brief.job_posts
    leadership = brief.leadership_change
    ai = brief.ai_maturity

    headcount = (profile.headcount_estimate or 0) if profile else 0
    funding = profile.last_funding_event if profile else None
    funding_days = funding.days_ago if funding else 9999
    funding_amount = (funding.amount_usd or 0) if funding else 0
    layoff_recent = layoff is not None and layoff.is_recent
    total_roles = (job_posts.total_open_roles or 0) if job_posts else 0

    # ── Segment 1: Recently-funded Series A/B ──────────────────────────
    s1 = 0.0
    s1_reason = []
    if funding and funding_days <= 180:
        if funding.round_type and any(t in funding.round_type.lower() for t in ["series_a", "series_b", "series a", "series b", "a", "b"]):
            s1 += 0.5
            s1_reason.append(f"Series A/B funding {funding_days}d ago")
        elif funding_amount and 5_000_000 <= funding_amount <= 30_000_000:
            s1 += 0.4
            s1_reason.append(f"Funding ${funding_amount/1e6:.1f}M {funding_days}d ago in range")
    if 15 <= headcount <= 80:
        s1 += 0.2
        s1_reason.append(f"Headcount {headcount} in 15–80 range")
    if total_roles >= 3:
        s1 += 0.2
        s1_reason.append(f"{total_roles} open roles")
    if layoff_recent:
        s1 *= 0.2
        s1_reason.append("PENALIZED: recent layoff (route to Seg 2)")
    scores["segment_1_series_a_b"] = round(min(s1, 1.0), 2)
    reasons["segment_1_series_a_b"] = "; ".join(s1_reason) or "No qualifying signals"

    # ── Segment 2: Mid-market restructuring ────────────────────────────
    s2 = 0.0
    s2_reason = []
    if 200 <= headcount <= 2000:
        s2 += 0.3
        s2_reason.append(f"Headcount {headcount} in 200–2,000 range")
    if layoff_recent:
        s2 += 0.5
        s2_reason.append(f"Layoff {layoff.days_ago}d ago")
    if total_roles >= 2:
        s2 += 0.2
        s2_reason.append(f"{total_roles} roles still open")
    scores["segment_2_mid_market_restructure"] = round(min(s2, 1.0), 2)
    reasons["segment_2_mid_market_restructure"] = "; ".join(s2_reason) or "No qualifying signals"

    # ── Segment 3: Engineering leadership transition ────────────────────
    s3 = 0.0
    s3_reason = []
    if leadership and leadership.is_recent:
        s3 += 0.8
        s3_reason.append(f"New {leadership.role} {leadership.days_ago}d ago (conf {leadership.confidence:.0%})")
    elif leadership and leadership.days_ago and leadership.days_ago <= 120:
        s3 += 0.4
        s3_reason.append(f"Leadership change {leadership.days_ago}d ago (approaching window)")
    scores["segment_3_leadership_transition"] = round(min(s3, 1.0), 2)
    reasons["segment_3_leadership_transition"] = "; ".join(s3_reason) or "No leadership change detected"

    # ── Segment 4: Specialized capability gaps ─────────────────────────
    s4 = 0.0
    s4_reason = []
    if ai.score >= 2:
        s4 += 0.5
        s4_reason.append(f"AI maturity {ai.score}/3 ({ai.confidence_label} confidence)")
        if (job_posts and job_posts.ai_adjacent_roles >= 2):
            s4 += 0.3
            s4_reason.append(f"{job_posts.ai_adjacent_roles} AI-adjacent roles open")
    else:
        s4_reason.append(f"AI maturity {ai.score}/3 — below threshold for Seg 4 (requires 2+)")
    scores["segment_4_specialized_capability"] = round(min(s4, 1.0), 2)
    reasons["segment_4_specialized_capability"] = "; ".join(s4_reason) or "AI maturity too low"

    # ── Pick best segment ───────────────────────────────────────────────
    best_segment = max(scores, key=lambda k: scores[k])
    best_score = scores[best_segment]

    if best_score < settings.min_icp_confidence:
        return ICPClassification(
            segment=None,
            confidence=best_score,
            reason=f"Best segment {best_segment} scored {best_score:.2f} — below threshold {settings.min_icp_confidence}",
            disqualified=False,
            disqualify_reason=None,
            abstain=True,
            abstain_reason=f"Confidence {best_score:.2f} below minimum {settings.min_icp_confidence}. Flag for human review.",
            all_segment_scores=scores,
        )

    log.info("icp_classified",
             company=brief.company_name,
             segment=best_segment,
             confidence=best_score)

    return ICPClassification(
        segment=best_segment,
        confidence=best_score,
        reason=reasons[best_segment],
        disqualified=False,
        disqualify_reason=None,
        abstain=False,
        abstain_reason=None,
        all_segment_scores=scores,
    )
