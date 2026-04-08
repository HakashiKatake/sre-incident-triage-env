from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from src.grading import grade_easy, grade_episode, grade_hard, grade_medium
from src.models import Difficulty, IncidentState, ScenarioSplit
from src.scenarios import build_scenario, evaluation_suite


class TaskDefinition(BaseModel):
    task_id: str
    difficulty: Difficulty
    split: ScenarioSplit
    seed: int
    title: str
    description: str
    grader_name: str


TASK_DEFINITIONS: dict[tuple[Difficulty, ScenarioSplit], TaskDefinition] = {
    ("easy", "public"): TaskDefinition(
        task_id="sre_easy_single_service_public",
        difficulty="easy",
        split="public",
        seed=11,
        title="Single Service Login Outage (Public)",
        description="Identify auth-service DB pool exhaustion and execute a safe mitigation.",
        grader_name="grade_easy",
    ),
    ("medium", "public"): TaskDefinition(
        task_id="sre_medium_cascading_public",
        difficulty="medium",
        split="public",
        seed=22,
        title="Cascading Checkout Failure (Public)",
        description="Find inventory-db as primary root cause and avoid high-blast mitigation.",
        grader_name="grade_medium",
    ),
    ("hard", "public"): TaskDefinition(
        task_id="sre_hard_distributed_public",
        difficulty="hard",
        split="public",
        seed=33,
        title="Distributed Config Failure (Public)",
        description="Use traces to isolate service-discovery bad rollout and submit postmortem.",
        grader_name="grade_hard",
    ),
    ("easy", "holdout"): TaskDefinition(
        task_id="sre_easy_single_service_holdout",
        difficulty="easy",
        split="holdout",
        seed=111,
        title="Single Service Session Outage (Holdout)",
        description="Generalize diagnosis to unseen service names and cache pool failure.",
        grader_name="grade_easy",
    ),
    ("medium", "holdout"): TaskDefinition(
        task_id="sre_medium_cascading_holdout",
        difficulty="medium",
        split="holdout",
        seed=122,
        title="Cascading Pricing Failure (Holdout)",
        description="Generalize root-cause analysis to pricing path without overfitting to public labels.",
        grader_name="grade_medium",
    ),
    ("hard", "holdout"): TaskDefinition(
        task_id="sre_hard_distributed_holdout",
        difficulty="hard",
        split="holdout",
        seed=133,
        title="Distributed Config Distributor Failure (Holdout)",
        description="Generalize trace-led triage with noisy telemetry and strict policy constraints.",
        grader_name="grade_hard",
    ),
}


TASK_GRADERS: dict[Difficulty, Callable[[IncidentState, Difficulty, ScenarioSplit, int], float]] = {
    "easy": lambda state, difficulty, split, seed: grade_easy(state, build_scenario(difficulty, seed, split)),
    "medium": lambda state, difficulty, split, seed: grade_medium(state, build_scenario(difficulty, seed, split)),
    "hard": lambda state, difficulty, split, seed: grade_hard(state, build_scenario(difficulty, seed, split)),
}


def get_task_definition(difficulty: Difficulty, split: ScenarioSplit) -> TaskDefinition:
    return TASK_DEFINITIONS[(difficulty, split)]


def grade_task(difficulty: Difficulty, split: ScenarioSplit, state: IncidentState, seed: int) -> dict[str, Any]:
    scenario = build_scenario(difficulty, seed, split)
    score = TASK_GRADERS[difficulty](state, difficulty, split, seed)
    details = grade_episode(scenario, state)
    details["final"] = score
    details["difficulty"] = difficulty
    details["split"] = split
    return details


def list_eval_tasks() -> list[TaskDefinition]:
    definitions: list[TaskDefinition] = []
    for _, difficulty, split, seed in evaluation_suite():
        definitions.append(get_task_definition(difficulty, split).model_copy(update={"seed": seed}))
    return definitions

