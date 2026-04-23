# The Conversion Engine
**Automated Lead Generation and Conversion System for Tenacious Consulting and Outsourcing**

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Conversion Engine                             │
│                                                                       │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐  │
│  │  Enrichment  │───▶│  ICP Classifier  │───▶│ Outreach Composer │  │
│  │   Pipeline   │    │  (4 segments +   │    │  (LLM + signal    │  │
│  │              │    │   confidence)    │    │     brief)        │  │
│  └──────────────┘    └──────────────────┘    └────────┬──────────┘  │
│       │                                               │              │
│  Crunchbase ODM                                       ▼              │
│  layoffs.fyi                               ┌──────────────────┐     │
│  Job post scraper                          │  Channel Router  │     │
│  Leadership changes                        │  Email (primary) │     │
│  AI maturity scorer                        │  SMS (secondary) │     │
│  Competitor gap brief                      │  Voice (bonus)   │     │
│                                            └────────┬─────────┘     │
│                                                     │               │
│              ┌──────────────────────────────────────┘               │
│              ▼                  ▼                  ▼                 │
│  ┌───────────────────┐  ┌─────────────┐  ┌──────────────────┐      │
│  │   HubSpot CRM     │  │  Cal.com    │  │    Langfuse      │      │
│  │  (all events)     │  │  (booking)  │  │ (observability)  │      │
│  └───────────────────┘  └─────────────┘  └──────────────────┘      │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    τ²-Bench Eval Harness                      │   │
│  │         score_log.json  ·  trace_log.jsonl                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Stack

| Layer | Tool |
|---|---|
| Backend | FastAPI (Python 3.11+) |
| Email (primary) | Resend (free tier) |
| SMS (secondary) | Africa's Talking sandbox |
| CRM | HubSpot Developer Sandbox |
| Calendar | Cal.com (self-hosted via Docker) |
| Observability | Langfuse cloud free tier |
| LLM (dev) | OpenRouter — Qwen3 / DeepSeek V3 |
| LLM (eval) | Claude Sonnet 4.6 |
| Enrichment | Playwright + Crunchbase ODM + layoffs.fyi |
| Evaluation | τ²-Bench retail domain |

## Channel Priority

> Email → SMS → Voice (match channel to segment)

- **Email** is primary for Tenacious prospects (founders, CTOs, VPs Engineering)
- **SMS** is secondary, only for warm leads who have replied and prefer fast scheduling coordination
- **Voice** is the final channel — a discovery call delivered by a human Tenacious delivery lead

## Setup Instructions

### Prerequisites
- Python 3.11+
- Docker + Docker Compose
- Node.js 18+ (for Playwright)

### 1. Clone and install

```bash
git clone <repo-url>
cd Automated_Lead_Generation_and_Conversion_System

# Agent dependencies
cd agent && pip install -r requirements.txt
playwright install chromium

# Eval dependencies
cd ../eval && pip install -r requirements.txt
```

### 2. Environment variables

```bash
cp .env.example .env
# Fill in all values — see .env.example for descriptions
```

### 3. Start Cal.com locally

```bash
docker-compose up -d calcom
```

### 4. Run the agent server

```bash
cd agent
uvicorn main:app --reload --port 8000
```

### 5. Kill-switch

**IMPORTANT:** All outbound defaults to the staff sink (sandbox mode).  
To enable live outbound, set `LIVE_OUTBOUND=true` in `.env`.  
Default is `LIVE_OUTBOUND=false` — all messages route to `STAFF_SINK_EMAIL` / `STAFF_SINK_PHONE`.

### 6. Run τ²-Bench baseline

```bash
cd eval
python run_baseline.py --trials 5 --domain retail --slice dev
```

## Project Structure

```
agent/
├── main.py                  # FastAPI app + webhook routes
├── config.py                # Settings loaded from .env
├── requirements.txt
├── enrichment/
│   ├── crunchbase.py        # Crunchbase ODM firmographic lookup
│   ├── layoffs.py           # layoffs.fyi parsing
│   ├── job_posts.py         # Playwright job-post scraper
│   ├── leadership.py        # Leadership change detection
│   ├── ai_maturity.py       # AI maturity scoring (0–3)
│   ├── competitor_gap.py    # Competitor gap brief generator
│   └── pipeline.py          # Orchestrates all enrichment steps
├── channels/
│   ├── email_handler.py     # Resend integration
│   ├── sms_handler.py       # Africa's Talking integration
│   └── calendar_handler.py  # Cal.com booking
├── crm/
│   └── hubspot.py           # HubSpot MCP / REST integration
├── qualification/
│   ├── icp_classifier.py    # ICP segment classifier + confidence
│   └── signal_brief.py      # Hiring signal brief builder
├── outreach/
│   ├── composer.py          # LLM email composer
│   └── nurture.py           # Nurture sequence state machine
└── webhooks/
    ├── email_reply.py       # Inbound email reply handler
    └── sms_reply.py         # Inbound SMS reply handler

eval/
├── tau2_harness.py          # τ²-Bench wrapper
├── run_baseline.py          # Baseline runner
├── score_log.json           # Pass@1 scores + CIs
└── trace_log.jsonl          # Full τ²-Bench trajectories

seed/
├── icp_definition.md        # ICP segment definitions
├── style_guide.md           # Tenacious tone markers
├── bench_summary.json       # Available engineers by stack
├── pricing.md               # Public-tier pricing bands
└── data/
    ├── crunchbase_sample.json
    └── layoffs_sample.csv

probes/                      # Act III (final submission)
├── probe_library.md
├── failure_taxonomy.md
└── target_failure_mode.md
```

## Data Handling

- All prospects during the challenge week are **synthetic** — derived from public Crunchbase firmographics with fictitious contact details
- No real Tenacious customer data is used
- All outbound routes to a staff-controlled sink by default (`LIVE_OUTBOUND=false`)
- Seed materials (deck, case studies, pricing) are under limited license — not redistributed

## Baseline Numbers (from challenge brief)

| Metric | Value | Source |
|---|---|---|
| Cold email reply rate | 1–3% | LeadIQ 2026 / Apollo |
| Signal-grounded reply rate | 7–12% | Clay, Smartlead case studies |
| Discovery-to-proposal | 35–50% | Tenacious internal |
| Proposal-to-close | 25–40% | Tenacious internal |
| ACV (talent outsourcing) | $240–720K | Tenacious internal |
| ACV (project consulting) | $80–300K | Tenacious internal |
| τ²-Bench pass@1 ceiling | ~42% | τ²-Bench Feb 2026 |
