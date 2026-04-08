from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.models import IncidentState, MitigationPlan
from src.scenarios import IncidentScenario


def _strict_open_interval_score(value: float) -> float:
    return round(min(0.99, max(0.01, float(value))), 4)


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").replace("_", " ").split())


def _token_set(value: str) -> set[str]:
    return {token for token in _normalize(value).split() if token}


def mitigation_match_score(submitted: str | None, expected_keywords: Iterable[str]) -> float:
    if not submitted:
        return 0.0
    submitted_tokens = _token_set(submitted)
    target_tokens = {_normalize(token) for token in expected_keywords}
    if not target_tokens:
        return 0.0
    exact_hits = sum(1 for token in target_tokens if token in submitted_tokens)
    return round(exact_hits / len(target_tokens), 4)


def _efficiency_score(step_count: int, step_limit: int) -> float:
    if step_count <= 0:
        return 0.0
    used_ratio = step_count / step_limit
    return round(max(0.0, 1.0 - max(0.0, used_ratio - 0.4) * 1.35), 4)


def _execution_plan_score(plan: MitigationPlan | None, scenario: IncidentScenario) -> float:
    if plan is None:
        return 0.0
    truth = scenario.hidden_truth
    if plan == truth.preferred_mitigation_plan:
        return 1.0
    if plan in truth.risky_mitigation_plans:
        return 0.0
    return 0.55


def _postmortem_score(scenario: IncidentScenario, state: IncidentState) -> float:
    assessment = state.current_observation.current_assessment
    truth = scenario.hidden_truth
    timeline = _normalize(assessment.postmortem_timeline or "")
    root_cause = _normalize(assessment.postmortem_root_cause or "")
    corrective = _normalize(assessment.postmortem_corrective_action or "")
    prevention = _normalize(assessment.postmortem_prevention_action or "")
    runbooks = {_normalize(item) for item in assessment.postmortem_runbooks}
    required_runbooks = {_normalize(item) for item in truth.required_runbooks}

    timeline_score = 0.0
    timeline_markers = sum(1 for service in truth.affected_services if _normalize(service) in timeline)
    if "utc" in timeline or "timeline" in timeline:
        timeline_score += 0.4
    timeline_score += min(0.6, timeline_markers * 0.2)

    root_score = 1.0 if _normalize(truth.root_cause_service) in root_cause else 0.0
    corrective_score = 1.0 if _normalize(truth.preferred_mitigation_plan).split()[0] in corrective else 0.4 if corrective else 0.0
    prevention_score = 1.0 if any(token in prevention for token in ("guardrail", "canary", "alert", "capacity", "validation")) else 0.0

    runbook_score = 0.0
    if required_runbooks:
        runbook_score = min(1.0, len(runbooks.intersection(required_runbooks)) / len(required_runbooks))

    combined = (timeline_score + root_score + corrective_score + prevention_score + runbook_score) / 5
    return round(min(1.0, combined), 4)


def _business_impact_score(scenario: IncidentScenario, state: IncidentState) -> float:
    assessment = state.current_observation.current_assessment
    truth = scenario.hidden_truth
    if assessment.severity is None:
        return 0.0
    score = 0.0
    if assessment.severity == truth.severity:
        score += 0.6
    notes = _normalize((assessment.close_summary or "") + " " + (assessment.postmortem_timeline or ""))
    if any(token in notes for token in ("users", "revenue", "error budget", "impact", "customer")):
        score += 0.4
    return round(min(1.0, score), 4)


def _counterfactual_messages(weighted: dict[str, float], scenario: IncidentScenario) -> list[str]:
    messages: list[str] = []
    if weighted["root_cause_service"] < 1.0:
        messages.append("Identify the primary root-cause service instead of a downstream symptom.")
    if weighted["root_cause_category"] < 1.0:
        messages.append("Use the exact root-cause category from evidence patterns.")
    if weighted["runbook_diagnosis"] < 1.0:
        messages.append("Cite the correct diagnosis runbook when declaring root cause.")
    if weighted["mitigation"] < 0.95:
        messages.append("Mitigation text is incomplete; include all expected remediation keywords.")
    if weighted["runbook_mitigation"] < 1.0:
        messages.append("Link mitigation to the correct runbook for safer operator handoff.")
    if weighted["mitigation_execution"] < 1.0:
        messages.append(f"Execute `{scenario.hidden_truth.preferred_mitigation_plan}` to avoid blast-radius risk.")
    if weighted["postmortem_quality"] < 0.9:
        messages.append("Submit a fuller postmortem with timeline, corrective action, prevention, and runbook references.")
    if weighted["trace_evidence"] < 1.0:
        messages.append("Inspect required traces to disambiguate noisy secondary alerts.")
    if weighted["policy"] < 1.0:
        messages.append("Avoid actions that violate error-budget policy or increase incident blast radius.")
    if weighted["efficiency"] < 0.9:
        messages.append("Reduce exploratory steps once sufficient evidence has been collected.")
    if not messages:
        messages.append("Full score achieved: diagnosis, mitigation, safety, and postmortem were all complete.")
    return messages


def grade_episode(scenario: IncidentScenario, state: IncidentState) -> dict[str, Any]:
    assessment = state.current_observation.current_assessment
    truth = scenario.hidden_truth

    severity_score = 1.0 if assessment.severity == truth.severity else 0.0
    root_service_score = 1.0 if assessment.root_cause_service == truth.root_cause_service else 0.0
    root_category_score = 1.0 if assessment.root_cause_category == truth.root_cause_category else 0.0
    mitigation_score = mitigation_match_score(assessment.mitigation, truth.mitigation_keywords)

    required_runbooks = {_normalize(item) for item in truth.required_runbooks}
    root_runbook_score = 1.0 if _normalize(assessment.root_cause_runbook or "") in required_runbooks else 0.0
    mitigation_runbook_score = 1.0 if _normalize(assessment.mitigation_runbook or "") in required_runbooks else 0.0

    submitted_affected = set()
    affected_source = " ".join([assessment.close_summary or "", assessment.postmortem_timeline or ""])
    for service in truth.affected_services:
        if service in affected_source:
            submitted_affected.add(service)
    affected_score = round(len(submitted_affected) / len(truth.affected_services), 4)

    trace_score = 1.0
    if truth.required_trace_id:
        trace_score = 1.0 if truth.required_trace_id in state.metrics.visited_trace_ids else 0.0

    execution_score = _execution_plan_score(assessment.executed_mitigation_plan, scenario)
    postmortem_score = _postmortem_score(scenario, state)
    business_impact_score = _business_impact_score(scenario, state)

    efficiency_score = _efficiency_score(state.step_count, state.step_limit)
    policy_score = max(
        0.0,
        1.0 - (state.metrics.policy_violations * 0.35) - (state.metrics.destructive_actions * 0.45),
    )
    safety_score = max(
        0.0,
        1.0 - (state.metrics.repeated_actions * 0.07) - (state.metrics.incorrect_actions * 0.10),
    )

    raw_weighted: dict[str, float] = {
        "root_cause_service": root_service_score,
        "root_cause_category": root_category_score,
        "runbook_diagnosis": root_runbook_score,
        "severity": severity_score,
        "mitigation": mitigation_score,
        "runbook_mitigation": mitigation_runbook_score,
        "mitigation_execution": execution_score,
        "affected_services": affected_score,
        "postmortem_quality": postmortem_score,
        "trace_evidence": trace_score,
        "business_impact": business_impact_score,
        "policy": round(policy_score, 4),
        "efficiency": efficiency_score,
        "safety": round(safety_score, 4),
    }

    final_score = (
        raw_weighted["root_cause_service"] * 0.14
        + raw_weighted["root_cause_category"] * 0.10
        + raw_weighted["runbook_diagnosis"] * 0.06
        + raw_weighted["severity"] * 0.08
        + raw_weighted["mitigation"] * 0.12
        + raw_weighted["runbook_mitigation"] * 0.06
        + raw_weighted["mitigation_execution"] * 0.12
        + raw_weighted["affected_services"] * 0.07
        + raw_weighted["postmortem_quality"] * 0.09
        + raw_weighted["trace_evidence"] * 0.06
        + raw_weighted["business_impact"] * 0.04
        + raw_weighted["policy"] * 0.04
        + raw_weighted["efficiency"] * 0.03
        + raw_weighted["safety"] * 0.09
    )
    # Hackathon validator requires strict open interval (0, 1), not inclusive bounds.
    weighted = {key: _strict_open_interval_score(value) for key, value in raw_weighted.items()}
    weighted["final"] = _strict_open_interval_score(final_score)
    return {
        **weighted,
        "counterfactual": _counterfactual_messages(raw_weighted, scenario),
    }


def grade_easy(state: IncidentState, scenario: IncidentScenario) -> float:
    return float(grade_episode(scenario, state)["final"])


def grade_medium(state: IncidentState, scenario: IncidentScenario) -> float:
    return float(grade_episode(scenario, state)["final"])


def grade_hard(state: IncidentState, scenario: IncidentScenario) -> float:
    return float(grade_episode(scenario, state)["final"])
