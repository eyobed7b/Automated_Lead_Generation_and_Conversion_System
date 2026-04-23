import os
from pydantic_settings import BaseSettings
from functools import lru_cache

_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


class Settings(BaseSettings):
    # Kill-switch: when False, all outbound routes to staff sink
    live_outbound: bool = False
    staff_sink_email: str = "sandbox@tenacious-staff.internal"
    staff_sink_phone: str = "+12025550100"

    # Email — Resend
    resend_api_key: str = ""
    resend_from_email: str = "outreach@tenacious.co"
    resend_reply_webhook_secret: str = ""

    # SMS — Africa's Talking
    africastalking_username: str = "sandbox"
    africastalking_api_key: str = ""
    africastalking_sender_id: str = "TENACIOUS"

    # CRM — HubSpot
    hubspot_access_token: str = ""
    hubspot_portal_id: str = ""

    # Calendar — Cal.com cloud
    calcom_api_key: str = ""
    calcom_username: str = ""
    calcom_base_url: str = "https://api.cal.com"
    calcom_event_type_id: int = 1

    # LLM — OpenRouter (used for all agent calls)
    # Common models (set DEV_MODEL in .env):
    #   deepseek/deepseek-chat-v3-0324   — fast, cheap, good JSON
    #   qwen/qwen3-235b-a22b             — stronger reasoning
    #   anthropic/claude-sonnet-4-6      — eval tier (more expensive)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    dev_model: str = "deepseek/deepseek-chat-v3-0324"
    eval_model: str = "anthropic/claude-sonnet-4-6"

    # Observability — Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Data paths (absolute, resolved from this file's location)
    crunchbase_data_path: str = os.path.join(os.path.dirname(__file__), "..", "seed", "data", "crunchbase_sample.json")
    layoffs_data_path: str = os.path.join(os.path.dirname(__file__), "..", "seed", "data", "layoffs_sample.csv")
    bench_summary_path: str = os.path.join(os.path.dirname(__file__), "..", "seed", "bench_summary.json")
    icp_definition_path: str = os.path.join(os.path.dirname(__file__), "..", "seed", "icp_definition.md")
    style_guide_path: str = os.path.join(os.path.dirname(__file__), "..", "seed", "style_guide.md")

    # Agent behavior
    max_outbound_per_day: int = 60
    min_icp_confidence: float = 0.60
    signal_grounded_threshold: float = 0.75
    job_post_velocity_min_roles: int = 5

    class Config:
        env_file = _ENV_FILE
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
