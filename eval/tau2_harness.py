"""
τ²-Bench harness wrapper.
Runs the retail domain against a pinned model and logs traces to Langfuse.
"""
import json
import os
import time
import uuid
from typing import Optional
import structlog

log = structlog.get_logger()

DEV_SLICE_SIZE = 30
HELD_OUT_SLICE_SIZE = 20


class Tau2Harness:
    def __init__(self, model: str, langfuse_client=None, output_dir: str = "."):
        self.model = model
        self.langfuse = langfuse_client
        self.output_dir = output_dir
        self.score_log_path = os.path.join(output_dir, "score_log.json")
        self.trace_log_path = os.path.join(output_dir, "trace_log.jsonl")

    def run_retail_baseline(self, n_trials: int = 5, slice_type: str = "dev") -> dict:
        """
        Run τ²-Bench retail domain baseline.
        Returns pass@1, 95% CI, cost, and latency stats.
        """
        log.info("tau2_run_start", model=self.model, trials=n_trials, slice=slice_type)

        try:
            from tau2bench.envs import make_env
            from tau2bench.run import run_task
            tasks = self._load_tasks(slice_type)
        except ImportError:
            log.warning("tau2bench_not_installed", note="Using mock evaluation")
            return self._mock_run(n_trials, slice_type)

        results = []
        traces = []
        total_cost = 0.0
        latencies = []

        for trial in range(n_trials):
            trial_results = []
            for task in tasks:
                start = time.monotonic()
                trace_id = str(uuid.uuid4())

                try:
                    env = make_env("retail", task_id=task["id"])
                    result = run_task(env, model=self.model)
                    passed = result.get("success", False)
                    cost = result.get("cost_usd", 0.0)
                    latency = time.monotonic() - start

                    trace = {
                        "trace_id": trace_id,
                        "task_id": task["id"],
                        "trial": trial,
                        "model": self.model,
                        "passed": passed,
                        "cost_usd": cost,
                        "latency_s": round(latency, 3),
                        "domain": "retail",
                        "slice": slice_type,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                    traces.append(trace)
                    trial_results.append(passed)
                    total_cost += cost
                    latencies.append(latency)

                    if self.langfuse:
                        self._log_to_langfuse(trace, result)

                except Exception as e:
                    log.error("task_failed", task_id=task.get("id"), error=str(e))
                    traces.append({
                        "trace_id": trace_id,
                        "task_id": task.get("id"),
                        "trial": trial,
                        "error": str(e),
                        "passed": False,
                    })
                    trial_results.append(False)

            trial_pass_rate = sum(trial_results) / len(trial_results) if trial_results else 0
            results.append(trial_pass_rate)
            log.info("trial_complete", trial=trial, pass_rate=trial_pass_rate)

        stats = self._compute_stats(results, latencies, total_cost, n_trials)
        self._write_outputs(stats, traces)

        log.info("tau2_run_complete", **{k: v for k, v in stats.items() if k != "raw_trial_results"})
        return stats

    def _mock_run(self, n_trials: int, slice_type: str) -> dict:
        """Mock run for when tau2-bench is not yet installed."""
        log.info("tau2_mock_run", note="Install tau2-bench for real evaluation")
        import random
        random.seed(42)

        results = []
        traces = []
        latencies = []
        total_cost = 0.0

        task_count = DEV_SLICE_SIZE if slice_type == "dev" else HELD_OUT_SLICE_SIZE

        for trial in range(n_trials):
            trial_results = []
            for task_idx in range(task_count):
                latency = random.uniform(1.5, 8.0)
                passed = random.random() < 0.38
                cost = random.uniform(0.002, 0.015)
                trace_id = str(uuid.uuid4())

                trace = {
                    "trace_id": trace_id,
                    "task_id": f"retail_{slice_type}_{task_idx:03d}",
                    "trial": trial,
                    "model": self.model,
                    "passed": passed,
                    "cost_usd": cost,
                    "latency_s": round(latency, 3),
                    "domain": "retail",
                    "slice": slice_type,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mock": True,
                }
                traces.append(trace)
                trial_results.append(passed)
                total_cost += cost
                latencies.append(latency)

            results.append(sum(trial_results) / len(trial_results))

        stats = self._compute_stats(results, latencies, total_cost, n_trials)
        stats["mock"] = True
        self._write_outputs(stats, traces)
        return stats

    def _compute_stats(self, results: list[float], latencies: list[float],
                       total_cost: float, n_trials: int) -> dict:
        import numpy as np
        from scipy import stats as scipy_stats

        arr = np.array(results)
        mean = float(arr.mean())
        sem = float(scipy_stats.sem(arr)) if len(arr) > 1 else 0.0
        ci_95 = float(scipy_stats.t.ppf(0.975, df=max(len(arr)-1, 1)) * sem)

        lat_arr = sorted(latencies)
        p50 = float(np.percentile(lat_arr, 50)) if lat_arr else 0
        p95 = float(np.percentile(lat_arr, 95)) if lat_arr else 0

        return {
            "model": self.model,
            "n_trials": n_trials,
            "pass_at_1_mean": round(mean, 4),
            "pass_at_1_ci_95_lower": round(mean - ci_95, 4),
            "pass_at_1_ci_95_upper": round(mean + ci_95, 4),
            "cost_per_run_usd": round(total_cost / n_trials, 4),
            "total_cost_usd": round(total_cost, 4),
            "latency_p50_s": round(p50, 2),
            "latency_p95_s": round(p95, 2),
            "raw_trial_results": results,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _write_outputs(self, stats: dict, traces: list[dict]) -> None:
        # score_log.json
        existing = []
        if os.path.exists(self.score_log_path):
            with open(self.score_log_path) as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    existing = []

        existing.append({k: v for k, v in stats.items() if k != "raw_trial_results"})
        with open(self.score_log_path, "w") as f:
            json.dump(existing, f, indent=2)

        # trace_log.jsonl
        with open(self.trace_log_path, "a") as f:
            for trace in traces:
                f.write(json.dumps(trace) + "\n")

        log.info("outputs_written",
                 score_log=self.score_log_path,
                 traces=len(traces))

    def _load_tasks(self, slice_type: str) -> list[dict]:
        size = DEV_SLICE_SIZE if slice_type == "dev" else HELD_OUT_SLICE_SIZE
        return [{"id": f"retail_{slice_type}_{i:03d}"} for i in range(size)]

    def _log_to_langfuse(self, trace: dict, result: dict) -> None:
        try:
            self.langfuse.trace(
                id=trace["trace_id"],
                name=f"tau2_retail_{trace['task_id']}",
                metadata={
                    "model": trace["model"],
                    "domain": trace["domain"],
                    "trial": trace["trial"],
                    "passed": trace["passed"],
                    "cost_usd": trace["cost_usd"],
                },
            )
        except Exception as e:
            log.warning("langfuse_log_failed", error=str(e))
