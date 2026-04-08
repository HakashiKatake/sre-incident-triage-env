from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from src.grading import mitigation_match_score
from src.models import (
    ClassifySeverity,
    CloseIncident,
    EpisodeMetrics,
    ExecuteMitigation,
    HiddenTruth,
    IdentifyRootCause,
    IncidentAction,
    IncidentObservation,
    IncidentState,
    InspectAlerts,
    InspectLogs,
    InspectServiceMetadata,
    InspectTimeline,
    InspectTrace,
    RecommendMitigation,
    ScenarioSplit,
    StepResult,
    SubmitPostmortem,
    SubmittedAssessment,
)
from src.rewards import reward_for_action
from src.scenarios import IncidentScenario, build_scenario
from src.tasks import get_task_definition, grade_task


ACTION_ADAPTER = TypeAdapter(IncidentAction)


class SREIncidentTriageEnv:
    def __init__(self, difficulty: str = "easy", seed: int = 0, split: ScenarioSplit = "public") -> None:
        self.default_difficulty = difficulty
        self.default_seed = seed
        self.default_split = split
        self._scenario: IncidentScenario | None = None
        self._state: IncidentState | None = None

    def reset(
        self,
        difficulty: str | None = None,
        seed: int | None = None,
        split: ScenarioSplit | None = None,
    ) -> StepResult:
        actual_difficulty = difficulty or self.default_difficulty
        actual_seed = self.default_seed if seed is None else seed
        actual_split = self.default_split if split is None else split
        self._scenario = build_scenario(actual_difficulty, actual_seed, actual_split)
        observation = IncidentObservation(
            incident_id=self._scenario.incident_id,
            difficulty=self._scenario.difficulty,
            split=self._scenario.split,
            step_count=0,
            step_limit=self._scenario.step_limit,
            available_services=self._scenario.available_services,
            available_trace_ids=sorted(self._scenario.evidence.traces.keys()),
            business_impact=self._scenario.business_impact,
            visible_alerts=[],
            visible_logs={},
            visible_traces={},
            visible_service_metadata={},
            visible_timeline=[],
            hints_unlocked=[],
            remaining_budget=self._scenario.step_limit,
            resolved=False,
            current_assessment=SubmittedAssessment(),
            last_action_feedback="Incident created. Inspect evidence to begin triage.",
            last_action_error=None,
        )
        self._state = IncidentState(
            episode_id=self._scenario.incident_id,
            seed=actual_seed,
            difficulty=self._scenario.difficulty,
            step_count=0,
            step_limit=self._scenario.step_limit,
            done=False,
            scenario_version=self._scenario.scenario_version,
            current_observation=observation,
            hidden_truth=self._scenario.hidden_truth,
            metrics=EpisodeMetrics(
                total_reward=0.0,
                visited_log_services=[],
                visited_trace_ids=[],
                visited_metadata_services=[],
                inspected_alerts=False,
                inspected_timeline=False,
                repeated_actions=0,
                incorrect_actions=0,
                destructive_actions=0,
                policy_violations=0,
                executed_mitigation_plans=[],
                runbook_citation_successes=0,
                postmortem_submitted=False,
            ),
            action_history=[],
            score=None,
        )
        return StepResult(
            observation=observation,
            reward=0.0,
            done=False,
            info={"difficulty": actual_difficulty, "seed": actual_seed, "split": actual_split, "last_action_error": None},
        )

    def step(self, action: IncidentAction | dict[str, Any]) -> StepResult:
        self._ensure_ready()
        assert self._scenario is not None
        assert self._state is not None

        parsed_action = ACTION_ADAPTER.validate_python(action)
        if self._state.done:
            reward, feedback = reward_for_action(
                self._scenario,
                parsed_action,
                repeated=False,
                already_done=True,
                inspected_relevant=False,
                trace_required_and_seen=False,
                severity_correct=False,
                severity_near_miss=False,
                root_service_correct=False,
                root_category_correct=False,
                root_runbook_correct=False,
                mitigation_score=0.0,
                mitigation_runbook_correct=False,
                executed_plan_score=0.0,
                destructive_execution=False,
                policy_violation=False,
                postmortem_score=0.0,
                business_impact_alignment=False,
                close_ready=False,
                step_efficiency_penalty=0.0,
            )
            observation = self._state.current_observation.model_copy(update={"last_action_feedback": feedback, "last_action_error": None})
            self._state.current_observation = observation
            return StepResult(observation=observation, reward=reward, done=True, info={"score": self._state.score, "last_action_error": None})

        repeated = self._is_repeated_action(parsed_action)
        if repeated:
            self._state.metrics.repeated_actions += 1

        self._state.step_count += 1
        obs = self._state.current_observation.model_copy(deep=True)
        assessment = obs.current_assessment.model_copy(deep=True)
        relevant = False
        trace_required_and_seen = False
        severity_correct = False
        severity_near_miss = False
        root_service_correct = False
        root_category_correct = False
        root_runbook_correct = False
        mitigation_score = 0.0
        mitigation_runbook_correct = False
        executed_plan_score = 0.0
        destructive_execution = False
        policy_violation = False
        postmortem_score = 0.0
        business_impact_alignment = False
        step_efficiency_penalty = 0.01
        last_action_error: str | None = None

        match parsed_action:
            case InspectAlerts():
                obs.visible_alerts = self._scenario.evidence.alerts
                self._state.metrics.inspected_alerts = True
                relevant = True
            case InspectLogs(service_name=service_name, limit=limit):
                logs = self._scenario.evidence.logs.get(service_name, [])[:limit]
                obs.visible_logs[service_name] = logs
                relevant = service_name in self._scenario.evidence.relevant_log_services
                if service_name not in self._state.metrics.visited_log_services:
                    self._state.metrics.visited_log_services.append(service_name)
            case InspectTrace(trace_id=trace_id):
                trace = self._scenario.evidence.traces.get(trace_id)
                if trace is not None:
                    obs.visible_traces[trace_id] = trace
                relevant = trace_id in self._scenario.evidence.relevant_trace_ids
                trace_required_and_seen = relevant
                if trace_id not in self._state.metrics.visited_trace_ids:
                    self._state.metrics.visited_trace_ids.append(trace_id)
            case InspectServiceMetadata(service_name=service_name):
                metadata = self._scenario.evidence.service_metadata.get(service_name)
                if metadata is not None:
                    obs.visible_service_metadata[service_name] = metadata
                relevant = service_name in self._scenario.evidence.relevant_metadata_services
                if service_name not in self._state.metrics.visited_metadata_services:
                    self._state.metrics.visited_metadata_services.append(service_name)
            case InspectTimeline():
                obs.visible_timeline = self._scenario.evidence.timeline
                self._state.metrics.inspected_timeline = True
                relevant = True
            case ClassifySeverity(severity=severity):
                assessment.severity = severity
                severity_correct = severity == self._scenario.hidden_truth.severity
                severity_near_miss = _severity_distance(severity, self._scenario.hidden_truth.severity) == 1
                business_impact_alignment = self._severity_aligned_with_business_impact(severity)
                if not severity_correct and not severity_near_miss:
                    self._state.metrics.incorrect_actions += 1
            case IdentifyRootCause(service_name=service_name, cause_category=cause_category, reason=reason, runbook_id=runbook_id):
                assessment.root_cause_service = service_name
                assessment.root_cause_category = cause_category
                assessment.root_cause_reason = reason
                assessment.root_cause_runbook = runbook_id
                root_service_correct = service_name == self._scenario.hidden_truth.root_cause_service
                root_category_correct = cause_category == self._scenario.hidden_truth.root_cause_category
                root_runbook_correct = self._runbook_is_correct(runbook_id, service_name)
                if root_runbook_correct:
                    self._state.metrics.runbook_citation_successes += 1
                if not (root_service_correct and root_category_correct and root_runbook_correct):
                    self._state.metrics.incorrect_actions += 1
            case RecommendMitigation(action=mitigation, runbook_id=runbook_id):
                assessment.mitigation = mitigation
                assessment.mitigation_runbook = runbook_id
                mitigation_score = mitigation_match_score(mitigation, self._scenario.hidden_truth.mitigation_keywords)
                mitigation_runbook_correct = self._runbook_is_correct(runbook_id, self._scenario.hidden_truth.root_cause_service)
                if mitigation_runbook_correct:
                    self._state.metrics.runbook_citation_successes += 1
                if mitigation_score < 0.34 or not mitigation_runbook_correct:
                    self._state.metrics.incorrect_actions += 1
            case ExecuteMitigation(plan=plan, justification=justification):
                assessment.executed_mitigation_plan = plan
                assessment.executed_mitigation_result = f"Executed {plan}: {justification}"
                executed_plan_score = self._execution_score(plan)
                destructive_execution = plan in self._scenario.hidden_truth.risky_mitigation_plans
                policy_violation = self._policy_violation(plan)
                self._state.metrics.executed_mitigation_plans.append(plan)
                if destructive_execution:
                    self._state.metrics.destructive_actions += 1
                    self._state.metrics.incorrect_actions += 1
                if policy_violation:
                    self._state.metrics.policy_violations += 1
            case SubmitPostmortem(
                timeline_summary=timeline_summary,
                root_cause=root_cause,
                corrective_action=corrective_action,
                prevention_action=prevention_action,
                runbook_ids=runbook_ids,
            ):
                assessment.postmortem_timeline = timeline_summary
                assessment.postmortem_root_cause = root_cause
                assessment.postmortem_corrective_action = corrective_action
                assessment.postmortem_prevention_action = prevention_action
                assessment.postmortem_runbooks = runbook_ids
                postmortem_score = self._postmortem_completeness(assessment)
                self._state.metrics.postmortem_submitted = True
            case CloseIncident(summary=summary):
                assessment.close_summary = summary

        obs.current_assessment = assessment
        hint = self._hint_for_action(parsed_action)
        if hint and hint not in obs.hints_unlocked:
            obs.hints_unlocked.append(hint)
        close_ready = self._close_ready(assessment, self._scenario.hidden_truth)
        reward, feedback = reward_for_action(
            self._scenario,
            parsed_action,
            repeated=repeated,
            already_done=False,
            inspected_relevant=relevant,
            trace_required_and_seen=trace_required_and_seen,
            severity_correct=severity_correct,
            severity_near_miss=severity_near_miss,
            root_service_correct=root_service_correct,
            root_category_correct=root_category_correct,
            root_runbook_correct=root_runbook_correct,
            mitigation_score=mitigation_score,
            mitigation_runbook_correct=mitigation_runbook_correct,
            executed_plan_score=executed_plan_score,
            destructive_execution=destructive_execution,
            policy_violation=policy_violation,
            postmortem_score=postmortem_score,
            business_impact_alignment=business_impact_alignment,
            close_ready=close_ready,
            step_efficiency_penalty=step_efficiency_penalty,
        )
        done = isinstance(parsed_action, CloseIncident) or self._state.step_count >= self._state.step_limit
        if isinstance(parsed_action, CloseIncident) and not close_ready:
            self._state.metrics.incorrect_actions += 1
            last_action_error = "premature_close_or_missing_requirements"

        obs.step_count = self._state.step_count
        obs.remaining_budget = max(0, self._state.step_limit - self._state.step_count)
        obs.last_action_feedback = feedback
        obs.last_action_error = last_action_error
        obs.resolved = bool(done)

        self._state.metrics.total_reward = round(self._state.metrics.total_reward + reward, 4)
        self._state.current_observation = obs
        self._state.done = done
        self._state.action_history.append(parsed_action.model_dump())

        info: dict[str, Any] = {
            "difficulty": self._scenario.difficulty,
            "split": self._scenario.split,
            "incident_id": self._scenario.incident_id,
            "hint_unlocked": hint,
            "last_action_error": last_action_error,
        }
        if done:
            graded = grade_task(self._scenario.difficulty, self._scenario.split, self._state, self._state.seed)
            self._state.score = float(graded["final"])
            info["grading"] = graded
            info["score"] = graded["final"]
            info["counterfactual_report"] = graded.get("counterfactual", [])
            info["task"] = get_task_definition(self._scenario.difficulty, self._scenario.split).model_dump()

        return StepResult(observation=obs, reward=reward, done=done, info=info)

    def state(self) -> IncidentState:
        self._ensure_ready()
        assert self._state is not None
        return self._state

    def _ensure_ready(self) -> None:
        if self._scenario is None or self._state is None:
            self.reset()

    def _is_repeated_action(self, action: IncidentAction) -> bool:
        assert self._state is not None
        current = action.model_dump()
        return current in self._state.action_history

    def _hint_for_action(self, action: IncidentAction) -> str | None:
        assert self._scenario is not None
        key = action.action_type
        service_name = getattr(action, "service_name", None)
        trace_id = getattr(action, "trace_id", None)
        severity = getattr(action, "severity", None)
        candidates = [key]
        if service_name:
            candidates.append(f"{key}:{service_name}")
        if trace_id:
            candidates.append(f"{key}:{trace_id}")
        if severity:
            candidates.append(f"{key}:{severity}")
        return next((self._scenario.evidence.relevant_hints[c] for c in candidates if c in self._scenario.evidence.relevant_hints), None)

    def _runbook_is_correct(self, runbook_id: str, service_name: str) -> bool:
        assert self._scenario is not None
        metadata = self._scenario.evidence.service_metadata.get(service_name)
        if metadata is None:
            return False
        truth_runbooks = set(self._scenario.hidden_truth.required_runbooks)
        return runbook_id == metadata.runbook and (runbook_id in truth_runbooks or not truth_runbooks)

    def _execution_score(self, plan: str) -> float:
        assert self._scenario is not None
        if plan == self._scenario.hidden_truth.preferred_mitigation_plan:
            return 1.0
        if plan in self._scenario.hidden_truth.risky_mitigation_plans:
            return 0.0
        return 0.55

    def _policy_violation(self, plan: str) -> bool:
        assert self._scenario is not None
        low_budget = self._scenario.business_impact.error_budget_remaining_pct <= 15.0
        if plan in self._scenario.hidden_truth.risky_mitigation_plans:
            return True
        if low_budget and plan in {"restart_service", "drain_traffic"}:
            return True
        return False

    def _postmortem_completeness(self, assessment: SubmittedAssessment) -> float:
        required = [
            assessment.postmortem_timeline,
            assessment.postmortem_root_cause,
            assessment.postmortem_corrective_action,
            assessment.postmortem_prevention_action,
        ]
        score = sum(1 for item in required if item and len(item.strip()) > 8) / 4
        if assessment.postmortem_runbooks:
            score += 0.2
        return min(1.0, round(score, 4))

    def _severity_aligned_with_business_impact(self, severity: str) -> bool:
        assert self._scenario is not None
        impact = self._scenario.business_impact
        if impact.impacted_users_pct >= 50 or impact.revenue_risk_per_min_usd >= 7000:
            return severity == "critical"
        if impact.impacted_users_pct >= 20 or impact.revenue_risk_per_min_usd >= 700:
            return severity in {"major", "critical"}
        return severity in {"warn", "major"}

    def _close_ready(self, assessment: SubmittedAssessment, truth: HiddenTruth) -> bool:
        severity_ok = assessment.severity == truth.severity
        root_service_ok = assessment.root_cause_service == truth.root_cause_service
        category_ok = assessment.root_cause_category == truth.root_cause_category
        runbook_ok = (assessment.root_cause_runbook in truth.required_runbooks) and (
            assessment.mitigation_runbook in truth.required_runbooks
        )
        mitigation_ok = mitigation_match_score(assessment.mitigation, truth.mitigation_keywords) >= 0.5
        execution_ok = assessment.executed_mitigation_plan == truth.preferred_mitigation_plan
        trace_ok = True
        if truth.required_trace_id:
            assert self._state is not None
            trace_ok = truth.required_trace_id in self._state.metrics.visited_trace_ids
        postmortem_ok = True
        if self._scenario and self._scenario.difficulty == "hard":
            postmortem_ok = self._postmortem_completeness(assessment) >= 0.8
        return severity_ok and root_service_ok and category_ok and runbook_ok and mitigation_ok and execution_ok and trace_ok and postmortem_ok


def _severity_distance(left: str, right: str) -> int:
    rank = {"info": 0, "warn": 1, "major": 2, "critical": 3}
    return abs(rank[left] - rank[right])
