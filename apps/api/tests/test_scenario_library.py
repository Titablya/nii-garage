from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.engine import DirectiveKind, OpponentDirective, ReasonCode
from app.llm.prompting import build_opponent_prompt
from app.models import ScenarioDraftRequest
from app.repository import InMemorySessionRepository
from app.scenario_catalog import load_scenario_catalog
from app.scenario_drafts import compile_draft, simulate_boundaries


def _register(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Конструктор", "password": "Strong-pass-42"},
    )
    assert response.status_code == 201
    return response.json()["csrf_token"]


def _draft(series_id: str | None = None) -> dict:
    payload = {
        "template_id": "random-co-marketing",
        "title": "Партнёрский запуск образовательного продукта",
        "situation": "Две компании готовят совместный запуск и должны согласовать вклад, срок, продвижение, поддержку и распределение результата.",
        "participant_role": "Директор продукта",
        "opponent_role": "Директор партнёрской сети",
        "objective": "Согласовать измеримый и исполнимый пакет взаимных обязательств.",
        "industry": "Образование",
        "theme": "Партнёрство",
        "difficulty": "medium",
        "tone": "businesslike",
        "estimated_minutes": 18,
        "max_turns": 14,
        "stakes_level": "high",
    }
    if series_id:
        payload["series_id"] = series_id
    return payload


def test_catalog_contains_thirty_validated_cases_and_all_required_themes() -> None:
    catalog = load_scenario_catalog()
    curated = [item for item in catalog.list() if item.source == "curated"]
    assert len(curated) >= 30
    assert {
        "Закупки", "Продажи", "Зарплата", "Найм", "Конфликт",
        "Партнёрство", "Сроки", "Бюджет", "Внутренние ресурсы",
    } <= {item.theme for item in curated}
    for scenario in curated:
        definition = catalog.get_definition(scenario.id)
        assert definition is not None
        result = simulate_boundaries(definition)
        assert result.valid is True
        assert result.checked_issues == len(definition.issues)
        assert result.hidden_fields_exposed is False


def test_catalog_filters_and_public_projection_do_not_leak_hidden_economics() -> None:
    app = create_app(InMemorySessionRepository(), scenario_catalog=load_scenario_catalog())
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/scenario-catalog",
            params={"industry": "Промышленность", "difficulty": "advanced", "max_minutes": 30},
        )
        assert response.status_code == 200
        assert response.json()
        serialized = json.dumps(response.json(), ensure_ascii=False).casefold()
        for forbidden in ("batna", "reservation", "hidden_interests", "party_ranges", '"zopa"'):
            assert forbidden not in serialized


def test_versioned_draft_is_owned_validated_and_can_start_a_session() -> None:
    app = create_app(InMemorySessionRepository(), scenario_catalog=load_scenario_catalog())
    owner = TestClient(app)
    outsider = TestClient(app)
    with owner, outsider:
        owner_csrf = _register(owner, "builder-owner@example.test")
        outsider_csrf = _register(outsider, "builder-outsider@example.test")

        first = owner.post(
            "/api/v1/me/scenario-drafts",
            json=_draft(),
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert first.status_code == 201
        created = first.json()
        assert created["version"] == 1
        assert created["validation"]["valid"] is True
        assert created["scenario"]["source"] == "custom"

        second = owner.post(
            "/api/v1/me/scenario-drafts",
            json=_draft(created["series_id"]),
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert second.status_code == 201
        assert second.json()["version"] == 2
        assert second.json()["scenario"]["id"] != created["scenario"]["id"]
        assert len(owner.get("/api/v1/me/scenario-drafts").json()["drafts"]) == 2

        scenario_id = second.json()["scenario"]["id"]
        assert outsider.get(f"/api/v1/scenarios/{scenario_id}").status_code == 404
        assert outsider.post(
            "/api/v1/sessions",
            json={"scenario_id": scenario_id},
            headers={"X-CSRF-Token": outsider_csrf},
        ).status_code == 404
        assert owner.get(f"/api/v1/scenarios/{scenario_id}").status_code == 200
        assert owner.post(
            "/api/v1/sessions",
            json={"scenario_id": scenario_id},
            headers={"X-CSRF-Token": owner_csrf},
        ).status_code == 201

        leaked = _draft()
        leaked["opponent_batna"] = "скрытая альтернатива"
        assert owner.post(
            "/api/v1/me/scenario-drafts",
            json=leaked,
            headers={"X-CSRF-Token": owner_csrf},
        ).status_code == 422


def test_public_text_assistant_never_requires_or_returns_hidden_economics() -> None:
    app = create_app(InMemorySessionRepository(), scenario_catalog=load_scenario_catalog())
    with TestClient(app) as client:
        csrf = _register(client, "builder-ai@example.test")
        response = client.post(
            "/api/v1/me/scenario-drafts/suggest",
            json={
                "title": "Запуск пилота",
                "situation": "Стороны обсуждают совместный пилот и должны уточнить измеримые условия запуска.",
                "participant_role": "Руководитель продукта",
                "opponent_role": "Операционный директор",
                "objective": "Согласовать реалистичный план запуска пилота.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert set(response.json()) == {"title", "situation", "objective", "provider", "fallback"}
        assert "batna" not in json.dumps(response.json()).casefold()


def test_custom_case_opponent_prompt_contains_only_public_projection() -> None:
    catalog = load_scenario_catalog()
    _, definition, _ = compile_draft(
        catalog,
        ScenarioDraftRequest.model_validate(_draft()),
        uuid4(),
        1,
    )
    prompt = build_opponent_prompt(
        definition.public_briefing,
        [],
        OpponentDirective(
            kind=DirectiveKind.CLARIFY,
            template_key="opponent.clarify",
            public_facts=("Уточните приоритеты сторон.",),
            reason_codes=(ReasonCode.TURN_PROCESSED,),
        ),
    ).casefold()
    for forbidden in ("batna", "reservation", "hidden_", "party_ranges", "engine_state"):
        assert forbidden not in prompt
