from src.env import SREIncidentTriageEnv


def test_reset_is_deterministic_for_same_seed() -> None:
    env_a = SREIncidentTriageEnv()
    env_b = SREIncidentTriageEnv()

    result_a = env_a.reset(difficulty="medium", seed=7)
    result_b = env_b.reset(difficulty="medium", seed=7)

    assert result_a.observation.incident_id == result_b.observation.incident_id
    assert result_a.observation.model_dump() == result_b.observation.model_dump()


def test_easy_happy_path_closes_with_score() -> None:
    env = SREIncidentTriageEnv()
    env.reset(difficulty="easy", seed=11, split="public")
    env.step({"action_type": "inspect_alerts"})
    env.step({"action_type": "inspect_logs", "service_name": "auth-service", "limit": 5})
    env.step({"action_type": "inspect_service_metadata", "service_name": "auth-service"})
    env.step({"action_type": "classify_severity", "severity": "major"})
    env.step(
        {
            "action_type": "identify_root_cause",
            "service_name": "auth-service",
            "cause_category": "db_pool_exhaustion",
            "reason": "auth-service logs show connection pool exhaustion",
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
    env.step(
        {
            "action_type": "execute_mitigation",
            "plan": "scale_capacity",
            "justification": "preserves error budget and reduces pool exhaustion safely",
        }
    )
    result = env.step(
        {
            "action_type": "close_incident",
            "summary": "Affected services: auth-service, edge-gateway. Restart auth-service and increase db pool capacity.",
        }
    )

    assert result.done is True
    assert 0.0 <= result.info["score"] <= 1.0
    assert result.info["score"] >= 0.8


def test_repeated_irrelevant_actions_reduce_reward() -> None:
    env = SREIncidentTriageEnv()
    env.reset(difficulty="hard", seed=2, split="public")

    first = env.step({"action_type": "inspect_logs", "service_name": "metrics-pipeline", "limit": 5})
    second = env.step({"action_type": "inspect_logs", "service_name": "metrics-pipeline", "limit": 5})

    assert first.reward < 0
    assert second.reward < first.reward


def test_destructive_execution_penalized() -> None:
    env = SREIncidentTriageEnv()
    env.reset(difficulty="hard", seed=33, split="public")
    env.step({"action_type": "inspect_alerts"})
    result = env.step(
        {
            "action_type": "execute_mitigation",
            "plan": "restart_service",
            "justification": "attempting fast recovery",
        }
    )
    assert result.reward < 0
