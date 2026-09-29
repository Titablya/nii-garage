"""Black-box regression tests for the deterministic negotiation engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.scenario import ScenarioDefinition
from app.engine import (
    ActionTag,
    IssueValue,
    NegotiationOutcome,
    NegotiationStatus,
    ReasonCode,
    assess_offer,
    initial_state,
    make_offer,
    transition_turn,
)


ROOT = Path(__file__).parents[1]


def _scenario(name: str) -> ScenarioDefinition:
    payload = (ROOT / "scenarios" / f"{name}.v1.json").read_text(encoding="utf-8")
    return ScenarioDefinition.model_validate_json(payload)


@pytest.fixture(params=("equipment-supply", "project-resources"))
def scenario(request: pytest.FixtureRequest) -> ScenarioDefinition:
    return _scenario(request.param)


def _run(scenario: ScenarioDefinition, utterances: list[str]):
    state = initial_state(scenario)
    transitions = []
    for text in utterances:
        transition = transition_turn(scenario, state, text)
        transitions.append(transition)
        state = transition.state
        if state.status is NegotiationStatus.COMPLETED:
            break
    return transitions


def _participant_texts(name: str, case: str) -> list[str]:
    path = ROOT / "golden_dialogues" / name / f"{case}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [item["text"] for item in data["messages"] if item["role"] == "participant"]


def test_same_sequence_has_identical_transitions_and_state(scenario: ScenarioDefinition) -> None:
    sequence = _participant_texts(scenario.metadata.id, "strong_success")
    left = _run(scenario, sequence)
    right = _run(scenario, sequence)
    assert [item.model_dump(mode="json") for item in left] == [
        item.model_dump(mode="json") for item in right
    ]


def test_metrics_are_bounded_and_turn_count_is_monotonic(scenario: ScenarioDefinition) -> None:
    transitions = _run(scenario, _participant_texts(scenario.metadata.id, "strong_success"))
    turns = [item.state.turn_count for item in transitions]
    assert turns == sorted(turns)
    assert all(b > a for a, b in zip([0, *turns], turns))
    for item in transitions:
        assert all(0 <= getattr(item.state, metric) <= 100 for metric in
                   ("trust", "tension", "progress", "relationship"))


def test_strong_corpus_outperforms_weak_and_aggressive(scenario: ScenarioDefinition) -> None:
    strong = _run(scenario, _participant_texts(scenario.metadata.id, "strong_success"))[-1].state
    weak = _run(scenario, _participant_texts(scenario.metadata.id, "weak"))[-1].state
    aggressive = _run(scenario, ["Вы не понимаете, что делаете. Иначе сообщу руководству."] * 4)[-1].state
    assert (strong.trust + strong.progress + strong.relationship) > (
        weak.trust + weak.progress + weak.relationship
    )
    assert (strong.trust + strong.progress + strong.relationship) > (
        aggressive.trust + aggressive.progress + aggressive.relationship
    )


def test_personal_attack_and_threat_raise_tension_and_harm_relationship(scenario: ScenarioDefinition) -> None:
    state = initial_state(scenario)
    before = (state.tension, state.relationship)
    result = transition_turn(scenario, state, "Вы не понимаете, что делаете. Иначе сообщу руководству.")
    assert ActionTag.PERSONAL_ATTACK in result.action.tags
    assert ActionTag.THREAT in result.action.tags
    assert result.state.tension > before[0]
    assert result.state.relationship < before[1]


def test_disclosure_requires_configured_trigger(scenario: ScenarioDefinition) -> None:
    state = initial_state(scenario)
    first = transition_turn(scenario, state, "Предлагаю обсудить общий план.")
    assert not first.state.disclosed_interest_ids
    rule = scenario.disclosure_rules[0]
    state = first.state
    for _ in range(rule.threshold):
        if rule.trigger.value == "open_question":
            text = "Что для вас сейчас важно?"
        elif rule.trigger.value == "active_listening":
            text = "Правильно ли я понимаю, что это для вас важно?"
        elif rule.trigger.value == "trust":
            text = "Правильно ли я понимаю, что это для вас важно?"
        else:
            text = "Продолжим обсуждение вариантов."
        state = transition_turn(scenario, state, text).state
    assert rule.hidden_interest_id in set(state.disclosed_interest_ids)


def test_offer_assessment_respects_zopa_and_batna(scenario: ScenarioDefinition) -> None:
    zopa = {item.issue_id: item for item in scenario.zopa}
    values = []
    for issue in scenario.issues:
        item = zopa[issue.id]
        if hasattr(item, "lower"):
            value = (item.lower + item.upper) / 2
        else:
            value = issue.party_ranges[scenario.roles[0].id].aspiration
        values.append(IssueValue(issue_id=issue.id, value=value))
    acceptable = assess_offer(scenario, make_offer(scenario.roles[0].id, tuple(values), 1))
    assert acceptable.complete and acceptable.acceptable_for_all
    bad = [app for app in values]
    first_issue = next(issue for issue in scenario.issues if issue.id == bad[0].issue_id)
    bad[0] = IssueValue(issue_id=bad[0].issue_id, value=first_issue.party_ranges[scenario.roles[0].id].minimum - 1)
    rejected = assess_offer(scenario, make_offer(scenario.roles[0].id, tuple(bad), 1))
    assert not rejected.acceptable_for_all
    assert rejected.reservation_violations or rejected.zopa_violation_issue_ids


def test_zopa_does_not_automatically_agree_and_offer_creates_counter(scenario: ScenarioDefinition) -> None:
    state = initial_state(scenario)
    result = transition_turn(scenario, state, "Предлагаю обсудить варианты и условия.")
    assert result.state.status is NegotiationStatus.ACTIVE
    assert result.directive.kind.value == "clarify"
    offer_text = "Фиксируем пакет: предлагаю бюджет 6 млн, 3 специалиста, старт 20 дней и отчётность 4 часа." if scenario.metadata.id == "project-resources" else "Фиксируем пакет: предлагаю цену 9,7 млн, поставку 42 дня, предоплату 45%, гарантию 30 месяцев и штраф 0,3%."
    result = transition_turn(scenario, result.state, offer_text)
    assert result.directive.kind.value in {"accept", "counter"}
    assert any(event.code is ReasonCode.OFFER_EXTRACTED for event in result.events)


def test_explicit_walk_away_is_terminal_and_reasoned(scenario: ScenarioDefinition) -> None:
    result = transition_turn(scenario, initial_state(scenario), "Прекращаю переговоры, сделки не будет.")
    assert result.state.status is NegotiationStatus.COMPLETED
    assert result.state.outcome is NegotiationOutcome.WALK_AWAY
    assert result.directive.kind.value == "walk_away"
    assert ReasonCode.WALK_AWAY_REACHED in result.directive.reason_codes


def test_turn_maximum_is_terminal_and_repeat_is_deterministic(scenario: ScenarioDefinition) -> None:
    state = initial_state(scenario)
    for turn in range(scenario.turn_limits.maximum):
        # Distinct option signatures keep this sequence active until the hard limit.
        result = transition_turn(scenario, state, f"Предлагаю вариант {turn + 1} без новых условий.")
        state = result.state
    assert state.status is NegotiationStatus.COMPLETED
    assert ReasonCode.TURN_LIMIT_REACHED in {event.code for event in result.events}
    repeat = transition_turn(scenario, state, "Любой текст после завершения")
    assert repeat.state == state
    assert repeat.events[0].code is ReasonCode.TERMINAL_STATE_IGNORED


def test_events_form_reason_journal_and_outputs_do_not_leak_hidden_data(scenario: ScenarioDefinition) -> None:
    result = transition_turn(scenario, initial_state(scenario), "Что для вас сейчас важно?")
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))
    public = result.model_dump(mode="json")
    hidden = {interest.id for role in scenario.roles for interest in role.hidden_interests}
    serialized = json.dumps(public, ensure_ascii=False)
    assert not any(interest_id in serialized for interest_id in hidden)
