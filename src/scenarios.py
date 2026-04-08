from __future__ import annotations

from pydantic import BaseModel

from src.models import (
    AlertEvent,
    BusinessImpact,
    Difficulty,
    HiddenTruth,
    LogEntry,
    ScenarioSplit,
    ServiceMetadata,
    TraceSnippet,
    TraceSpan,
)


class ScenarioEvidence(BaseModel):
    alerts: list[AlertEvent]
    logs: dict[str, list[LogEntry]]
    traces: dict[str, TraceSnippet]
    service_metadata: dict[str, ServiceMetadata]
    timeline: list[str]
    relevant_log_services: list[str]
    relevant_metadata_services: list[str]
    relevant_trace_ids: list[str]
    relevant_hints: dict[str, str]
    noisy_log_services: list[str] = []


class IncidentScenario(BaseModel):
    incident_id: str
    difficulty: Difficulty
    split: ScenarioSplit
    title: str
    summary: str
    step_limit: int
    available_services: list[str]
    business_impact: BusinessImpact
    evidence: ScenarioEvidence
    hidden_truth: HiddenTruth
    scenario_version: str = "2026.05"


def _variant(seed: int, values: list[str], offset: int = 0) -> str:
    return values[(seed + offset) % len(values)]


def build_scenario(difficulty: Difficulty, seed: int = 0, split: ScenarioSplit = "public") -> IncidentScenario:
    if difficulty == "easy":
        return _build_easy(seed, split)
    if difficulty == "medium":
        return _build_medium(seed, split)
    return _build_hard(seed, split)


def evaluation_suite() -> list[tuple[str, Difficulty, ScenarioSplit, int]]:
    return [
        ("easy_public", "easy", "public", 11),
        ("medium_public", "medium", "public", 22),
        ("hard_public", "hard", "public", 33),
        ("easy_holdout", "easy", "holdout", 111),
        ("medium_holdout", "medium", "holdout", 122),
        ("hard_holdout", "hard", "holdout", 133),
    ]


def _build_easy(seed: int, split: ScenarioSplit) -> IncidentScenario:
    if split == "public":
        root_service = "auth-service"
        root_category = "db_pool_exhaustion"
        runbook = "rb://auth-service/db-pool"
        services = ["edge-gateway", "auth-service", "user-db"]
        trace_id = f"easy-public-trace-{seed % 3}"
        title = "Login failures after auth-service saturation"
        summary = "Users cannot sign in because auth-service returns 503."
        logs = {
            "auth-service": [
                LogEntry(
                    timestamp="2026-04-08T10:01:14Z",
                    service="auth-service",
                    level="ERROR",
                    message="psycopg_pool.PoolTimeout while acquiring connection active=64 queued=91",
                    trace_id=trace_id,
                ),
                LogEntry(
                    timestamp="2026-04-08T10:01:22Z",
                    service="auth-service",
                    level="ERROR",
                    message="request failed: downstream user-db unavailable because pool checkout timed out",
                    trace_id=trace_id,
                ),
            ],
            "edge-gateway": [
                LogEntry(
                    timestamp="2026-04-08T10:01:25Z",
                    service="edge-gateway",
                    level="WARN",
                    message="upstream auth-service returned 503 for POST /login",
                    trace_id=trace_id,
                )
            ],
            "user-db": [
                LogEntry(
                    timestamp="2026-04-08T10:00:58Z",
                    service="user-db",
                    level="INFO",
                    message="connections steady at 62/64; no replication lag detected",
                )
            ],
        }
        metadata = {
            "edge-gateway": ServiceMetadata(
                service="edge-gateway",
                tier="edge",
                owner="traffic-platform",
                dependencies=["auth-service"],
                runbook="rb://edge-gateway/503s",
            ),
            "auth-service": ServiceMetadata(
                service="auth-service",
                tier="backend",
                owner="identity",
                dependencies=["user-db"],
                runbook=runbook,
            ),
            "user-db": ServiceMetadata(
                service="user-db",
                tier="data",
                owner="identity-data",
                dependencies=[],
                runbook="rb://user-db/connections",
            ),
        }
        timeline = [
            "09:58 UTC deploy auth-service v2026.04.08.1",
            "10:01 UTC login latency climbs above 2s",
            "10:02 UTC auth-service 5xx alert fires",
        ]
    else:
        root_service = "session-service"
        root_category = "cache_pool_exhaustion"
        runbook = "rb://session-service/cache-pool"
        services = ["edge-gateway", "session-service", "session-cache"]
        trace_id = f"easy-holdout-trace-{seed % 3}"
        title = "Session creation failures from exhausted cache pool"
        summary = "User sessions fail because session-service cannot acquire cache connections."
        logs = {
            "session-service": [
                LogEntry(
                    timestamp="2026-04-10T09:01:11Z",
                    service="session-service",
                    level="ERROR",
                    message="redis pool exhausted: waited 20s for free client, active=128 queued=53",
                    trace_id=trace_id,
                ),
                LogEntry(
                    timestamp="2026-04-10T09:01:15Z",
                    service="session-service",
                    level="ERROR",
                    message="session token mint failed due to cache acquisition timeout",
                    trace_id=trace_id,
                ),
            ],
            "edge-gateway": [
                LogEntry(
                    timestamp="2026-04-10T09:01:18Z",
                    service="edge-gateway",
                    level="WARN",
                    message="upstream session-service returned 503 for POST /session/new",
                    trace_id=trace_id,
                )
            ],
            "session-cache": [
                LogEntry(
                    timestamp="2026-04-10T09:01:00Z",
                    service="session-cache",
                    level="INFO",
                    message="cache hit ratio 0.92; no cluster failover",
                )
            ],
        }
        metadata = {
            "edge-gateway": ServiceMetadata(
                service="edge-gateway",
                tier="edge",
                owner="traffic-platform",
                dependencies=["session-service"],
                runbook="rb://edge-gateway/503s",
            ),
            "session-service": ServiceMetadata(
                service="session-service",
                tier="backend",
                owner="identity",
                dependencies=["session-cache"],
                runbook=runbook,
            ),
            "session-cache": ServiceMetadata(
                service="session-cache",
                tier="data",
                owner="identity-data",
                dependencies=[],
                runbook="rb://session-cache/capacity",
            ),
        }
        timeline = [
            "08:58 UTC rollout session-service v2026.04.10.2",
            "09:01 UTC session creation latency climbs above 1.8s",
            "09:02 UTC session-service availability alert fires",
        ]

    incident_id = f"inc-{split}-easy-{seed:03d}"
    return IncidentScenario(
        incident_id=incident_id,
        difficulty="easy",
        split=split,
        title=title,
        summary=summary,
        step_limit=10,
        available_services=services,
        business_impact=BusinessImpact(
            impacted_users_pct=31.0 if split == "public" else 24.0,
            revenue_risk_per_min_usd=920,
            error_budget_remaining_pct=44.0,
            notes="Authentication/session path degraded for a large share of user traffic.",
        ),
        hidden_truth=HiddenTruth(
            root_cause_service=root_service,
            root_cause_category=root_category,
            severity="major",
            affected_services=[root_service, "edge-gateway"],
            mitigation_keywords=["scale", root_service, "pool", "connection"],
            preferred_mitigation_plan="scale_capacity",
            risky_mitigation_plans=["restart_service"],
            required_runbooks=[runbook],
            postmortem_keywords=[root_service, "timeline", "corrective", "prevention", "error budget"],
            business_impact_label="customer_auth_path",
        ),
        evidence=ScenarioEvidence(
            alerts=[
                AlertEvent(
                    alert_id=f"ALERT-{incident_id}-1",
                    service=root_service,
                    title="Auth/session 5xx above SLO",
                    severity="major",
                    summary="5xx rate exceeded 15% for 6m.",
                    fired_at="2026-04-08T10:02:00Z",
                )
            ],
            logs=logs,
            traces={
                trace_id: TraceSnippet(
                    trace_id=trace_id,
                    root_service="edge-gateway",
                    summary="Request fails while root service waits for backend pool acquisition.",
                    spans=[
                        TraceSpan(
                            span_id="1",
                            service="edge-gateway",
                            operation="POST auth/session",
                            status="error",
                            duration_ms=1040,
                            summary="Gateway forwards user request",
                        ),
                        TraceSpan(
                            span_id="2",
                            service=root_service,
                            operation="pool_checkout",
                            status="error",
                            duration_ms=1015,
                            summary="Pool wait timeout triggered",
                        ),
                    ],
                )
            },
            service_metadata=metadata,
            timeline=timeline,
            relevant_log_services=[root_service, "edge-gateway"],
            relevant_metadata_services=[root_service],
            relevant_trace_ids=[trace_id],
            relevant_hints={
                f"inspect_logs:{root_service}": "Root service logs show pool exhaustion before edge symptoms.",
                "recommend_mitigation": "Scaling pool capacity is safer than restarts when error budget is already tight.",
            },
            noisy_log_services=["session-cache" if split == "holdout" else "user-db"],
        ),
    )


def _build_medium(seed: int, split: ScenarioSplit) -> IncidentScenario:
    if split == "public":
        root_service = "inventory-db"
        culprit_service = "inventory-service"
        runbook = "rb://inventory-db/max-connections"
        services = ["frontend-api", "checkout-service", "inventory-service", "inventory-db", "cart-service"]
        trace_id = f"medium-public-trace-{seed % 4}"
        title = "Checkout degradation caused by saturated inventory database"
        summary = "Checkout and cart calls fail during inventory reservation."
    else:
        root_service = "pricing-db"
        culprit_service = "pricing-service"
        runbook = "rb://pricing-db/connection-capacity"
        services = ["frontend-api", "checkout-service", "pricing-service", "pricing-db", "cart-service"]
        trace_id = f"medium-holdout-trace-{seed % 4}"
        title = "Checkout degradation caused by saturated pricing database"
        summary = "Pricing quote calls fail, causing checkout fallback loops."

    incident_id = f"inc-{split}-medium-{seed:03d}"
    logs = {
        "checkout-service": [
            LogEntry(
                timestamp="2026-04-08T11:12:03Z",
                service="checkout-service",
                level="ERROR",
                message=f"upstream {culprit_service} call exceeded 4500ms and failed after retries",
                trace_id=trace_id,
            ),
        ],
        culprit_service: [
            LogEntry(
                timestamp="2026-04-08T11:11:49Z",
                service=culprit_service,
                level="ERROR",
                message=f"QueuePool limit reached while connecting to {root_service}",
                trace_id=trace_id,
            ),
            LogEntry(
                timestamp="2026-04-08T11:12:05Z",
                service=culprit_service,
                level="WARN",
                message=f"worker backlog growing due to {root_service} connection wait",
                trace_id=trace_id,
            ),
        ],
        root_service: [
            LogEntry(
                timestamp="2026-04-08T11:11:40Z",
                service=root_service,
                level="WARN",
                message="max_connections reached; rejecting new clients",
            ),
        ],
        "cart-service": [
            LogEntry(
                timestamp="2026-04-08T11:10:59Z",
                service="cart-service",
                level="WARN",
                message="retrying checkout-session sync after downstream 504",
            )
        ],
        "frontend-api": [
            LogEntry(
                timestamp="2026-04-08T11:12:13Z",
                service="frontend-api",
                level="WARN",
                message="customer saw checkout spinner for 5.1s before error banner",
                trace_id=trace_id,
            )
        ],
    }
    metadata = {
        "frontend-api": ServiceMetadata(
            service="frontend-api",
            tier="frontend",
            owner="commerce-ui",
            dependencies=["checkout-service"],
            runbook="rb://frontend-api/latency",
        ),
        "checkout-service": ServiceMetadata(
            service="checkout-service",
            tier="backend",
            owner="commerce-core",
            dependencies=[culprit_service, "cart-service"],
            runbook="rb://checkout-service/retries",
        ),
        culprit_service: ServiceMetadata(
            service=culprit_service,
            tier="backend",
            owner="commerce-pricing" if split == "holdout" else "inventory",
            dependencies=[root_service],
            runbook=f"rb://{culprit_service}/db-timeouts",
        ),
        root_service: ServiceMetadata(
            service=root_service,
            tier="data",
            owner="commerce-data",
            dependencies=[],
            runbook=runbook,
        ),
        "cart-service": ServiceMetadata(
            service="cart-service",
            tier="backend",
            owner="commerce-core",
            dependencies=["checkout-service"],
            runbook="rb://cart-service/downstream-errors",
        ),
    }
    timeline = [
        "11:07 UTC promotional traffic increases 3x",
        "11:11 UTC checkout latency alert fires",
        f"11:13 UTC {culprit_service} timeout alert fires",
    ]
    return IncidentScenario(
        incident_id=incident_id,
        difficulty="medium",
        split=split,
        title=title,
        summary=summary,
        step_limit=12,
        available_services=services,
        business_impact=BusinessImpact(
            impacted_users_pct=42.0,
            revenue_risk_per_min_usd=3100,
            error_budget_remaining_pct=28.0,
            notes="Checkout conversions are severely reduced during traffic surge.",
        ),
        hidden_truth=HiddenTruth(
            root_cause_service=root_service,
            root_cause_category="connection_saturation",
            severity="major",
            affected_services=[root_service, culprit_service, "checkout-service", "frontend-api"],
            mitigation_keywords=["scale", root_service, "connection", "throttle"],
            preferred_mitigation_plan="scale_capacity",
            risky_mitigation_plans=["restart_service", "drain_traffic"],
            required_runbooks=[runbook],
            postmortem_keywords=[root_service, culprit_service, "checkout-service", "error budget", "prevention"],
            business_impact_label="checkout_conversion_loss",
        ),
        evidence=ScenarioEvidence(
            alerts=[
                AlertEvent(
                    alert_id=f"ALERT-{incident_id}-1",
                    service="checkout-service",
                    title="Checkout latency high",
                    severity="major",
                    summary="P95 checkout latency exceeded 4.8s for 10m.",
                    fired_at="2026-04-08T11:11:00Z",
                ),
                AlertEvent(
                    alert_id=f"ALERT-{incident_id}-2",
                    service=culprit_service,
                    title="Reservation/quote timeout burst",
                    severity="major",
                    summary="Timeouts increased 7x.",
                    fired_at="2026-04-08T11:13:00Z",
                ),
            ],
            logs=logs,
            traces={
                trace_id: TraceSnippet(
                    trace_id=trace_id,
                    root_service="frontend-api",
                    summary=f"Checkout failure cascades from {culprit_service} waiting on {root_service}.",
                    spans=[
                        TraceSpan(
                            span_id="1",
                            service="frontend-api",
                            operation="POST /checkout",
                            status="error",
                            duration_ms=4920,
                            summary="Frontend request enters checkout-service",
                        ),
                        TraceSpan(
                            span_id="2",
                            service="checkout-service",
                            operation="dependency_call",
                            status="error",
                            duration_ms=4860,
                            summary="Retry storm while waiting on dependency service",
                        ),
                        TraceSpan(
                            span_id="3",
                            service=culprit_service,
                            operation="query_backend",
                            status="error",
                            duration_ms=4802,
                            summary=f"Pool timeout while connecting to {root_service}",
                        ),
                    ],
                )
            },
            service_metadata=metadata,
            timeline=timeline,
            relevant_log_services=[culprit_service, root_service, "checkout-service"],
            relevant_metadata_services=[culprit_service, root_service],
            relevant_trace_ids=[trace_id],
            relevant_hints={
                f"inspect_logs:{root_service}": f"{root_service} is refusing new clients, so checkout is a symptom.",
                "execute_mitigation": "Prefer capacity scaling over hard restarts when error budget is low.",
            },
            noisy_log_services=["cart-service"],
        ),
    )


def _build_hard(seed: int, split: ScenarioSplit) -> IncidentScenario:
    noisy_node = _variant(seed, ["gw-1", "gw-2", "gw-3"], offset=1)
    if split == "public":
        root_service = "service-discovery"
        runbook = "rb://service-discovery/config-rollbacks"
        title = "Intermittent checkout outage caused by bad service-discovery rollout"
        summary = "Payment auth fails across services with misleading gateway CPU noise."
        services = [
            "edge-gateway",
            "checkout-service",
            "payments-api",
            "service-discovery",
            "feature-flags",
            "metrics-pipeline",
        ]
        trace_id = f"hard-public-trace-{seed % 5}"
        rollout = _variant(seed, ["rollout-417", "rollout-423", "rollout-431"])
    else:
        root_service = "config-distributor"
        runbook = "rb://config-distributor/rollback"
        title = "Distributed payment outage caused by bad config-distributor rollout"
        summary = "Payments fail with noisy gateway and metrics alerts masking config corruption."
        services = [
            "edge-gateway",
            "checkout-service",
            "payments-api",
            "config-distributor",
            "feature-flags",
            "metrics-pipeline",
        ]
        trace_id = f"hard-holdout-trace-{seed % 5}"
        rollout = _variant(seed, ["rollout-880", "rollout-883", "rollout-891"])

    incident_id = f"inc-{split}-hard-{seed:03d}"
    logs = {
        "edge-gateway": [
            LogEntry(
                timestamp="2026-04-08T12:26:19Z",
                service="edge-gateway",
                level="WARN",
                message=f"retrying upstream payments-api on {noisy_node}; connection resets observed",
                trace_id=trace_id,
            )
        ],
        "checkout-service": [
            LogEntry(
                timestamp="2026-04-08T12:27:14Z",
                service="checkout-service",
                level="ERROR",
                message="payment authorization failed after endpoint rotated twice in 900ms",
                trace_id=trace_id,
            )
        ],
        "payments-api": [
            LogEntry(
                timestamp="2026-04-08T12:27:11Z",
                service="payments-api",
                level="ERROR",
                message="dial tcp connection refused after resolver update",
                trace_id=trace_id,
            ),
            LogEntry(
                timestamp="2026-04-08T12:27:12Z",
                service="payments-api",
                level="WARN",
                message=f"endpoint cache churn detected; {root_service} target changed 14 times in 60s",
                trace_id=trace_id,
            ),
        ],
        root_service: [
            LogEntry(
                timestamp="2026-04-08T12:25:58Z",
                service=root_service,
                level="ERROR",
                message=f"applied {rollout} with malformed endpoint weights; stale endpoints published to clients",
            ),
            LogEntry(
                timestamp="2026-04-08T12:26:02Z",
                service=root_service,
                level="WARN",
                message="cache invalidation lag 48s across regional watchers",
            ),
        ],
        "feature-flags": [
            LogEntry(
                timestamp="2026-04-08T12:26:08Z",
                service="feature-flags",
                level="INFO",
                message="payments_retry_enabled toggled true for 5% canary",
            )
        ],
        "metrics-pipeline": [
            LogEntry(
                timestamp="2026-04-08T12:27:30Z",
                service="metrics-pipeline",
                level="WARN",
                message="late datapoints in eu-central due to ingestion backlog",
            )
        ],
    }
    metadata = {
        "edge-gateway": ServiceMetadata(
            service="edge-gateway",
            tier="edge",
            owner="traffic-platform",
            dependencies=["checkout-service", "payments-api"],
            runbook="rb://edge-gateway/retry-amplification",
        ),
        "checkout-service": ServiceMetadata(
            service="checkout-service",
            tier="backend",
            owner="commerce-core",
            dependencies=["payments-api"],
            runbook="rb://checkout-service/payment-failures",
        ),
        "payments-api": ServiceMetadata(
            service="payments-api",
            tier="backend",
            owner="payments",
            dependencies=[root_service, "feature-flags"],
            runbook="rb://payments-api/endpoint-churn",
        ),
        root_service: ServiceMetadata(
            service=root_service,
            tier="platform",
            owner="platform-runtime",
            dependencies=[],
            runbook=runbook,
        ),
        "feature-flags": ServiceMetadata(
            service="feature-flags",
            tier="platform",
            owner="experimentation",
            dependencies=[],
            runbook="rb://feature-flags/canary",
        ),
        "metrics-pipeline": ServiceMetadata(
            service="metrics-pipeline",
            tier="platform",
            owner="observability",
            dependencies=[],
            runbook="rb://metrics-pipeline/delay",
        ),
    }
    timeline = [
        f"12:25 UTC platform-runtime deploys {rollout} to {root_service}",
        "12:26 UTC gateway CPU warning appears because retries begin",
        "12:27 UTC payment auth failures spike across regions",
    ]

    return IncidentScenario(
        incident_id=incident_id,
        difficulty="hard",
        split=split,
        title=title,
        summary=summary,
        step_limit=14,
        available_services=services,
        business_impact=BusinessImpact(
            impacted_users_pct=57.0,
            revenue_risk_per_min_usd=9100,
            error_budget_remaining_pct=9.0,
            notes="Critical payment path failure with immediate business impact and low budget remaining.",
        ),
        hidden_truth=HiddenTruth(
            root_cause_service=root_service,
            root_cause_category="bad_config_rollout",
            severity="critical",
            affected_services=[root_service, "payments-api", "checkout-service", "edge-gateway"],
            mitigation_keywords=["rollback", root_service, "config", "flush", "cache"],
            preferred_mitigation_plan="rollback_config",
            risky_mitigation_plans=["restart_service", "disable_feature_flag", "drain_traffic"],
            required_runbooks=[runbook, "rb://payments-api/endpoint-churn"],
            postmortem_keywords=[root_service, "trace", "rollback", "cache", "prevention", "error budget"],
            business_impact_label="payment_authorization_outage",
            required_trace_id=trace_id,
        ),
        evidence=ScenarioEvidence(
            alerts=[
                AlertEvent(
                    alert_id=f"ALERT-{incident_id}-1",
                    service="edge-gateway",
                    title="Gateway CPU above 85%",
                    severity="warn",
                    summary=f"Node {noisy_node} CPU high because of request retry amplification.",
                    fired_at="2026-04-08T12:26:00Z",
                ),
                AlertEvent(
                    alert_id=f"ALERT-{incident_id}-2",
                    service="payments-api",
                    title="Payment auth failure rate critical",
                    severity="critical",
                    summary="Payment authorization failures hit 32% across 3 regions.",
                    fired_at="2026-04-08T12:27:00Z",
                ),
            ],
            logs=logs,
            traces={
                trace_id: TraceSnippet(
                    trace_id=trace_id,
                    root_service="edge-gateway",
                    summary=f"Trace proves first failing dependency update is from {root_service}, not gateway CPU.",
                    spans=[
                        TraceSpan(
                            span_id="1",
                            service="edge-gateway",
                            operation="POST /checkout/pay",
                            status="error",
                            duration_ms=3860,
                            summary="Gateway retries payments-api because of connection resets",
                        ),
                        TraceSpan(
                            span_id="2",
                            service="checkout-service",
                            operation="authorize_payment",
                            status="error",
                            duration_ms=3781,
                            summary="Checkout forwards to payments-api and retries",
                        ),
                        TraceSpan(
                            span_id="3",
                            service="payments-api",
                            operation="resolve_endpoint",
                            status="error",
                            duration_ms=142,
                            summary=f"Resolver returned stale endpoint from {root_service}",
                        ),
                        TraceSpan(
                            span_id="4",
                            service=root_service,
                            operation="watch_config",
                            status="error",
                            duration_ms=41,
                            summary="Bad rollout published malformed endpoint weights",
                        ),
                    ],
                )
            },
            service_metadata=metadata,
            timeline=timeline,
            relevant_log_services=["payments-api", root_service, "checkout-service"],
            relevant_metadata_services=["payments-api", root_service],
            relevant_trace_ids=[trace_id],
            relevant_hints={
                f"inspect_trace:{trace_id}": "Hard incidents require trace proof to isolate root cause from noisy symptoms.",
                "execute_mitigation": "Rollback config and flush stale endpoint caches; avoid broad traffic drains.",
            },
            noisy_log_services=["metrics-pipeline", "feature-flags", "edge-gateway"],
        ),
    )
