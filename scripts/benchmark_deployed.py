from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference import BaselinePolicy
from src.scenarios import evaluation_suite


@dataclass
class EpisodeResult:
    task: str
    difficulty: str
    split: str
    seed: int
    steps: int
    score: float
    reward_sum: float


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return float(statistics.quantiles(values, n=100, method="inclusive")[94])


def run_benchmark(base_url: str, timeout_s: int) -> dict[str, Any]:
    policy = BaselinePolicy()
    policy.offline = True

    reset_latencies_ms: list[float] = []
    step_latencies_ms: list[float] = []
    state_latencies_ms: list[float] = []
    episodes: list[EpisodeResult] = []

    for task_name, difficulty, split, seed in evaluation_suite():
        start = time.perf_counter()
        reset_resp = requests.post(
            f"{base_url}/reset",
            params={"difficulty": difficulty, "seed": seed, "split": split},
            timeout=timeout_s,
        )
        reset_latencies_ms.append((time.perf_counter() - start) * 1000)
        reset_resp.raise_for_status()
        result = reset_resp.json()

        done = bool(result["done"])
        steps = 0
        reward_sum = 0.0
        score = 0.0

        while not done:
            action = policy.choose_action(result["observation"])
            step_start = time.perf_counter()
            step_resp = requests.post(f"{base_url}/step", json=action, timeout=timeout_s)
            step_latencies_ms.append((time.perf_counter() - step_start) * 1000)
            step_resp.raise_for_status()
            result = step_resp.json()
            done = bool(result["done"])
            steps = int(result["observation"]["step_count"])
            reward_sum += float(result["reward"])
            if done:
                score = float(result.get("info", {}).get("score", 0.0))

        state_start = time.perf_counter()
        state_resp = requests.get(f"{base_url}/state", timeout=timeout_s)
        state_latencies_ms.append((time.perf_counter() - state_start) * 1000)
        state_resp.raise_for_status()

        episodes.append(
            EpisodeResult(
                task=task_name,
                difficulty=difficulty,
                split=split,
                seed=seed,
                steps=steps,
                score=score,
                reward_sum=round(reward_sum, 2),
            )
        )

    scores = [ep.score for ep in episodes]
    steps = [ep.steps for ep in episodes]

    return {
        "base_url": base_url,
        "episodes": [asdict(ep) for ep in episodes],
        "summary": {
            "episode_count": len(episodes),
            "mean_score": round(statistics.mean(scores), 4),
            "min_score": round(min(scores), 4),
            "max_score": round(max(scores), 4),
            "mean_steps": round(statistics.mean(steps), 2),
            "reset_ms_p50": round(statistics.median(reset_latencies_ms), 2),
            "reset_ms_p95": round(_p95(reset_latencies_ms), 2),
            "step_ms_p50": round(statistics.median(step_latencies_ms), 2),
            "step_ms_p95": round(_p95(step_latencies_ms), 2),
            "state_ms_p50": round(statistics.median(state_latencies_ms), 2),
            "state_ms_p95": round(_p95(state_latencies_ms), 2),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark deployed SRE Incident Triage Env API.")
    parser.add_argument(
        "--base-url",
        default="https://hakashikatake-sre-incident-triage-env.hf.space",
        help="Base URL of deployed API.",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to write JSON benchmark report.",
    )
    args = parser.parse_args()

    report = run_benchmark(args.base_url.rstrip("/"), timeout_s=args.timeout)
    print(json.dumps(report, indent=2))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
