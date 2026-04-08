from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.server import app


ROOT = Path(__file__).resolve().parents[1]


def test_openenv_manifest_has_required_fields() -> None:
    manifest = yaml.safe_load((ROOT / "openenv.yaml").read_text())
    assert manifest["spec_version"] == 1
    assert manifest["runtime"] == "fastapi"
    assert manifest["app"] == "src.server:app"
    assert manifest["port"] == 7860


def test_server_supports_reset_step_and_state() -> None:
    client = TestClient(app)

    reset = client.post("/reset?difficulty=easy&seed=3")
    assert reset.status_code == 200
    assert reset.json()["observation"]["incident_id"] == "inc-public-easy-003"

    step = client.post("/step", json={"action_type": "inspect_alerts"})
    assert step.status_code == 200
    assert step.json()["observation"]["visible_alerts"]

    state = client.get("/state")
    assert state.status_code == 200
    assert state.json()["hidden_truth"]["root_cause_service"] == "auth-service"
