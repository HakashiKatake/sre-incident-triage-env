from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
from pydantic import TypeAdapter

from src.env import SREIncidentTriageEnv
from src.models import IncidentAction, IncidentState, StepResult


app = FastAPI(title="SRE Incident Triage Env", version="0.1.0")
env = SREIncidentTriageEnv()
ACTION_ADAPTER = TypeAdapter(IncidentAction)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "SRE Incident Triage Env",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/web")
def web() -> dict[str, str]:
    return {
        "name": "SRE Incident Triage Env",
        "status": "ok",
        "message": "Web UI not required for benchmark endpoints. Use /docs or API routes.",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reset", response_model=StepResult)
def reset(
    difficulty: str = Query(default="easy", pattern="^(easy|medium|hard)$"),
    seed: int = Query(default=0, ge=0),
    split: str = Query(default="public", pattern="^(public|holdout)$"),
) -> StepResult:
    return env.reset(difficulty=difficulty, seed=seed, split=split)


@app.post("/step", response_model=StepResult)
def step(action: dict[str, Any]) -> StepResult:
    parsed = ACTION_ADAPTER.validate_python(action)
    return env.step(parsed)


@app.get("/state", response_model=IncidentState)
def state() -> IncidentState:
    return env.state()
