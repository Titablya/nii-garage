from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.golden_dialogue import DialogueRole, GoldenDialogueDefinition
from app.engine import initial_state, transition_turn
from app.models import Message, NegotiationSession, SessionStatus
from app.reporting import evaluate_session
from app.scenario_catalog import DEFAULT_SCENARIOS_PATH, load_scenario_catalog


GOLDEN_ROOT = Path(__file__).resolve().parent.parent / "golden_dialogues"
GOLDEN_CASES = [
    (scenario_id, case_type)
    for scenario_id in ("equipment-supply", "project-resources")
    for case_type in (
        "strong_success",
        "weak",
        "agreement_bad_process",
        "strong_process_bad_result",
        "impasse",
    )
]


def _golden(scenario_id: str, case_type: str) -> GoldenDialogueDefinition:
    source = GOLDEN_ROOT / scenario_id / f"{case_type}.json"
    return GoldenDialogueDefinition.model_validate_json(source.read_text(encoding="utf-8"))


def _session_from_golden(case: GoldenDialogueDefinition) -> tuple[object, NegotiationSession]:
    scenario_id = case.scenario_version_id.split(":", 1)[0]
    scenario = load_scenario_catalog(DEFAULT_SCENARIOS_PATH).get_definition(scenario_id)
    assert scenario is not None

    state = initial_state(scenario)
    messages: list[Message] = []
    for item in case.messages:
        role = "participant" if item.role is DialogueRole.PARTICIPANT else "opponent"
        messages.append(Message(role=role, content=item.text))
        if role == "participant":
            state = transition_turn(scenario, state, item.text).state

    return scenario, NegotiationSession(
        scenario_id=scenario_id,
        scenario_version_id=case.scenario_version_id,
        engine_state=state,
        status=SessionStatus.COMPLETED,
        messages=messages,
    )


@pytest.mark.parametrize("scenario_id", ["equipment-supply", "project-resources"])
def test_strong_reference_dialogues_land_in_their_score_bands(scenario_id: str) -> None:
    case = _golden(scenario_id, "strong_success")
    scenario, session = _session_from_golden(case)

    report = evaluate_session(scenario, session)  # type: ignore[arg-type]

    assert case.expected.score_band.minimum <= report.score <= case.expected.score_band.maximum
    assert report.outcome.kind == "agreement"
    assert report.outcome.meets_batna is True
    assert report.outcome.reservation_respected is True
    assert [block.max_score for block in report.blocks] == [20, 25, 20, 25, 10]
    assert report.task_checks
    assert all(item.status == "met" for item in report.task_checks)


def test_destructive_process_produces_evidence_backed_penalties() -> None:
    case = _golden("equipment-supply", "agreement_bad_process")
    scenario, session = _session_from_golden(case)

    report = evaluate_session(scenario, session)  # type: ignore[arg-type]
    penalties = {item.id: item for item in report.penalties}

    assert {"penalty.personal_attack", "penalty.threat", "penalty.ignored_concern"} <= penalties.keys()
    assert all(item.occurrences >= 1 and item.evidence for item in penalties.values())
    assert report.methodology.penalty_points == sum(
        item.points * item.occurrences for item in report.penalties
    )


def test_report_is_deterministic_traceable_and_keeps_private_state_private() -> None:
    case = _golden("equipment-supply", "strong_success")
    scenario, session = _session_from_golden(case)
    participant_messages = {message.id: message.content for message in session.messages if message.role == "participant"}

    first = evaluate_session(scenario, session)  # type: ignore[arg-type]
    second = evaluate_session(scenario, session)  # type: ignore[arg-type]

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.trajectory[0].turn == 0
    assert len(first.trajectory) == len(participant_messages) + 1
    assert len(first.improvements) <= 3

    evidence_items = [
        evidence
        for block in first.blocks
        for criterion in block.criteria
        for evidence in criterion.evidence
    ] + [
        evidence for finding in first.strengths for evidence in finding.evidence
    ] + [
        evidence for penalty in first.penalties for evidence in penalty.evidence
    ]
    assert evidence_items
    for evidence in evidence_items:
        assert evidence.message_id in participant_messages
        assert evidence.quote in participant_messages[evidence.message_id]

    rendered = json.dumps(first.model_dump(mode="json"), ensure_ascii=False).casefold()
    assert not any(token in rendered for token in (
        "engine_state", "reason_events", "hidden_interests", "reservation_points",
        "concession_budget", "disclosed_interest_ids",
    ))


def test_report_allows_derived_metric_changes_between_evaluator_releases() -> None:
    case = _golden("equipment-supply", "strong_success")
    scenario, session = _session_from_golden(case)
    altered_state = session.engine_state.model_copy(
        update={"trust": max(0, session.engine_state.trust - 1)}
    )
    historical = session.model_copy(update={"engine_state": altered_state})

    report = evaluate_session(scenario, historical)  # type: ignore[arg-type]

    assert report.outcome.kind == "agreement"


def test_report_rejects_history_that_changes_authoritative_result() -> None:
    case = _golden("equipment-supply", "strong_success")
    scenario, session = _session_from_golden(case)
    altered_state = session.engine_state.model_copy(
        update={"turn_count": session.engine_state.turn_count + 1}
    )
    tampered = session.model_copy(update={"engine_state": altered_state})

    with pytest.raises(ValueError, match="does not reproduce"):
        evaluate_session(scenario, tampered)  # type: ignore[arg-type]


def test_report_recognizes_natural_meso_and_conditional_exchange() -> None:
    scenario = load_scenario_catalog(DEFAULT_SCENARIOS_PATH).get_definition("project-resources")
    assert scenario is not None
    participant_turns = (
        "Нам нужен проверяемый результат в текущем квартале. Какие ограничения по двум "
        "обязательным операционным программам важнее всего учесть при выделении команды?",
        "Правильно понимаю: вам нужен не просто меньший запрос, а пакет, который сохраняет "
        "операционную мощность и даёт прозрачный контроль?",
        "Давайте решим общую задачу. Сверим по плану ресурсов доступную мощность для команды "
        "и дату старта, по экономике пилота — бюджет, а по регламенту — отчётность.",
        "Предлагаю два равноценных пакета. Первый: бюджет 6 млн рублей, три специалиста, "
        "старт через 20 дней, отчётность 4 часа в неделю. Второй: бюджет 7 млн рублей, "
        "три специалиста, старт через 30 дней, отчётность 5 часов в неделю.",
        "Согласен на четыре часа отчётности, если фиксируем первый пакет целиком: бюджет "
        "6 млн рублей, три специалиста и старт через 20 дней. Зафиксируем контрольную точку.",
    )
    state = initial_state(scenario)
    messages: list[Message] = []
    for text in participant_turns:
        messages.append(Message(role="participant", content=text))
        state = transition_turn(scenario, state, text).state
        messages.append(Message(role="opponent", content="Продолжим обсуждение пакета."))

    session = NegotiationSession(
        scenario_id=scenario.metadata.id,
        scenario_version_id=scenario.metadata.version_id,
        engine_state=state,
        status=SessionStatus.COMPLETED,
        messages=messages,
    )
    report = evaluate_session(scenario, session)
    option_criterion = next(
        criterion
        for block in report.blocks
        for criterion in block.criteria
        if criterion.id == "value.options"
    )

    assert option_criterion.score == option_criterion.max_score
    assert not {"I7", "I8"} & {item.indicator_id for item in report.improvements}


@pytest.mark.parametrize(("scenario_id", "case_type"), GOLDEN_CASES)
def test_every_golden_dialogue_produces_a_consistent_private_safe_report(
    scenario_id: str, case_type: str
) -> None:
    case = _golden(scenario_id, case_type)
    scenario, session = _session_from_golden(case)
    participant_messages = {
        message.id: message.content for message in session.messages if message.role == "participant"
    }

    report = evaluate_session(scenario, session)  # type: ignore[arg-type]
    raw_score = sum(block.score for block in report.blocks)
    penalty_points = sum(item.points * item.occurrences for item in report.penalties)
    expected = max(0, min(100, raw_score + penalty_points))
    if report.methodology.score_cap is not None:
        expected = min(expected, report.methodology.score_cap)

    assert report.score == expected
    assert len(report.blocks) == 5
    assert len(report.improvements) <= 3
    assert len(report.trajectory) == len(participant_messages) + 1

    evidence_items = [
        evidence
        for block in report.blocks
        for criterion in block.criteria
        for evidence in criterion.evidence
    ] + [
        evidence for item in (*report.strengths, *report.penalties) for evidence in item.evidence
    ]
    for evidence in evidence_items:
        assert evidence.message_id in participant_messages
        assert evidence.quote.rstrip("…") in participant_messages[evidence.message_id]

    rendered = json.dumps(report.model_dump(mode="json"), ensure_ascii=False).casefold()
    assert not any(token in rendered for token in (
        "engine_state", "reason_events", "hidden_interests", "reservation_points",
        "concession_budget", "disclosed_interest_ids",
    ))
