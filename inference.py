from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from src.env import ACTION_ADAPTER, SREIncidentTriageEnv
from src.scenarios import evaluation_suite


DEFAULT_MODEL = "meta-llama/Llama-3.1-8B-Instruct"
DEFAULT_BASE_URL = "https://router.huggingface.co/v1"
DEFAULT_BENCHMARK = "sre_incident_triage_env"

API_BASE_URL = os.getenv("API_BASE_URL", DEFAULT_BASE_URL)
MODEL_NAME = os.getenv("MODEL_NAME", DEFAULT_MODEL)
HF_TOKEN = os.getenv("HF_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class ActionEnvelope(BaseModel):
    action: dict[str, Any]


class BaselinePolicy:
    def __init__(self) -> None:
        self.api_base_url = API_BASE_URL
        self.model_name = MODEL_NAME
        self.benchmark = os.getenv("BENCHMARK", DEFAULT_BENCHMARK)
        self.hf_token = HF_TOKEN
        self.openai_api_key = OPENAI_API_KEY
        self.api_key = self.hf_token or self.openai_api_key
        self.offline = self.api_key is None
        self.client = OpenAI(base_url=self.api_base_url, api_key=self.api_key or "offline-placeholder-key")

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        heuristic = self._heuristic_action(observation)
        if self.offline:
            return heuristic
        prompt = self._build_prompt(observation, heuristic)
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an SRE incident triage agent. Return exactly one JSON object with an `action` key. "
                            "Use runbook-cited diagnosis, execute safe mitigation, submit postmortem, then close incident."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            payload = ActionEnvelope.model_validate_json(_extract_json(content))
            return payload.action
        except Exception:
            return heuristic

    def _heuristic_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        assessment = observation["current_assessment"]
        visible_logs = observation["visible_logs"]
        visible_traces = observation["visible_traces"]
        visible_metadata = observation["visible_service_metadata"]
        available_services = observation["available_services"]
        difficulty = observation["difficulty"]

        if not observation["visible_alerts"]:
            return {"action_type": "inspect_alerts"}
        if not observation["visible_timeline"]:
            return {"action_type": "inspect_timeline"}

        root_candidate, root_category = _infer_root_from_visible_logs(visible_logs, available_services)
        if root_candidate and root_candidate not in visible_metadata:
            return {"action_type": "inspect_service_metadata", "service_name": root_candidate}

        if difficulty == "hard" and not visible_traces:
            return {"action_type": "inspect_trace", "trace_id": observation["available_trace_ids"][0]}

        if not root_candidate:
            for service in _prioritized_service_scan_order(available_services):
                if service not in visible_logs:
                    return {"action_type": "inspect_logs", "service_name": service, "limit": 6}
            if not visible_traces:
                return {"action_type": "inspect_trace", "trace_id": observation["available_trace_ids"][0]}
            root_candidate, root_category = _infer_root_from_visible_logs(visible_logs, available_services)

        if assessment["severity"] is None:
            severity = "critical" if difficulty == "hard" else "major"
            return {"action_type": "classify_severity", "severity": severity}

        if assessment["root_cause_service"] is None:
            root_service = root_candidate or available_services[0]
            category = root_category or "connection_saturation"
            runbook = _runbook_for_service(root_service, visible_metadata)
            reason = f"{root_service} is the primary failing dependency from logs and timeline evidence."
            return {
                "action_type": "identify_root_cause",
                "service_name": root_service,
                "cause_category": category,
                "reason": reason,
                "runbook_id": runbook,
            }

        if assessment["mitigation"] is None:
            root_service = assessment["root_cause_service"]
            category = assessment["root_cause_category"] or root_category or "connection_saturation"
            runbook = _runbook_for_service(root_service, visible_metadata)
            mitigation = _mitigation_text_for_category(category, root_service)
            return {"action_type": "recommend_mitigation", "action": mitigation, "runbook_id": runbook}

        if assessment["executed_mitigation_plan"] is None:
            category = assessment["root_cause_category"] or root_category or "connection_saturation"
            plan = _mitigation_plan_for_category(category)
            return {
                "action_type": "execute_mitigation",
                "plan": plan,
                "justification": f"Chosen plan {plan} minimizes blast radius and preserves error budget.",
            }

        if assessment["postmortem_timeline"] is None:
            root_service = assessment["root_cause_service"] or (root_candidate or available_services[0])
            runbook = _runbook_for_service(root_service, visible_metadata)
            return {
                "action_type": "submit_postmortem",
                "timeline_summary": (
                    f"Timeline UTC: alert fired, traced failure to {root_service}, executed mitigation, recovery verified."
                ),
                "root_cause": f"{root_service} produced the primary fault and downstream errors.",
                "corrective_action": f"Applied {_mitigation_plan_for_category(assessment['root_cause_category'] or 'connection_saturation')} and stabilized service dependencies.",
                "prevention_action": "Add rollout validation guardrail, runbook drill, and stronger alert thresholds to protect error budget.",
                "runbook_ids": [runbook],
            }

        if assessment["close_summary"] is None:
            root_service = assessment["root_cause_service"] or (root_candidate or available_services[0])
            affected = ", ".join(_affected_services_from_root(root_service, available_services))
            summary = (
                f"Resolved by confirming root cause {root_service}. "
                f"Severity {assessment['severity']}. "
                f"Mitigation executed: {assessment['executed_mitigation_plan']}. "
                f"Affected services: {affected}. "
                "Business impact and error budget implications documented in postmortem."
            )
            return {"action_type": "close_incident", "summary": summary}

        return {"action_type": "inspect_trace", "trace_id": observation["available_trace_ids"][0]}

    def _build_prompt(self, observation: dict[str, Any], heuristic: dict[str, Any]) -> str:
        return (
            "Choose the next incident response action.\n"
            "Allowed actions: inspect_alerts, inspect_timeline, inspect_logs(service_name, limit), "
            "inspect_service_metadata(service_name), inspect_trace(trace_id), classify_severity(severity), "
            "identify_root_cause(service_name, cause_category, reason, runbook_id), "
            "recommend_mitigation(action, runbook_id), execute_mitigation(plan, justification), "
            "submit_postmortem(timeline_summary, root_cause, corrective_action, prevention_action, runbook_ids), "
            "close_incident(summary).\n"
            f"Observation: {json.dumps(observation, sort_keys=True)}\n"
            f"Heuristic suggestion: {json.dumps(heuristic, sort_keys=True)}\n"
            "Return JSON only in the form {\"action\": {...}}."
        )


def _extract_json(content: str) -> str:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise ValueError("Model response did not contain JSON.")
    return content[start : end + 1]


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _format_action(action: dict[str, Any]) -> str:
    return json.dumps(action, separators=(",", ":"), sort_keys=True)


def _format_error(error: str | None) -> str:
    return "null" if error is None else error


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def _runbook_for_service(service_name: str, visible_metadata: dict[str, Any]) -> str:
    metadata = visible_metadata.get(service_name)
    if metadata and metadata.get("runbook"):
        return str(metadata["runbook"])
    return f"rb://{service_name}/incident"


def _prioritized_service_scan_order(services: list[str]) -> list[str]:
    preferred = [svc for svc in services if any(token in svc for token in ("db", "discovery", "config", "session", "auth", "inventory", "pricing", "payments"))]
    remaining = [svc for svc in services if svc not in preferred]
    return preferred + remaining


def _infer_root_from_visible_logs(
    visible_logs: dict[str, list[dict[str, Any]]],
    available_services: list[str],
) -> tuple[str | None, str | None]:
    strongest_service: str | None = None
    strongest_category: str | None = None
    strongest_score = -1
    service_aliases = {_normalize(service): service for service in available_services}

    referenced_scores: dict[str, int] = {}
    for service, entries in visible_logs.items():
        score = 0
        category = None
        for entry in entries:
            message = _normalize(str(entry.get("message", "")))
            referenced = _infer_referenced_service(message, service_aliases)
            if referenced is not None:
                referenced_scores[referenced] = referenced_scores.get(referenced, 0) + 3
            if any(token in message for token in ("pooltimeout", "pool exhausted", "max connections", "rejecting new clients", "queuepool limit")):
                score += 3
                category = "connection_saturation" if "max connections" in message else "db_pool_exhaustion"
            if any(token in message for token in ("redis pool exhausted", "cache acquisition timeout")):
                score += 3
                category = "cache_pool_exhaustion"
            if any(token in message for token in ("malformed endpoint weights", "stale endpoints", "resolver update", "config rollout")):
                score += 4
                category = "bad_config_rollout"
            if any(token in message for token in ("connection refused", "timeout", "retry storm")):
                score += 1
        if score > strongest_score:
            strongest_score = score
            strongest_service = service
            strongest_category = category
    if referenced_scores:
        explicit_root = max(referenced_scores.items(), key=lambda item: item[1])[0]
        if explicit_root in available_services:
            if "config" in explicit_root or "discovery" in explicit_root or "distributor" in explicit_root:
                return explicit_root, "bad_config_rollout"
            if "db" in explicit_root:
                return explicit_root, "connection_saturation"
            return explicit_root, strongest_category
    return strongest_service, strongest_category


def _infer_referenced_service(message: str, service_aliases: dict[str, str]) -> str | None:
    trigger_tokens = (
        "connecting to",
        "target changed",
        "from",
        "resolver returned",
        "waiting on",
        "dependency",
    )
    if not any(token in message for token in trigger_tokens):
        return None
    for alias, service in service_aliases.items():
        if alias in message:
            return service
    return None


def _mitigation_plan_for_category(category: str) -> str:
    category_norm = _normalize(category)
    if "config" in category_norm or "rollout" in category_norm:
        return "rollback_config"
    if "pool" in category_norm or "connection" in category_norm or "cache" in category_norm:
        return "scale_capacity"
    return "scale_capacity"


def _mitigation_text_for_category(category: str, root_service: str) -> str:
    plan = _mitigation_plan_for_category(category)
    if plan == "rollback_config":
        return f"rollback {root_service} config rollout and flush stale endpoint caches"
    return f"scale capacity for {root_service} connection pools and throttle retry pressure"


def _affected_services_from_root(root_service: str, available_services: list[str]) -> list[str]:
    if root_service in {"auth-service", "session-service"}:
        return [root_service, "edge-gateway"]
    if root_service in {"inventory-db", "pricing-db"}:
        svc = "inventory-service" if root_service == "inventory-db" else "pricing-service"
        return [root_service, svc, "checkout-service", "frontend-api"]
    if root_service in {"service-discovery", "config-distributor"}:
        return [root_service, "payments-api", "checkout-service", "edge-gateway"]
    return available_services[:2] if len(available_services) >= 2 else available_services


def main() -> None:
    policy = BaselinePolicy()
    for task_name, difficulty, split, seed in evaluation_suite():
        print(f"[START] task={task_name} env={policy.benchmark} model={policy.model_name}")
        env = SREIncidentTriageEnv(difficulty=difficulty, seed=seed, split=split)
        done = True
        success = False
        score = 0.0
        rewards: list[float] = []
        steps = 0
        error: str | None = None
        result = None
        try:
            result = env.reset(difficulty=difficulty, seed=seed, split=split)
            done = bool(result.done)
            while not done:
                observation = result.observation.model_dump(mode="json")
                action_dict = policy.choose_action(observation)
                ACTION_ADAPTER.validate_python(action_dict)
                result = env.step(action_dict)
                steps = result.observation.step_count
                done = result.done
                rewards.append(result.reward)
                error = result.info.get("last_action_error")
                print(
                    "[STEP] "
                    f"step={steps} "
                    f"action={_format_action(action_dict)} "
                    f"reward={result.reward:.2f} "
                    f"done={_format_bool(done)} "
                    f"error={_format_error(error)}"
                )
            if result is not None:
                score = float(result.info.get("score", 0.0))
            success = True
        except Exception as exc:
            error = str(exc)
            success = False
        finally:
            rewards_str = ",".join(f"{reward:.2f}" for reward in rewards)
            print(
                "[END] "
                f"success={_format_bool(success)} "
                f"steps={steps} "
                f"score={score:.2f} "
                f"rewards={rewards_str if rewards_str else '0.00'}"
            )


if __name__ == "__main__":
    main()
