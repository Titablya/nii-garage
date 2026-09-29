from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.llm import GenerationRequest, GenerationResponse, LLMProvider
from app.models import SessionConfiguration, SessionDifficulty, SessionTone
from app.repository import InMemorySessionRepository
from app.scenario_catalog import get_scenario_catalog
from app.services import materialize_session_definition


class RecordingProvider(LLMProvider):
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return GenerationResponse(reply="Какие условия для вас наиболее важны?")


def test_configuration_is_trimmed_strict_and_rejects_extra_fields() -> None:
    configuration = SessionConfiguration(
        topic="  Новая тема  ",
        context="  Контекст пользовательской тренировки достаточно длинный.  ",
        participant_role="  Покупатель  ",
        opponent_role="  Поставщик  ",
        objective="  Согласовать рабочий пакет  ",
        difficulty="hard",
        tone="firm",
        max_turns=6,
    )

    assert configuration.topic == "Новая тема"
    assert configuration.context.startswith("Контекст")
    assert configuration.difficulty is SessionDifficulty.HARD
    assert configuration.tone is SessionTone.FIRM

    with pytest.raises(ValidationError):
        SessionConfiguration(
            topic="Тема",
            context="Достаточно длинный контекст тренировки.",
            participant_role="Покупатель",
            opponent_role="Поставщик",
            objective="Согласовать условия",
            max_turns=10,
            unexpected="forbidden",
        )


def test_session_configuration_is_snapshotted_and_retry_copies_it() -> None:
    repository = InMemorySessionRepository()
    api = TestClient(create_app(repository))
    payload = {
        "scenario_id": "equipment-supply",
        "configuration": {
            "topic": "Пилотная поставка",
            "context": "Проверяем пользовательский контекст для отдельной тренировки.",
            "participant_role": "Руководитель закупки",
            "opponent_role": "Коммерческий директор поставщика",
            "objective": "Согласовать пакет без потери сроков",
            "difficulty": "easy",
            "tone": "cooperative",
            "max_turns": 6,
        },
    }
    created = api.post("/api/v1/sessions", json=payload)
    assert created.status_code == 201
    session = created.json()
    session_id = UUID(session["id"])
    assert {
        key: value for key, value in session["configuration"].items() if key != "simulation"
    } == payload["configuration"]
    assert session["configuration"]["simulation"]["enabled"] is True

    stored = repository.get(session_id)
    assert stored is not None
    assert stored.configuration.topic == "Пилотная поставка"
    assert stored.configuration.max_turns == 6

    assert api.post(f"/api/v1/sessions/{session_id}/complete").status_code == 200
    retry = api.post(f"/api/v1/sessions/{session_id}/retry")
    assert retry.status_code == 201
    assert retry.json()["configuration"] == session["configuration"]


def test_materialization_changes_public_context_signals_and_turn_limit_only() -> None:
    catalog = get_scenario_catalog()
    base = catalog.get_definition("equipment-supply")
    assert base is not None
    config = SessionConfiguration(
        topic="Пользовательская тема",
        context="Пользовательский контекст переговорной тренировки.",
        participant_role="Покупатель",
        opponent_role="Жёсткий поставщик",
        objective="Получить измеримое соглашение",
        difficulty="hard",
        tone="firm",
        max_turns=6,
    )

    materialized = materialize_session_definition(base, config)
    assert materialized.public_briefing.title == config.topic
    assert materialized.public_briefing.situation == config.context
    assert materialized.public_briefing.objective == config.objective
    assert materialized.turn_limits.maximum == 6
    assert materialized.initial_state.trust < base.initial_state.trust
    assert materialized.initial_state.tension > base.initial_state.tension
    assert materialized.initial_state.relationship < base.initial_state.relationship
    assert materialized.roles == base.roles
    assert materialized.issues == base.issues
    assert materialized.zopa == base.zopa


def test_configuration_is_used_in_opponent_prompt() -> None:
    provider = RecordingProvider()
    api = TestClient(create_app(InMemorySessionRepository(), llm_provider=provider))
    response = api.post(
        "/api/v1/sessions",
        json={
            "scenario_id": "equipment-supply",
            "configuration": {
                "topic": "Особая тема поставки",
                "context": "Контекст отдельной пользовательской тренировки с деталями.",
                "participant_role": "Руководитель закупки",
                "opponent_role": "Жёсткий поставщик",
                "objective": "Согласовать срок и цену",
                "difficulty": "hard",
                "tone": "firm",
                "max_turns": 6,
            },
        },
    )
    assert response.status_code == 201
    session_id = response.json()["id"]
    exchange = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Какие условия для вас важны?"},
    )
    assert exchange.status_code == 200
    prompt = provider.requests[0].prompt
    assert all(value in prompt for value in (
        "Особая тема поставки",
        "Контекст отдельной пользовательской тренировки с деталями.",
        "Согласовать срок и цену",
        "Жёсткий поставщик",
        "firm",
        "hard",
        "Руководитель закупки",
    ))
