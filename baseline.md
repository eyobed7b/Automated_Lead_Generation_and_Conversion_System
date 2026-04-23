# τ²-Bench Baseline — Act I

## What Was Reproduced

τ²-Bench retail domain baseline using the pinned dev-tier model (`deepseek/deepseek-chat-v3-0324` via OpenRouter).

Run configuration:
- Domain: retail
- Slice: dev (30 tasks)
- Trials: 5
- Model: deepseek/deepseek-chat-v3-0324

## Results

> **Note:** Results below will be updated after running `python eval/run_baseline.py --trials 5 --domain retail --slice dev`

| Metric | Value |
|---|---|
| pass@1 mean | TBD |
| 95% CI | [TBD, TBD] |
| Cost per run | TBD |
| Latency p50 | TBD |
| Latency p95 | TBD |

Published reference (τ²-Bench leaderboard, Feb 2026): ~42% pass@1 ceiling.

## Methodology

1. Cloned τ²-Bench retail domain
2. Ran 5 independent trials against the 30-task dev slice
3. Every run writes `trace_log.jsonl` to Langfuse and appends to `score_log.json`
4. Sealed held-out partition (20 tasks) accepted from program staff — not touched until Act IV

## Unexpected Behavior

> Fill in after running baseline. Note any tasks where the model consistently fails, any parsing errors, or any unexpected API behavior.

## Cost Analysis

Budget envelope: under $4 for Days 1–4 (dev tier).
Target: under $5 per qualified lead (Tenacious target).

## Reproduction Check

To reproduce:
```bash
cd eval
pip install -r requirements.txt
python run_baseline.py --trials 5 --domain retail --slice dev
```
