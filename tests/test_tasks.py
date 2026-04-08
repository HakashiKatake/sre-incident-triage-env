from src.env import SREIncidentTriageEnv
from src.tasks import TASK_DEFINITIONS, grade_task


def test_three_tasks_are_defined() -> None:
    assert len(TASK_DEFINITIONS) >= 3


def test_task_graders_return_normalized_scores() -> None:
    env = SREIncidentTriageEnv()
    for difficulty, split, seed in [("easy", "public", 11), ("medium", "public", 22), ("hard", "holdout", 133)]:
        env.reset(difficulty=difficulty, seed=seed, split=split)
        env.step({"action_type": "inspect_alerts"})
        env.step({"action_type": "inspect_timeline"})
        env.step({"action_type": "close_incident", "summary": "premature close"})
        graded = grade_task(difficulty, split, env.state(), seed)
        assert 0.0 <= graded["final"] <= 1.0
