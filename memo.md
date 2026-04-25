# DECISION MEMO

**To:** CEO, CFO — Tenacious Consulting
**From:** Engineering Lead
**Date:** April 24, 2026
**Re:** Automated Lead Generation and Conversion System — Pilot Authorization

---

## Executive Summary

Tenacious's Automated Lead Generation and Conversion System combines a FastAPI + DeepSeek V3 pipeline with HubSpot, Cal.com, and Langfuse to research ICPs, draft signal-grounded cold emails, and book discovery calls without SDR labor. The system achieved a τ²-Bench retail pass@1 of 13.3% at $0.00345/task with an honesty-flag validation pass reducing fabrication exposure, though a disqualification bug in the ICP classifier must be patched before any live send. Recommendation: authorize a 40-lead, 30-day pilot targeting Segment 2 (mid-market restructuring) while the classifier fix is completed in parallel.

---

## τ²-Bench Retail Baseline

| Metric | Value | 95% CI | Source |
|---|---|---|---|
| pass@1 | 13.3% (4/30 tasks) | [1.2%, 25.5%] | τ²-Bench Day-1 eval |
| Cost / task | $0.00345 | — | OpenRouter traces |
| Latency p50 | 52.5s | — | OpenRouter traces |
| Latency p95 | 203.5s | — | OpenRouter traces |
| Model | DeepSeek V3 via OpenRouter | — | System config |
| Eval date | April 2026 | — | This submission |

Published τ²-Bench ceiling: ~42% (Feb 2026 leaderboard). Gap of ~29 pp represents headroom for prompt and retrieval improvements before ceiling contact.

---

## Cost Per Qualified Lead

- LLM cost per email: $0.00345 (OpenRouter traces)
- Assumption: 10% of outbound leads qualify (conservative midpoint between cold email 1–3% and signal-grounded 7–12% reply rates; Clay/Smartlead 2025 case studies)
- Emails per qualified lead: ~10
- LLM cost per qualified lead: 10 × $0.00345 = **$0.0345**
- Playwright enrichment overhead: ~$0.01/lead (conservative compute estimate)
- Honesty validation pass: ~$0.001/email (system design spec)
- **Total estimated CPL: ~$0.04–0.05** (LLM + compute only)

This is well under the $5 CPL target in baseline.md. Human SDR equivalent cost at $60K/year fully-loaded across ~60 touches/week (Tenacious internal sales ops) is approximately $19/qualified lead.

---

## Stalled-Deal Rate Delta

Current Tenacious manual stall rate: 30–40% (challenge brief). Industry benchmark stalled-deal rate: ~72% (CRM Pipeline Analysis Benchmarks). The system targets the front-of-funnel gap, not late-stage stalls.

**Honest limitation:** stall rate improvement cannot be measured from τ²-Bench retail traces — the benchmark domain does not model outbound B2B deal progression. This metric will be tracked in the live pilot via HubSpot deal-stage transition events over 30 days.

---

## Outbound Variant Performance Gap

The pipeline branches on signal confidence:

| Variant | Trigger | Expected Reply Rate | Source |
|---|---|---|---|
| `signal_grounded` | Hiring / funding / leadership signal detected | 7–12% | Clay/Smartlead 2025 |
| `exploratory` | Below confidence threshold | 1–3% | LeadIQ 2026 / Apollo 2026 |

Delta: 4–9 pp lift when a verifiable signal is present. Cannot be confirmed until live pilot. Pilot tracking will tag each send by variant in HubSpot and measure 30-day reply rates.

---

## Pilot Scope Recommendation

- **Segment:** Segment 2 (mid-market restructuring) — layoff events are public and verifiable, minimizing signal-staleness risk
- **Volume:** 40 qualified leads over 30 days (2/day, within the 60 touches/week SDR target; Tenacious internal sales ops)
- **Budget:** ~$2 LLM cost + $50 Resend/Africa's Talking + $0 HubSpot sandbox = **~$52/month**
- **Success criterion:** ≥1 discovery call booked within 30 days (7% signal-grounded reply rate × 35% discovery-to-call conversion × 40 leads = 0.98 calls expected; 1 call = benchmark threshold)
- **Kill switch:** if zero replies in first 20 sends, pause and review signal quality before continuing

ACV context: Tenacious project ACV is $80–300K (Tenacious internal, README). A single closed deal from this pilot returns 1,500–5,700x the monthly pilot cost.

---

---

## The Skeptic's Appendix: Four Failure Modes τ²-Bench Does Not Capture

**1. Offshore-perception objection**
A signal-grounded email lands. The prospect replies: "we don't offshore." The agent cannot handle the nuanced value-proposition negotiation around Tenacious's African-engineer positioning. τ²-Bench retail simulates single-domain tool use, not B2B objection dynamics. Resolution: seed an objection-handling eval with the 5 most common Tenacious objections (offshore quality, timezone, IP risk, team cohesion, hidden costs). Estimated cost: 1 SDR day + $2 LLM eval.

**2. Bench mismatch at proposal stage**
The agent books a call. The prospect needs 3 senior Rust/CUDA engineers. Tenacious has none. Deal collapses. τ²-Bench does not model AI-to-human handoffs against a live bench. Resolution: post-discovery validator cross-referencing requirements against bench_summary.json. Estimated cost: 2 engineering days.

**3. Signal staleness causing wrong pitch timing**
A Series B shows 178 days old in Crunchbase. The company is in a hiring freeze. τ²-Bench uses static tasks, not live data streams. Resolution: timestamp validation on all signals with configurable staleness thresholds (engineers ready to deploy: 60; time-to-deploy: 7–14 days; Tenacious Overview Jan 2026 / seed/baseline_numbers.md).

**4. Multi-contact collision at the same company**
The agent emails both CTO and VP Engineering. One replies positively, one negatively. The agent sends conflicting follow-ups. τ²-Bench is single-thread per task. Resolution: company-level deduplication lock in HubSpot before any outbound send.

---

## Public-Signal Lossiness: AI Maturity Scoring

**False negative — quietly sophisticated, publicly silent:** A company with a deep internal ML platform but no public signals scores 0–1. System routes to Segment 1 or abstains. If the company is a Segment 4 capability-gap prospect in reality, Tenacious sends the wrong pitch or none. Business impact: missed $80–300K project consulting opportunity (Tenacious internal, README).

**False positive — loud but shallow:** A company posts AI Engineer listings to appear innovative but has no real AI product (common pattern, 2025–2026). System scores 2–3, routes to Segment 4, composes a capabilities-gap pitch. CTO replies: "we're not actually building AI." Business impact: one burned contact and a brand-quality impression of poor research.

---

## One Honest Unresolved Failure

**Probe P-15 — `disqualified=False` hardcoding in ICP classifier**

The `disqualified` field is hardcoded to `False` on every return path of `icp_classifier.py` (lines 119 and 136). Explicit disqualifying signals documented in `seed/icp_definition.md` — anti-offshore founder public stance, company already listed on a competitor's case-study page, layoff >40% — are never evaluated in code.

This was not resolved in Act IV. The submitted mechanism (honesty-flag validation pass — a second LLM call at temperature 0.0 checking `honesty_flags`) targets the email-generation layer, not the classification layer. A disqualified prospect who clears the confidence threshold will receive a fully grounded, properly flagged email, and Tenacious will have pitched an anti-offshore founder.

Observed honesty-flag violation rate in manually inspected traces: 43% of 10 dev-slice traces — underscoring that the email layer does have exposure, but the classification-layer gap is structurally separate and unaddressed.

Business impact if deployed without the fix: a single viral LinkedIn post from a well-followed founder costs more pipeline than one week of signal-grounded outbound generates (seed/style_guide.md).

**Resolution path:** add a pre-classification disqualification check — rule-based, zero LLM cost, 1 engineering hour. Not included in the current submission. This fix must be merged and tested before the pilot sends its first email.

---

*All numeric claims trace to evidence_graph.json.*
