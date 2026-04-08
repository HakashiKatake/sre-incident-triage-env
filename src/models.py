from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


SeverityLevel = Literal["info", "warn", "major", "critical"]
Difficulty = Literal["easy", "medium", "hard"]
ScenarioSplit = Literal["public", "holdout"]
MitigationPlan = Literal[
    "rollback_config",
    "restart_service",
    "scale_capacity",
    "flush_cache",
    "drain_traffic",
    "disable_feature_flag",
]


class BusinessImpact(BaseModel):
    impacted_users_pct: float = Field(ge=0.0, le=100.0)
    revenue_risk_per_min_usd: int = Field(ge=0)
    error_budget_remaining_pct: float = Field(ge=0.0, le=100.0)
    notes: str


class AlertEvent(BaseModel):
    alert_id: str
    service: str
    title: str
    severity: SeverityLevel
    summary: str
    fired_at: str


class LogEntry(BaseModel):
    timestamp: str
    service: str
    level: Literal["INFO", "WARN", "ERROR"]
    message: str
    trace_id: str | None = None


class TraceSpan(BaseModel):
    span_id: str
    service: str
    operation: str
    status: Literal["ok", "error"]
    duration_ms: int
    summary: str


class TraceSnippet(BaseModel):
    trace_id: str
    root_service: str
    spans: list[TraceSpan]
    summary: str


class ServiceMetadata(BaseModel):
    service: str
    tier: Literal["edge", "frontend", "backend", "data", "platform"]
    owner: str
    dependencies: list[str]
    runbook: str


class SubmittedAssessment(BaseModel):
    severity: SeverityLevel | None = None
    root_cause_service: str | None = None
    root_cause_category: str | None = None
    root_cause_reason: str | None = None
    root_cause_runbook: str | None = None
    mitigation: str | None = None
    mitigation_runbook: str | None = None
    executed_mitigation_plan: MitigationPlan | None = None
    executed_mitigation_result: str | None = None
    postmortem_timeline: str | None = None
    postmortem_root_cause: str | None = None
    postmortem_corrective_action: str | None = None
    postmortem_prevention_action: str | None = None
    postmortem_runbooks: list[str] = Field(default_factory=list)
    close_summary: str | None = None


class IncidentObservation(BaseModel):
    incident_id: str
    difficulty: Difficulty
    split: ScenarioSplit
    step_count: int
    step_limit: int
    available_services: list[str]
    available_trace_ids: list[str]
    business_impact: BusinessImpact
    visible_alerts: list[AlertEvent]
    visible_logs: dict[str, list[LogEntry]]
    visible_traces: dict[str, TraceSnippet]
    visible_service_metadata: dict[str, ServiceMetadata]
    visible_timeline: list[str]
    hints_unlocked: list[str]
    remaining_budget: int
    resolved: bool
    current_assessment: SubmittedAssessment
    last_action_feedback: str
    last_action_error: str | None = None


class HiddenTruth(BaseModel):
    root_cause_service: str
    root_cause_category: str
    severity: SeverityLevel
    affected_services: list[str]
    mitigation_keywords: list[str]
    preferred_mitigation_plan: MitigationPlan
    risky_mitigation_plans: list[MitigationPlan] = Field(default_factory=list)
    required_runbooks: list[str] = Field(default_factory=list)
    postmortem_keywords: list[str] = Field(default_factory=list)
    business_impact_label: str = "unknown"
    required_trace_id: str | None = None


class EpisodeMetrics(BaseModel):
    total_reward: float
    visited_log_services: list[str]
    visited_trace_ids: list[str]
    visited_metadata_services: list[str]
    inspected_alerts: bool
    inspected_timeline: bool
    repeated_actions: int
    incorrect_actions: int
    destructive_actions: int
    policy_violations: int
    executed_mitigation_plans: list[MitigationPlan]
    runbook_citation_successes: int
    postmortem_submitted: bool


class IncidentState(BaseModel):
    episode_id: str
    seed: int
    difficulty: Difficulty
    step_count: int
    step_limit: int
    done: bool
    scenario_version: str
    current_observation: IncidentObservation
    hidden_truth: HiddenTruth
    metrics: EpisodeMetrics
    action_history: list[dict[str, Any]]
    score: float | None = None


class StepResult(BaseModel):
    observation: IncidentObservation
    reward: float
    done: bool
    info: dict[str, Any] = Field(default_factory=dict)


class InspectLogs(BaseModel):
    action_type: Literal["inspect_logs"] = "inspect_logs"
    service_name: str
    limit: int = Field(default=5, ge=1, le=20)


class InspectAlerts(BaseModel):
    action_type: Literal["inspect_alerts"] = "inspect_alerts"


class InspectTrace(BaseModel):
    action_type: Literal["inspect_trace"] = "inspect_trace"
    trace_id: str


class InspectServiceMetadata(BaseModel):
    action_type: Literal["inspect_service_metadata"] = "inspect_service_metadata"
    service_name: str


class InspectTimeline(BaseModel):
    action_type: Literal["inspect_timeline"] = "inspect_timeline"


class ClassifySeverity(BaseModel):
    action_type: Literal["classify_severity"] = "classify_severity"
    severity: SeverityLevel


class IdentifyRootCause(BaseModel):
    action_type: Literal["identify_root_cause"] = "identify_root_cause"
    service_name: str
    cause_category: str
    reason: str
    runbook_id: str


class RecommendMitigation(BaseModel):
    action_type: Literal["recommend_mitigation"] = "recommend_mitigation"
    action: str
    runbook_id: str


class ExecuteMitigation(BaseModel):
    action_type: Literal["execute_mitigation"] = "execute_mitigation"
    plan: MitigationPlan
    justification: str


class SubmitPostmortem(BaseModel):
    action_type: Literal["submit_postmortem"] = "submit_postmortem"
    timeline_summary: str
    root_cause: str
    corrective_action: str
    prevention_action: str
    runbook_ids: list[str] = Field(default_factory=list)


class CloseIncident(BaseModel):
    action_type: Literal["close_incident"] = "close_incident"
    summary: str = ""


IncidentAction = Annotated[
    Union[
        InspectLogs,
        InspectAlerts,
        InspectTrace,
        InspectServiceMetadata,
        InspectTimeline,
        ClassifySeverity,
        IdentifyRootCause,
        RecommendMitigation,
        ExecuteMitigation,
        SubmitPostmortem,
        CloseIncident,
    ],
    Field(discriminator="action_type"),
]
