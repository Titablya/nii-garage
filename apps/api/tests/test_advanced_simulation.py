from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.llm.opponent import OpponentGenerator
from app.main import create_app
from app.models import (
    CheckSimulationHypothesisRequest,
    InteractionMode,
    SessionConfiguration,
    SimulationDisclosure,
    SimulationSettings,
    utc_now,
)
from app.repository import InMemorySessionRepository
from app.scenario_catalog import get_scenario_catalog
from app.services import add_participant_message, build_report, complete_session, create_session
from app.simulation import before_participant_turn, check_hypothesis, public_simulation


def _configuration(*, seed: int = 2026, participants: int = 3, timer: int = 90) -> SessionConfiguration:
    return SessionConfiguration(
        topic="Поставка оборудования",
        context="Компания согласовывает условия поставки оборудования для производственной линии.",
        participant_role="Руководитель закупки",
        opponent_role="Коммерческий директор поставщика",
        objective="Согласовать жизнеспособный пакет условий поставки",
        difficulty="medium",
        tone="businesslike",
        max_turns=12,
        simulation=SimulationSettings(
            seed=seed,
            ai_participants=participants,
            event_intensity=2,
            decision_time_seconds=timer,
            mode=InteractionMode.ESCALATION,
        ),
    )


def test_same_seed_reproduces_schedule_and_private_fields_never_reach_public_snapshot() -> None:
    catalog = get_scenario_catalog()
    first = create_session(InMemorySessionRepository(), catalog, "equipment-supply", _configuration())
    second = create_session(InMemorySessionRepository(), catalog, "equipment-supply", _configuration())

    assert first.simulation_state.event_schedule == second.simulation_state.event_schedule
    first.simulation_state.opponents[0].memory.append("private role memory")
    public = public_simulation(first.simulation_state).model_dump(mode="json")
    rendered = str(public)
    assert "event_schedule" not in public
    assert "memory" not in rendered
    assert "private role memory" not in rendered


def test_timer_records_pressure_without_rejecting_the_participant_turn() -> None:
    repository = InMemorySessionRepository()
    session = create_session(repository, get_scenario_catalog(), "equipment-supply", _configuration(timer=1))
    session.simulation_state.deadline_at = utc_now() - timedelta(seconds=1)

    message = before_participant_turn(session)

    assert message is not None and message.message_kind == "timeout"
    assert session.simulation_state.timed_out_decisions == 1
    assert session.simulation_state.pressure_score == 8


def test_hypotheses_are_checked_only_against_disclosed_public_facts() -> None:
    repository = InMemorySessionRepository()
    session = create_session(repository, get_scenario_catalog(), "equipment-supply", _configuration())
    unknown = check_hypothesis(repository, session, CheckSimulationHypothesisRequest(text="Стороне критичен быстрый запуск"))
    assert unknown.hypothesis.status == "insufficient"

    session.simulation_state.disclosures.append(
        SimulationDisclosure(id="fact-deadline", text="Для стороны критичен быстрый запуск производства", source_turn=1)
    )
    repository.save(session)
    confirmed = check_hypothesis(repository, session, CheckSimulationHypothesisRequest(text="Стороне критичен быстрый запуск"))
    assert confirmed.hypothesis.status == "confirmed"
    assert confirmed.hypothesis.evidence_fact_id == "fact-deadline"


def test_multilateral_api_returns_stable_speakers_and_keeps_zopa_unchanged() -> None:
    catalog = get_scenario_catalog()
    definition_before = catalog.get_definition("equipment-supply")
    assert definition_before is not None
    api = TestClient(create_app(InMemorySessionRepository(), catalog, llm_provider=None))
    created = api.post(
        "/api/v1/sessions",
        json={"scenario_id": "equipment-supply", "configuration": _configuration().model_dump(mode="json")},
    )
    assert created.status_code == 201
    assert created.json()["simulation"]["deadline_at"] is None
    session_id = created.json()["id"]
    exchange = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Какие критерии решения и сроки для вас сейчас приоритетны?"},
    )
    assert exchange.status_code == 200
    payload = exchange.json()
    assert len(payload["opponent_messages"]) == 3
    assert {item["speaker_id"] for item in payload["opponent_messages"]} == {
        "opponent_1", "opponent_2", "opponent_3"
    }
    assert all(item["speaker_label"] for item in payload["opponent_messages"])
    timer = payload["session"]["simulation"]
    deadline = datetime.fromisoformat(timer["deadline_at"].replace("Z", "+00:00"))
    server_time = datetime.fromisoformat(timer["server_time"].replace("Z", "+00:00"))
    assert 89 <= (deadline - server_time).total_seconds() <= 90
    definition_after = catalog.get_definition("equipment-supply")
    assert definition_after is not None
    assert definition_after.zopa == definition_before.zopa
    assert definition_after.issues == definition_before.issues


def test_report_separates_official_skill_from_environment_pressure() -> None:
    repository = InMemorySessionRepository()
    catalog = get_scenario_catalog()
    session = create_session(repository, catalog, "equipment-supply", _configuration())
    import asyncio

    asyncio.run(
        add_participant_message(
            repository,
            catalog,
            OpponentGenerator(None),
            session.id,
            "Какие сроки, риски и критерии результата для вас наиболее важны?",
        )
    )
    completed = complete_session(repository, session.id)
    report = build_report(catalog, completed)

    assert report.simulation is not None
    assert report.simulation.participant_skill_score == report.score
    assert report.simulation.environment_pressure_score > 0
    assert report.simulation.ai_participants == 3
    assert "отдельно" in report.simulation.interpretation.casefold()
