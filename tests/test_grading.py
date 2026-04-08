from src.env import SREIncidentTriageEnv
from src.grading import grade_easy, grade_hard, grade_medium
from src.scenarios import build_scenario


def _run_good_episode(difficulty: str, seed: int) -> SREIncidentTriageEnv:
    env = SREIncidentTriageEnv()
    env.reset(difficulty=difficulty, seed=seed, split="public")
    env.step({"action_type": "inspect_alerts"})
    env.step({"action_type": "inspect_timeline"})
    if difficulty == "easy":
        env.step({"action_type": "inspect_logs", "service_name": "auth-service", "limit": 5})
        env.step({"action_type": "inspect_service_metadata", "service_name": "auth-service"})
        env.step({"action_type": "classify_severity", "severity": "major"})
        env.step(
            {
                "action_type": "identify_root_cause",
                "service_name": "auth-service",
                "cause_category": "db_pool_exhaustion",
                "reason": "Pool exhaustion is visible in auth-service logs",
                "runbook_id": "rb://auth-service/db-pool",
            }
        )
        env.step(
            {
                "action_type": "recommend_mitigation",
                "action": "scale capacity for auth-service connection pools and throttle retry pressure",
                "runbook_id": "rb://auth-service/db-pool",
            }
        )
        env.step({"action_type": "execute_mitigation", "plan": "scale_capacity", "justification": "safest fix"})
        env.step(
            {
                "action_type": "close_incident",
                "summary": "Affected services: auth-service, edge-gateway. restart auth-service and increase db pool capacity.",
            }
        )
    elif difficulty == "medium":
        env.step({"action_type": "inspect_logs", "service_name": "inventory-db", "limit": 5})
        env.step({"action_type": "inspect_logs", "service_name": "inventory-service", "limit": 5})
        env.step({"action_type": "inspect_service_metadata", "service_name": "inventory-db"})
        env.step({"action_type": "classify_severity", "severity": "major"})
        env.step(
            {
                "action_type": "identify_root_cause",
                "service_name": "inventory-db",
                "cause_category": "connection_saturation",
                "reason": "inventory-db is rejecting new clients and causing downstream timeouts",
                "runbook_id": "rb://inventory-db/max-connections",
            }
        )
        env.step(
            {
                "action_type": "recommend_mitigation",
                "action": "scale inventory-db connection capacity and throttle reservation traffic",
                "runbook_id": "rb://inventory-db/max-connections",
            }
        )
        env.step({"action_type": "execute_mitigation", "plan": "scale_capacity", "justification": "reduce queue pressure"})
        env.step(
            {
                "action_type": "close_incident",
                "summary": "Affected services: inventory-db, inventory-service, checkout-service, frontend-api.",
            }
        )
    else:
        env.step({"action_type": "inspect_logs", "service_name": "payments-api", "limit": 5})
        env.step({"action_type": "inspect_logs", "service_name": "service-discovery", "limit": 5})
        env.step({"action_type": "inspect_trace", "trace_id": "hard-public-trace-3"})
        env.step({"action_type": "inspect_service_metadata", "service_name": "service-discovery"})
        env.step({"action_type": "classify_severity", "severity": "critical"})
        env.step(
            {
                "action_type": "identify_root_cause",
                "service_name": "service-discovery",
                "cause_category": "bad_config_rollout",
                "reason": "service-discovery published stale endpoints after a bad rollout",
                "runbook_id": "rb://service-discovery/config-rollbacks",
            }
        )
        env.step(
            {
                "action_type": "recommend_mitigation",
                "action": "rollback the service-discovery config rollout and flush stale endpoint caches",
                "runbook_id": "rb://service-discovery/config-rollbacks",
            }
        )
        env.step({"action_type": "execute_mitigation", "plan": "rollback_config", "justification": "fixes root safely"})
        env.step(
            {
                "action_type": "submit_postmortem",
                "timeline_summary": "Timeline UTC with trace evidence and mitigation rollout.",
                "root_cause": "service-discovery bad config rollout caused stale endpoints.",
                "corrective_action": "rollback_config restored stable endpoint map.",
                "prevention_action": "add rollout guardrail and canary validation to protect error budget.",
                "runbook_ids": ["rb://service-discovery/config-rollbacks", "rb://payments-api/endpoint-churn"],
            }
        )
        env.step(
            {
                "action_type": "close_incident",
                "summary": "Affected services: service-discovery, payments-api, checkout-service, edge-gateway.",
            }
        )
    return env


def test_graders_return_normalized_scores() -> None:
    easy_env = _run_good_episode("easy", 11)
    medium_env = _run_good_episode("medium", 22)
    hard_env = _run_good_episode("hard", 33)

    easy_score = grade_easy(easy_env.state(), build_scenario("easy", 11))
    medium_score = grade_medium(medium_env.state(), build_scenario("medium", 22))
    hard_score = grade_hard(hard_env.state(), build_scenario("hard", 33))

    assert 0.0 <= easy_score <= 1.0
    assert 0.0 <= medium_score <= 1.0
    assert 0.0 <= hard_score <= 1.0
    assert hard_score >= 0.8


def test_hard_trace_is_required_for_full_score() -> None:
    env = SREIncidentTriageEnv()
    env.reset(difficulty="hard", seed=33, split="public")
    env.step({"action_type": "inspect_alerts"})
    env.step({"action_type": "classify_severity", "severity": "critical"})
    env.step(
        {
            "action_type": "identify_root_cause",
            "service_name": "service-discovery",
            "cause_category": "bad_config_rollout",
            "reason": "service-discovery is the likely root cause",
            "runbook_id": "rb://service-discovery/config-rollbacks",
        }
    )
    env.step(
        {
            "action_type": "recommend_mitigation",
            "action": "rollback the service-discovery config rollout and flush stale endpoint caches",
            "runbook_id": "rb://service-discovery/config-rollbacks",
        }
    )
    env.step({"action_type": "execute_mitigation", "plan": "rollback_config", "justification": "best plan"})
    env.step({"action_type": "close_incident", "summary": "Affected services: service-discovery, payments-api."})

    score = grade_hard(env.state(), build_scenario("hard", 33, "public"))
    assert score < 1.0
