from typing import Optional
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

# Signal weights as defined in the challenge brief
SIGNAL_WEIGHTS = {
    "ai_adjacent_roles": "high",
    "named_ai_leadership": "high",
    "github_ai_activity": "medium",
    "executive_commentary": "medium",
    "modern_ml_stack": "low",
    "strategic_communications": "low",
}

AI_STACK_SIGNALS = [
    "dbt", "snowflake", "databricks", "weights and biases", "wandb",
    "ray", "vllm", "mlflow", "kubeflow", "airflow", "spark",
    "pytorch", "tensorflow", "hugging face", "langchain", "openai",
]

AI_LEADERSHIP_TITLES = [
    "head of ai", "head of ml", "vp data", "vp of data",
    "chief scientist", "chief ai officer", "caio",
    "director of ai", "director of ml", "director of data science",
    "head of data science",
]


class AIMaturitySignal(BaseModel):
    signal_name: str
    present: bool
    weight: str
    justification: str
    confidence: float


class AIMaturityScore(BaseModel):
    score: int
    confidence: float
    confidence_label: str
    signals: list[AIMaturitySignal]
    summary: str
    pitch_language_key: str


def score_ai_maturity(
    job_posts,
    company_description: Optional[str] = None,
    stack_signals: Optional[list[str]] = None,
    has_ai_leadership: bool = False,
    ai_leadership_title: Optional[str] = None,
    has_github_ai: bool = False,
    has_executive_ai_commentary: bool = False,
    has_strategic_ai_comms: bool = False,
) -> AIMaturityScore:
    """
    Score AI maturity 0–3 based on public signals.
    Carries per-signal confidence and justification.
    """
    signals: list[AIMaturitySignal] = []
    weighted_score = 0.0
    max_score = 0.0

    # Signal 1: AI-adjacent open roles (HIGH weight)
    ai_role_fraction = getattr(job_posts, "ai_role_fraction", 0)
    ai_role_count = getattr(job_posts, "ai_adjacent_roles", 0)
    role_titles = getattr(job_posts, "role_titles", [])
    ai_roles_present = ai_role_fraction > 0.1 or ai_role_count >= 2

    signals.append(AIMaturitySignal(
        signal_name="ai_adjacent_open_roles",
        present=ai_roles_present,
        weight="high",
        justification=f"{ai_role_count} AI-adjacent roles open ({ai_role_fraction:.0%} of engineering openings). "
                      f"Titles: {', '.join(role_titles[:3]) or 'none detected'}.",
        confidence=0.85 if ai_role_count > 0 else 0.6,
    ))
    max_score += 2.0
    if ai_roles_present:
        weighted_score += 2.0 * (0.8 if ai_role_count >= 3 else 0.4)

    # Signal 2: Named AI/ML leadership (HIGH weight)
    signals.append(AIMaturitySignal(
        signal_name="named_ai_ml_leadership",
        present=has_ai_leadership,
        weight="high",
        justification=f"AI/ML leadership role detected: {ai_leadership_title}" if has_ai_leadership
                      else "No Head of AI/VP Data/Chief Scientist detected on public team page.",
        confidence=0.9 if has_ai_leadership else 0.7,
    ))
    max_score += 2.0
    if has_ai_leadership:
        weighted_score += 2.0

    # Signal 3: GitHub AI activity (MEDIUM weight)
    signals.append(AIMaturitySignal(
        signal_name="public_github_ai_activity",
        present=has_github_ai,
        weight="medium",
        justification="Recent commits on AI/ML repos detected." if has_github_ai
                      else "No public GitHub AI activity detected (absence is not proof — many keep AI work private).",
        confidence=0.75 if has_github_ai else 0.5,
    ))
    max_score += 1.0
    if has_github_ai:
        weighted_score += 1.0

    # Signal 4: Executive commentary on AI (MEDIUM weight)
    signals.append(AIMaturitySignal(
        signal_name="executive_ai_commentary",
        present=has_executive_ai_commentary,
        weight="medium",
        justification="CEO/CTO posts or interviews naming AI as strategic detected." if has_executive_ai_commentary
                      else "No executive AI commentary found in public posts/interviews.",
        confidence=0.8 if has_executive_ai_commentary else 0.6,
    ))
    max_score += 1.0
    if has_executive_ai_commentary:
        weighted_score += 1.0

    # Signal 5: Modern ML stack (LOW weight)
    stack_present = bool(stack_signals and any(
        s.lower() in " ".join(stack_signals).lower() for s in AI_STACK_SIGNALS
    ))
    stack_matches = [s for s in (stack_signals or []) if s.lower() in " ".join(AI_STACK_SIGNALS)]
    signals.append(AIMaturitySignal(
        signal_name="modern_data_ml_stack",
        present=stack_present,
        weight="low",
        justification=f"ML stack tools detected: {', '.join(stack_matches[:5])}" if stack_present
                      else "No modern ML stack tools detected via BuiltWith/Wappalyzer.",
        confidence=0.7,
    ))
    max_score += 0.5
    if stack_present:
        weighted_score += 0.5

    # Signal 6: Strategic AI communications (LOW weight)
    signals.append(AIMaturitySignal(
        signal_name="strategic_ai_communications",
        present=has_strategic_ai_comms,
        weight="low",
        justification="AI positioned as company priority in fundraising/annual reports." if has_strategic_ai_comms
                      else "No strategic AI communications found.",
        confidence=0.7,
    ))
    max_score += 0.5
    if has_strategic_ai_comms:
        weighted_score += 0.5

    # Normalize to 0–3
    normalized = (weighted_score / max_score) * 3 if max_score > 0 else 0
    score = min(3, int(round(normalized)))

    # Overall confidence = weighted average of present signal confidences
    present_signals = [s for s in signals if s.present]
    if present_signals:
        high_conf = [s.confidence for s in present_signals if s.weight == "high"]
        med_conf = [s.confidence for s in present_signals if s.weight == "medium"]
        low_conf = [s.confidence for s in present_signals if s.weight == "low"]
        overall_conf = (
            sum(high_conf) * 2 + sum(med_conf) * 1 + sum(low_conf) * 0.5
        ) / max(len(high_conf) * 2 + len(med_conf) + len(low_conf) * 0.5, 1)
    else:
        overall_conf = 0.3

    confidence_label = (
        "high" if overall_conf >= 0.75 else
        "medium" if overall_conf >= 0.55 else "low"
    )

    pitch_key = _pitch_language_key(score, confidence_label)
    summary = _build_summary(score, signals, confidence_label)

    log.info("ai_maturity_scored", score=score, confidence=overall_conf, label=confidence_label)

    return AIMaturityScore(
        score=score,
        confidence=round(overall_conf, 2),
        confidence_label=confidence_label,
        signals=signals,
        summary=summary,
        pitch_language_key=pitch_key,
    )


def _pitch_language_key(score: int, confidence: str) -> str:
    if score == 0:
        return "no_ai_signal"
    if score == 1:
        return "early_ai"
    if score == 2 and confidence == "low":
        return "emerging_ai_weak_signal"
    if score == 2:
        return "emerging_ai"
    return "active_ai"


def _build_summary(score: int, signals: list[AIMaturitySignal], confidence: str) -> str:
    present = [s.signal_name for s in signals if s.present]
    absent = [s.signal_name for s in signals if not s.present]

    base = {
        0: "No public AI engagement signal detected.",
        1: "Early/minimal AI signal — one or two weak indicators present.",
        2: "Moderate AI engagement — building toward an AI function.",
        3: "Active AI function with multiple strong public signals.",
    }[score]

    if present:
        base += f" Present signals: {', '.join(present)}."
    return base
