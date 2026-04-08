from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference import BaselinePolicy
from src.env import ACTION_ADAPTER
from src.scenarios import evaluation_suite


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _format_error(error: str | None) -> str:
    return "null" if error is None else error


def _format_action(action: dict[str, Any]) -> str:
    return json.dumps(action, separators=(",", ":"), sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run baseline policy against deployed SRE Incident Triage API.")
    parser.add_argument(
        "--base-url",
        default="https://hakashikatake-sre-incident-triage-env.hf.space",
        help="Deployed Space API base URL.",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    policy = BaselinePolicy()
    benchmark_name = "sre_incident_triage_env_deployed"

    for task_name, difficulty, split, seed in evaluation_suite():
        print(f"[START] task={task_name} env={benchmark_name} model={policy.model_name}")
        done = True
        rewards: list[float] = []
        steps = 0
        score = 0.0
        success = False
        error: str | None = None
        result: dict[str, Any] | None = None
        try:
            reset_resp = requests.post(
                f"{base_url}/reset",
                params={"difficulty": difficulty, "split": split, "seed": seed},
                timeout=args.timeout,
            )
            reset_resp.raise_for_status()
            result = reset_resp.json()
            done = bool(result["done"])
            while not done:
                assert result is not None
                action = policy.choose_action(result["observation"])
                ACTION_ADAPTER.validate_python(action)
                step_resp = requests.post(f"{base_url}/step", json=action, timeout=args.timeout)
                step_resp.raise_for_status()
                result = step_resp.json()
                done = bool(result["done"])
                steps = int(result["observation"]["step_count"])
                reward = float(result["reward"])
                rewards.append(reward)
                error = result.get("info", {}).get("last_action_error")
                print(
                    "[STEP] "
                    f"step={steps} "
                    f"action={_format_action(action)} "
                    f"reward={reward:.2f} "
                    f"done={_format_bool(done)} "
                    f"error={_format_error(error)}"
                )
            if result is not None:
                score = float(result.get("info", {}).get("score", 0.0))
            success = True
        except Exception as exc:
            error = str(exc)
            success = False
        rewards_str = ",".join(f"{r:.2f}" for r in rewards) if rewards else "0.00"
        print(
            "[END] "
            f"success={_format_bool(success)} "
            f"steps={steps} "
            f"score={score:.2f} "
            f"rewards={rewards_str}"
        )


if __name__ == "__main__":
    main()
