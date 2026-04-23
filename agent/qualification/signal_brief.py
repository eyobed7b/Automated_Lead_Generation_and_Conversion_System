from typing import Optional
from pydantic import BaseModel


class SignalBrief(BaseModel):
    headline: str
    funding_signal: Optional[str]
    hiring_signal: Optional[str]
    layoff_signal: Optional[str]
    leadership_signal: Optional[str]
    ai_maturity_signal: str
    competitor_gap_signal: Optional[str]
    recommended_pitch_angle: str
    honesty_flags: list[str]


def build_signal_brief(brief, classification) -> dict:
    """
    Convert enrichment data into a structured signal brief for the outreach composer.
    Honesty flag names match hiring_signal_brief.schema.json enum values.
    """
    honesty_flags = []
    profile = brief.crunchbase_profile
    funding = profile.last_funding_event if profile else None
    job_posts = brief.job_posts
    ai = brief.ai_maturity
    layoff = brief.layoff_event
    layoff_recent = layoff is not None and layoff.is_recent

    # Funding signal
    funding_signal = None
    if funding and funding.days_ago <= 180:
        amt = f"${funding.amount_usd/1e6:.0f}M " if funding.amount_usd else ""
        funding_signal = f"Closed {amt}{funding.round_type} {funding.days_ago} days ago."
    elif funding and 180 < funding.days_ago <= 365:
        funding_signal = (f"Raised {funding.round_type} approximately "
                          f"{funding.days_ago // 30} months ago (signal aging).")

    # Layoff + funding interaction flag
    if layoff_recent and funding:
        honesty_flags.append("layoff_overrides_funding")

    # Hiring signal
    hiring_signal = None
    if job_posts and job_posts.total_open_roles >= 5:
        hiring_signal = (f"{job_posts.total_open_roles} open roles detected "
                         f"({job_posts.engineering_roles} engineering, "
                         f"{job_posts.ai_adjacent_roles} AI-adjacent).")
    elif job_posts and 0 < job_posts.total_open_roles < 5:
        hiring_signal = f"{job_posts.total_open_roles} open roles detected."
        honesty_flags.append("weak_hiring_velocity_signal")
    else:
        honesty_flags.append("weak_hiring_velocity_signal")

    # Layoff signal
    layoff_signal = None
    if layoff_recent:
        layoff_signal = (f"Layoff event {layoff.days_ago} days ago "
                         f"({layoff.percentage_cut or '?'}% headcount cut).")

    # Leadership signal
    leadership_signal = None
    if brief.leadership_change and brief.leadership_change.is_recent:
        lc = brief.leadership_change
        leadership_signal = (f"New {lc.role} appointed {lc.days_ago} days ago. "
                             f"Confidence: {lc.confidence:.0%}.")
        if lc.confidence < 0.7:
            honesty_flags.append("conflicting_segment_signals")

    # AI maturity signal
    ai_signal = f"AI maturity score: {ai.score}/3 ({ai.confidence_label} confidence). {ai.summary}"
    if ai.confidence_label == "low":
        honesty_flags.append("weak_ai_maturity_signal")

    # Competitor gap signal
    gap_signal = None
    if brief.competitor_gap and brief.competitor_gap.gaps:
        gaps_text = "; ".join(brief.competitor_gap.gaps[:2])
        confidence_note = "" if brief.competitor_gap.confidence >= 0.6 else " (low confidence — ask, don't assert)"
        gap_signal = (f"Top-quartile gap vs sector: {gaps_text}. "
                      f"Confidence: {brief.competitor_gap.confidence:.0%}{confidence_note}.")

    # Tech stack always inferred from job posts / description
    honesty_flags.append("tech_stack_inferred_not_confirmed")

    # Headline
    headline = _build_headline(brief, classification, honesty_flags)

    pitch_angle = _pitch_angle(classification.segment, ai.pitch_language_key, bool(layoff_signal))

    return {
        "headline": headline,
        "funding_signal": funding_signal,
        "hiring_signal": hiring_signal,
        "layoff_signal": layoff_signal,
        "leadership_signal": leadership_signal,
        "ai_maturity_signal": ai_signal,
        "competitor_gap_signal": gap_signal,
        "recommended_pitch_angle": pitch_angle,
        "honesty_flags": honesty_flags,
        "icp_segment": classification.segment,
        "icp_confidence": classification.confidence,
    }


def _build_headline(brief, classification, flags: list[str]) -> str:
    profile = brief.crunchbase_profile
    funding = profile.last_funding_event if profile else None
    job_posts = brief.job_posts

    if funding and funding.days_ago <= 180 and "weak_hiring_velocity_signal" not in flags:
        amt = f"${funding.amount_usd/1e6:.0f}M " if funding.amount_usd else ""
        roles = getattr(job_posts, "total_open_roles", 0) or 0
        return (f"Closed {amt}{funding.round_type} {funding.days_ago}d ago "
                f"with {roles} open engineering roles.")
    if brief.leadership_change and brief.leadership_change.is_recent:
        lc = brief.leadership_change
        return f"New {lc.role} appointed {lc.days_ago} days ago."
    if brief.layoff_event and brief.layoff_event.is_recent:
        return f"Restructuring in progress — layoff {brief.layoff_event.days_ago}d ago."
    return f"Reviewing {brief.company_name}'s public signals for fit."


def _pitch_angle(segment: Optional[str], ai_key: str, has_layoff: bool) -> str:
    if segment == "segment_1_series_a_b":
        if ai_key in ("active_ai", "emerging_ai"):
            return "Scale your AI team faster than in-house hiring can support."
        return "Stand up your first AI function with a dedicated squad."
    if segment == "segment_2_mid_market_restructure":
        if ai_key in ("active_ai", "emerging_ai"):
            return "Maintain AI delivery velocity at lower cost — offshore equivalents for your existing roles."
        return "Replace higher-cost roles with offshore equivalents; keep delivery capacity."
    if segment == "segment_3_leadership_transition":
        return "New engineering leaders typically reassess vendor mix in their first 90 days."
    if segment == "segment_4_specialized_capability":
        return "Project-based engagement for the specific capability gap — bench matched to your stack."
    return "Exploring fit for talent outsourcing or project-based consulting."
