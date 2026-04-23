import json
import os
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Optional

log = structlog.get_logger()

# OpenRouter requires these headers for proper routing and rate-limit attribution
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://tenacious.co",
    "X-Title": "Tenacious Conversion Engine",
}

SYSTEM_PROMPT = """You are a senior SDR at Tenacious Consulting and Outsourcing writing cold outbound emails.

Tenacious provides two services:
1. Managed talent outsourcing — dedicated engineering/data teams (3–12 engineers, 6–24 months)
2. Project-based consulting — time-boxed AI/data platform deliveries

TONE RULES (from style_guide.md — never violate these):
- Direct. No "I hope this email finds you well" or filler phrases.
- Grounded. Every claim must reference a signal from the brief.
- Curious. Ask rather than assert when signal confidence is low.
- Respectful of time. First paragraph carries the whole message.
- No exclamation marks. No buzzwords (synergy, leverage, ecosystem, world-class).
- Max 4 sentences in cold email body.
- Competitor gap framing: opportunity, not deficit. Never condescending.

HONESTY RULES (enforced, not optional):
- If honesty_flags includes "weak_hiring_velocity_signal": do NOT say "aggressively hiring" or "scaling fast"
- If honesty_flags includes "weak_ai_maturity_signal": use asking language for AI claims
- If honesty_flags includes "layoff_overrides_funding": lead with restructure framing, not growth framing
- If honesty_flags includes "conflicting_segment_signals": phrase leadership signal as "it looks like" not "you appointed"
- If honesty_flags includes "tech_stack_inferred_not_confirmed": qualify stack claims with "based on public signals"
- If honesty_flags includes "bench_gap_detected": do not assert capacity — route to discovery call
- Never commit to specific bench capacity numbers — route to discovery call

OUTPUT FORMAT (JSON only):
{
  "subject": "...",
  "body": "...",
  "variant": "signal_grounded | exploratory",
  "honesty_flags_applied": ["..."]
}"""


async def compose_outreach_email(
    brief: dict,
    classification,
    competitor_gap,
    contact_name: Optional[str],
    settings,
) -> dict:
    """
    Compose a signal-grounded outreach email using the LLM.
    Falls back to template if LLM is unavailable.
    """
    user_prompt = _build_prompt(brief, classification, competitor_gap, contact_name)

    if not settings.openrouter_api_key:
        log.warning("openrouter_key_missing", fallback="template")
        return _template_email(brief, classification, contact_name)

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers=OPENROUTER_HEADERS,
    )

    try:
        result = await _call_with_retry(client, settings.dev_model, SYSTEM_PROMPT, user_prompt)
        log.info("email_composed", variant=result.get("variant"), subject=result.get("subject"),
                 model=settings.dev_model)
        return result
    except Exception as e:
        log.error("compose_failed", error=str(e))
        return _template_email(brief, classification, contact_name)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _call_with_retry(client: AsyncOpenAI, model: str,
                            system: str, user: str) -> dict:
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    return json.loads(content)


def _build_prompt(brief: dict, classification, competitor_gap, contact_name: Optional[str]) -> str:
    segment = classification.segment if classification else "unknown"
    pitch = brief.get("recommended_pitch_angle", "")
    flags = brief.get("honesty_flags", [])

    return f"""Write a cold outreach email for this prospect.

SEGMENT: {segment}
PITCH ANGLE: {pitch}
CONTACT NAME: {contact_name or 'unknown'}

SIGNAL BRIEF:
- Headline: {brief.get('headline', 'N/A')}
- Funding: {brief.get('funding_signal', 'None detected')}
- Hiring: {brief.get('hiring_signal', 'None detected')}
- Layoff: {brief.get('layoff_signal', 'None detected')}
- Leadership: {brief.get('leadership_signal', 'None detected')}
- AI Maturity: {brief.get('ai_maturity_signal', 'N/A')}
- Competitor Gap: {brief.get('competitor_gap_signal', 'None detected')}

HONESTY FLAGS (must respect):
{json.dumps(flags, indent=2)}

ICP CONFIDENCE: {classification.confidence if classification else 0}

Write the email. Return JSON only."""


def _template_email(brief: dict, classification, contact_name: Optional[str]) -> dict:
    """Fallback template when LLM is unavailable."""
    name = contact_name.split()[0] if contact_name else "there"
    headline = brief.get("headline", "Reviewing your company's public signals")
    pitch = brief.get("recommended_pitch_angle", "Worth a 30-minute conversation?")
    flags = brief.get("honesty_flags", [])

    subject = f"Quick question about your engineering capacity"
    body = (
        f"Hi {name},\n\n"
        f"{headline}\n\n"
        f"{pitch}\n\n"
        f"Worth a 30-minute conversation? Happy to keep it concrete."
    )

    return {
        "subject": subject,
        "body": body,
        "variant": "exploratory",
        "honesty_flags_applied": flags,
    }
