import json
import os
import time
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Optional

log = structlog.get_logger()

OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://tenacious.co",
    "X-Title": "Tenacious Conversion Engine",
}


# Use langfuse.openai drop-in if keys configured — auto-traces every LLM call
def _make_openai_client(settings):
    try:
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
            os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
            os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
            from langfuse.openai import AsyncOpenAI
            log.info("langfuse_tracing_enabled")
        else:
            from openai import AsyncOpenAI
    except Exception:
        from openai import AsyncOpenAI
    return AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers=OPENROUTER_HEADERS,
    )

SYSTEM_PROMPT = """You are a senior SDR at Tenacious Consulting and Outsourcing writing Email 1 of a 3-email cold outreach sequence.

Tenacious provides two services:
1. Managed talent outsourcing — dedicated engineering/data teams (3–12 engineers, 6–24 months) based in Addis Ababa
2. Project-based consulting — time-boxed AI/data platform deliveries

SEQUENCE CONTEXT: This is Email 1 (Day 0). A follow-up (Day 5) adds a competitor-gap data point if no reply. A gracious close (Day 12) ends the thread.

SUBJECT LINE — pick the pattern matching the highest-confidence signal:
- Segment 1 (Series A/B funded): "Context: [specific funding event]"
- Segment 2 (restructure): "Note on [specific restructure or layoff event]"
- Segment 3 (leadership transition): "Congrats on the [role] appointment"
- Segment 4 (capability gap): "Question on [specific capability signal]"

BODY STRUCTURE (max 120 words, exactly 4 sentences):
Sentence 1: One concrete verifiable fact from the hiring signal brief.
Sentence 2: The typical bottleneck or opportunity companies in this state hit. Frame as observation, not assertion.
Sentence 3: One specific thing Tenacious does that matches that state. No service menu.
Sentence 4: The ask — 15 or 30 minutes, a specific day, the Cal.com link.

SIGNATURE FORMAT (append after body on new line):
[Contact first name]
Research Partner, Tenacious Intelligence Corporation
gettenacious.com

TONE RULES (never violate):
- Direct. No "I hope this email finds you well" or any filler opener.
- Grounded. Every claim must reference a signal from the brief.
- No exclamation marks. No buzzwords (synergy, leverage, ecosystem, world-class).
- No "just following up", "circling back", "wanted to touch base".
- Competitor gap framing: opportunity, not deficit. Never condescending.
- No social proof dumps, no logo lists, no case-study names.

HONESTY RULES (enforced, not optional):
- If honesty_flags includes "weak_hiring_velocity_signal": do NOT say "aggressively hiring" or "scaling fast"
- If honesty_flags includes "weak_ai_maturity_signal": use asking language for AI claims, not assertions
- If honesty_flags includes "layoff_overrides_funding": lead with restructure framing, not growth framing
- If honesty_flags includes "conflicting_segment_signals": phrase leadership signal as "it looks like" not "you appointed"
- If honesty_flags includes "tech_stack_inferred_not_confirmed": qualify stack claims with "based on public signals"
- If honesty_flags includes "bench_gap_detected": do not assert capacity — route to discovery call
- Never commit to specific bench capacity numbers

OUTPUT FORMAT (JSON only):
{
  "subject": "...",
  "body": "...",
  "sequence": "cold",
  "sequence_email_number": 1,
  "variant": "signal_grounded | exploratory",
  "honesty_flags_applied": ["..."],
  "word_count": 0
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
    Auto-traces to Langfuse via drop-in client if keys are configured.
    Falls back to template if LLM is unavailable.
    """
    user_prompt = _build_prompt(brief, classification, competitor_gap, contact_name)

    if not settings.openrouter_api_key:
        log.warning("openrouter_key_missing", fallback="template")
        return _template_email(brief, classification, contact_name)

    client = _make_openai_client(settings)

    try:
        t0 = time.time()
        result = await _call_with_retry(client, settings.dev_model, SYSTEM_PROMPT, user_prompt)
        latency_ms = int((time.time() - t0) * 1000)

        log.info("email_composed",
                 variant=result.get("variant"),
                 subject=result.get("subject"),
                 model=settings.dev_model,
                 latency_ms=latency_ms)
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
async def _call_with_retry(client, model: str,
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

    return {
        "subject": "Quick question about your engineering capacity",
        "body": (
            f"Hi {name},\n\n"
            f"{headline}\n\n"
            f"{pitch}\n\n"
            f"Worth a 30-minute conversation? Happy to keep it concrete."
        ),
        "sequence": "cold",
        "sequence_email_number": 1,
        "variant": "exploratory",
        "honesty_flags_applied": flags,
        "word_count": 0,
    }
