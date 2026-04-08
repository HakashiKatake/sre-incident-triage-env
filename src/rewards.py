from __future__ import annotations

from src.models import (
    ClassifySeverity,
    CloseIncident,
    ExecuteMitigation,
    IdentifyRootCause,
    IncidentAction,
    RecommendMitigation,
    SubmitPostmortem,
)
from src.scenarios import IncidentScenario


def reward_for_action(
    scenario: IncidentScenario,
    action: IncidentAction,
    *,
    repeated: bool,
    already_done: bool,
    inspected_relevant: bool,
    trace_required_and_seen: bool,
    severity_correct: bool,
    severity_near_miss: bool,
    root_service_correct: bool,
    root_category_correct: bool,
    root_runbook_correct: bool,
    mitigation_score: float,
    mitigation_runbook_correct: bool,
    executed_plan_score: float,
    destructive_execution: bool,
    policy_violation: bool,
    postmortem_score: float,
    business_impact_alignment: bool,
    close_ready: bool,
    step_efficiency_penalty: float,
) -> tuple[float, str]:
    if already_done:
        return -0.25, "Incident is already closed."

    reward = -step_efficiency_penalty
    feedback = "Action processed."

    if repeated:
        reward -= 0.05
        feedback = "Repeated inspection added limited new information."

    match action:
        case ClassifySeverity():
            if severity_correct:
                reward += 0.18
                if business_impact_alignment:
                    reward += 0.03
                feedback = "Severity classification matches impact and SLO context."
            elif severity_near_miss:
                reward += 0.07
                feedback = "Severity is close but slightly misaligned with business impact."
            else:
                reward -= 0.10
                feedback = "Severity classification is inconsistent with the evidence."
        case IdentifyRootCause():
            reward += 0.16 if root_service_correct else -0.12
            reward += 0.10 if root_category_correct else -0.07
            reward += 0.08 if root_runbook_correct else -0.05
            feedback = "Root cause hypothesis and runbook citation recorded."
        case RecommendMitigation():
            reward += (mitigation_score * 0.22) - (0.08 if mitigation_score < 0.34 else 0.0)
            reward += 0.06 if mitigation_runbook_correct else -0.04
            feedback = "Mitigation proposal captured with runbook context."
        case ExecuteMitigation():
            reward += (executed_plan_score * 0.28) - (0.08 if executed_plan_score < 0.34 else 0.0)
            if destructive_execution:
                reward -= 0.18
                feedback = "Executed mitigation increased blast radius."
            elif policy_violation:
                reward -= 0.10
                feedback = "Mitigation violated error-budget policy."
            else:
                reward += 0.06
                feedback = "Mitigation execution was safe and policy-compliant."
        case SubmitPostmortem():
            reward += postmortem_score * 0.22
            reward -= 0.05 if postmortem_score < 0.4 else 0.0
            feedback = "Postmortem draft captured for incident review."
        case CloseIncident():
            if close_ready:
                reward += 0.16
                feedback = "Incident closed with sufficient diagnostic and remediation evidence."
            else:
                reward -= 0.22
                feedback = "Incident closed before the response met reliability policy."
        case _:
            if inspected_relevant:
                reward += 0.08
                feedback = "Relevant evidence inspected."
            else:
                reward -= 0.03
                feedback = "Inspection was low-signal for this incident."
            if trace_required_and_seen and scenario.hidden_truth.required_trace_id:
                reward += 0.03

    return round(reward, 4), feedback

