from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import InMemorySessionRepository
from app.scenario_catalog import get_scenario_catalog
from app.services import build_report, complete_session, create_session, retry_session


def client() -> TestClient:
    return TestClient(create_app(InMemorySessionRepository()))


def test_retry_requires_completed_source_and_preserves_version_lineage() -> None:
    api = client()
    first = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()

    assert api.post(f"/api/v1/sessions/{first['id']}/retry").status_code == 409
    assert api.post("/api/v1/sessions/00000000-0000-0000-0000-000000000000/retry").status_code == 404

    api.post(f"/api/v1/sessions/{first['id']}/complete")
    retry = api.post(f"/api/v1/sessions/{first['id']}/retry")

    assert retry.status_code == 201
    second = retry.json()
    assert second["series_id"] == first["series_id"]
    assert second["previous_session_id"] == first["id"]
    assert second["attempt_number"] == 2
    assert second["scenario_version_id"] == first["scenario_version_id"]
    assert second["status"] == "active"
    assert second["messages"] == []


def test_completed_retry_produces_deterministic_comparison() -> None:
    api = client()
    first = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()
    api.post(f"/api/v1/sessions/{first['id']}/complete")
    first_report = api.get(f"/api/v1/sessions/{first['id']}/report").json()
    second = api.post(f"/api/v1/sessions/{first['id']}/retry").json()

    assert api.get(f"/api/v1/sessions/{second['id']}/comparison").status_code == 409
    message = (
        "Какие ограничения для вас критичны? Предлагаю опереться на рыночный диапазон "
        "и обсудить пакет: 9,9 млн, 42 дня, 45% предоплаты, гарантия 24 месяца и штраф 0,25%."
    )
    assert api.post(
        f"/api/v1/sessions/{second['id']}/messages", json={"content": message}
    ).status_code == 200
    api.post(f"/api/v1/sessions/{second['id']}/complete")
    second_report = api.get(f"/api/v1/sessions/{second['id']}/report").json()

    response = api.get(f"/api/v1/sessions/{second['id']}/comparison")

    assert response.status_code == 200
    comparison = response.json()
    assert comparison["previous"]["session_id"] == first["id"]
    assert comparison["current"]["session_id"] == second["id"]
    assert comparison["score_delta"] == second_report["score"] - first_report["score"]
    assert comparison["previous"]["attempt_number"] == 1
    assert comparison["current"]["attempt_number"] == 2
    assert len(comparison["block_deltas"]) == 5
    assert len(comparison["task_deltas"]) == len(second_report["task_checks"])
    assert comparison["current"]["tasks_met"] == sum(
        item["status"] == "met" for item in second_report["task_checks"]
    )
    rendered = json.dumps(comparison, ensure_ascii=False).casefold()
    assert not any(token in rendered for token in (
        "engine_state", "hidden_interests", "reservation_points", "concession_budget"
    ))


def test_retry_does_not_mutate_completed_attempt_and_numbers_continue() -> None:
    api = client()
    first = api.post("/api/v1/sessions", json={"scenario_id": "project-resources"}).json()
    api.post(
        f"/api/v1/sessions/{first['id']}/messages",
        json={"content": "Какие приоритеты и ограничения для вас наиболее важны?"},
    )
    api.post(f"/api/v1/sessions/{first['id']}/complete")
    frozen = api.get(f"/api/v1/sessions/{first['id']}").json()
    second = api.post(f"/api/v1/sessions/{first['id']}/retry").json()
    api.post(f"/api/v1/sessions/{second['id']}/complete")
    third = api.post(f"/api/v1/sessions/{second['id']}/retry").json()

    assert api.get(f"/api/v1/sessions/{first['id']}").json() == frozen
    assert third["attempt_number"] == 3
    assert third["previous_session_id"] == second["id"]
    assert third["series_id"] == first["series_id"]


def test_mixed_evaluator_versions_require_explicit_historical_view() -> None:
    catalog = get_scenario_catalog()
    repository = InMemorySessionRepository()
    first = create_session(repository, catalog, "equipment-supply")
    first = complete_session(repository, first.id)
    historical_report = build_report(catalog, first).model_copy(
        update={"evaluator_version": "0.9"}
    )
    repository.save_report(historical_report)
    assert repository.save_report(build_report(catalog, first)) == historical_report
    returned = repository.get_report(first.id)
    assert returned is not None
    returned.evaluator_version = "discarded_local_edit"
    assert repository.get_report(first.id) == historical_report
    second = retry_session(repository, catalog, first.id)
    second = complete_session(repository, second.id)
    current_report = repository.save_report(build_report(catalog, second))
    api = TestClient(create_app(repository, catalog))

    assert api.get(f"/api/v1/sessions/{first.id}/report").json()["evaluator_version"] == "0.9"
    assert api.post(f"/api/v1/sessions/{first.id}/complete").status_code == 200
    assert repository.get_report(first.id) == historical_report

    ordinary = api.get(f"/api/v1/sessions/{second.id}/comparison")
    assert ordinary.status_code == 409
    assert ordinary.json()["detail"] == "evaluator_version_mismatch"

    historical = api.get(f"/api/v1/sessions/{second.id}/comparison/historical")
    assert historical.status_code == 200
    payload = historical.json()
    assert payload["versions_match"] is False
    assert payload["previous"]["evaluator_version"] == "0.9"
    assert payload["current"]["evaluator_version"] == current_report.evaluator_version
    assert payload["previous"]["score"] == historical_report.score
    assert "score_delta" not in payload
    assert "block_deltas" not in payload
    assert repository.get_report(first.id) == historical_report

    coaching = api.get(f"/api/v1/sessions/{second.id}/coach/summary")
    assert coaching.status_code == 200
    assert coaching.json()["previous_skill_score"] is None
    assert coaching.json()["skill_delta"] is None


def test_historical_report_is_never_implicitly_rebuilt() -> None:
    catalog = get_scenario_catalog()
    repository = InMemorySessionRepository()
    first = create_session(repository, catalog, "equipment-supply")
    first = complete_session(repository, first.id)
    second = retry_session(repository, catalog, first.id)
    second = complete_session(repository, second.id)
    repository.save_report(build_report(catalog, second))
    api = TestClient(create_app(repository, catalog))

    assert api.get(f"/api/v1/sessions/{first.id}/report").status_code == 409
    assert api.get(f"/api/v1/sessions/{second.id}/comparison").status_code == 409
    assert api.get(f"/api/v1/sessions/{second.id}/comparison/historical").status_code == 409
    assert api.post(f"/api/v1/sessions/{first.id}/complete").status_code == 200
    assert repository.get_report(first.id) is None
