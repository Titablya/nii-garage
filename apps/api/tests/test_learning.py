from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import InMemorySessionRepository


PASSWORD = "Strong-pass-42"


def _register(client: TestClient) -> tuple[str, UUID]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "learner@example.test", "display_name": "Ученик", "password": PASSWORD},
    )
    assert response.status_code == 201
    payload = response.json()
    return payload["csrf_token"], UUID(payload["account"]["id"])


def _complete_attempt(client: TestClient, csrf: str, messages: list[str]) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={"scenario_id": "equipment-supply"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    session_id = created.json()["id"]
    for content in messages:
        sent = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": content},
            headers={"X-CSRF-Token": csrf},
        )
        assert sent.status_code == 200
    completed = client.post(
        f"/api/v1/sessions/{session_id}/complete",
        headers={"X-CSRF-Token": csrf},
    )
    assert completed.status_code == 200
    assert client.get(f"/api/v1/sessions/{session_id}/report").status_code == 200
    return session_id


def test_learning_goal_drill_and_new_attempt_update_skill() -> None:
    app = create_app(InMemorySessionRepository())
    client = TestClient(app)
    csrf, _ = _register(client)

    empty = client.get("/api/v1/me/learning")
    assert empty.status_code == 200
    assert empty.json()["rubric_version"] is None
    assert len(empty.json()["skill_map"]) == 8
    assert empty.json()["recommendation"]["skill_id"] == "interests"

    assert client.post(
        "/api/v1/me/learning-goal",
        json={"skill_id": "meso", "target_score": 80, "weekly_sessions": 3},
    ).status_code == 403
    goal = client.post(
        "/api/v1/me/learning-goal",
        json={"skill_id": "meso", "target_score": 80, "weekly_sessions": 3},
        headers={"X-CSRF-Token": csrf},
    )
    assert goal.status_code == 200
    assert goal.json()["goal"]["skill_id"] == "meso"
    assert goal.json()["recommendation"]["skill_id"] == "meso"

    drill = client.post(
        "/api/v1/me/drills/meso.micro-v1/complete",
        json={"self_rating": 4},
        headers={"X-CSRF-Token": csrf},
    )
    assert drill.status_code == 200
    meso_before = next(item for item in drill.json()["skill_map"] if item["id"] == "meso")
    assert meso_before["due"] is False
    assert meso_before["next_due_at"] is not None

    _complete_attempt(client, csrf, ["Предлагаю обсудить возможный срок поставки."])
    first = client.get("/api/v1/me/learning").json()
    questions_first = next(item for item in first["skill_map"] if item["id"] == "questions")
    assert questions_first["score"] == 0

    _complete_attempt(
        client,
        csrf,
        [
            "Что для вас важнее всего в сроках поставки?",
            "Какие ограничения мешают выбрать более раннюю дату?",
        ],
    )
    second = client.get("/api/v1/me/learning").json()
    questions_second = next(item for item in second["skill_map"] if item["id"] == "questions")
    assert questions_second["score"] > questions_first["score"]
    assert questions_second["delta"] > 0
    assert second["rubric_version"] == "0.1"
    assert second["comparable_sessions"] == 2
    assert second["weekly_progress"][0]["attempts"] == 2
    assert second["scenario_progress"][0]["scenario_id"] == "equipment-supply"


@pytest.mark.parametrize("version_field", ["rubric_version", "evaluator_version"])
def test_learning_history_excludes_incompatible_scoring_versions(version_field: str) -> None:
    repository = InMemorySessionRepository()
    app = create_app(repository)
    client = TestClient(app)
    csrf, _ = _register(client)

    first_id = _complete_attempt(client, csrf, ["Что для вас важно в этом предложении?"])
    second_id = _complete_attempt(client, csrf, ["Предлагаю обсудить условия."])
    first_report = repository.get_report(UUID(first_id))
    second_session = repository.get(UUID(second_id))
    assert first_report is not None and second_session is not None
    second_session.completed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    repository.save(second_session)
    changes = {"session_id": UUID(second_id), version_field: "9.9"}
    if version_field == "rubric_version":
        changes["methodology"] = first_report.methodology.model_copy(
            update={"rubric_version": "9.9"}
        )
    repository._reports[UUID(second_id)] = first_report.model_copy(update=changes)

    dashboard = client.get("/api/v1/me/learning")
    assert dashboard.status_code == 200
    assert dashboard.json()[version_field] == "9.9"
    assert dashboard.json()["comparable_sessions"] == 1
    assert dashboard.json()["excluded_incompatible_sessions"] == 1
