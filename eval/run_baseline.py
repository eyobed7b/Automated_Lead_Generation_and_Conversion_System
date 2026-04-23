"""
Run τ²-Bench retail baseline.

Usage:
    python run_baseline.py --trials 5 --domain retail --slice dev
    python run_baseline.py --trials 1 --domain retail --slice held_out  # sealed partition only
"""
import argparse
import os
import sys
import structlog

sys.path.insert(0, os.path.dirname(__file__))

log = structlog.get_logger()


def main():
    parser = argparse.ArgumentParser(description="Run τ²-Bench baseline")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials (default 5)")
    parser.add_argument("--domain", type=str, default="retail", choices=["retail", "telecom"])
    parser.add_argument("--slice", type=str, default="dev",
                        choices=["dev", "held_out"],
                        help="dev = 30-task dev slice; held_out = sealed 20-task partition")
    parser.add_argument("--model", type=str, default=None,
                        help="Override model (default: from .env)")
    args = parser.parse_args()

    if args.slice == "held_out":
        print("WARNING: Running on held-out partition. Use only for final evaluation.")
        confirm = input("Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            sys.exit(0)

    # Load settings
    from dotenv import load_dotenv
    load_dotenv("../.env")

    model = args.model or os.getenv("DEV_MODEL", "deepseek/deepseek-chat-v3-0324")
    langfuse_public = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    # Init Langfuse
    langfuse_client = None
    if langfuse_public and langfuse_secret:
        try:
            from langfuse import Langfuse
            langfuse_client = Langfuse(
                public_key=langfuse_public,
                secret_key=langfuse_secret,
                host=langfuse_host,
            )
            print(f"Langfuse connected at {langfuse_host}")
        except ImportError:
            print("Langfuse not installed — traces will not be sent")

    # Run
    from tau2_harness import Tau2Harness
    harness = Tau2Harness(
        model=model,
        langfuse_client=langfuse_client,
        output_dir=os.path.dirname(__file__),
    )

    print(f"\nRunning τ²-Bench {args.domain} domain")
    print(f"Model: {model}")
    print(f"Slice: {args.slice} ({30 if args.slice == 'dev' else 20} tasks)")
    print(f"Trials: {args.trials}")
    print("-" * 50)

    stats = harness.run_retail_baseline(n_trials=args.trials, slice_type=args.slice)

    print("\n=== RESULTS ===")
    print(f"pass@1 mean:    {stats['pass_at_1_mean']:.3f}")
    print(f"95% CI:         [{stats['pass_at_1_ci_95_lower']:.3f}, {stats['pass_at_1_ci_95_upper']:.3f}]")
    print(f"Cost/run:       ${stats['cost_per_run_usd']:.4f}")
    print(f"Latency p50/p95: {stats['latency_p50_s']:.1f}s / {stats['latency_p95_s']:.1f}s")
    if stats.get("mock"):
        print("\n[MOCK] Install tau2-bench for real evaluation: pip install -r requirements.txt")
    print(f"\nOutputs written to:")
    print(f"  score_log.json")
    print(f"  trace_log.jsonl")


if __name__ == "__main__":
    main()
