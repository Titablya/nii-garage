from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.scenario import ScenarioDefinition
from app.engine import (
    ActionTag,
    DirectiveKind,
    IssueValue,
    NegotiationOutcome,
    NegotiationStatus,
    ReasonCode,
    assess_offer,
    classify_action,
    deterministic_counter_offer,
    extract_issue_values,
    initial_state,
    make_offer,
    transition_turn,
)
from app.random_scenarios import build_random_scenarios


SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "scenarios"


def _scenario(name: str) -> ScenarioDefinition:
    return ScenarioDefinition.model_validate_json(
        (SCENARIOS_PATH / f"{name}.v1.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def equipment() -> ScenarioDefinition:
    return _scenario("equipment-supply")


@pytest.fixture(scope="module")
def resources() -> ScenarioDefinition:
    return _scenario("project-resources")


def _equipment_offer_text(price: str = "9,75") -> str:
    return (
        f"Предлагаю цену {price} млн рублей, поставку за 40 дней, "
        "предоплату 45%, гарантию 24 месяца и штраф 0,25% в день."
    )


def _resource_offer_text(specialists: int = 3) -> str:
    return (
        f"Предлагаю бюджет 6,25 млн рублей, {specialists} специалиста, "
        "старт через 25 дней и отчётность 4 часа в неделю."
    )


def test_initial_state_is_scenario_derived_frozen_and_canonical(
    equipment: ScenarioDefinition, resources: ScenarioDefinition
) -> None:
    equipment_state = initial_state(equipment)
    resources_state = initial_state(resources)

    assert equipment_state.scenario_version_id == "equipment-supply:v1"
    assert equipment_state.participant_role_id == "buyer"
    assert equipment_state.opponent_role_id == "supplier"
    assert equipment_state.trust == 48
    assert [item.role_id for item in resources_state.concession_budget] == [
        "division_director",
        "project_lead",
    ]
    with pytest.raises(ValidationError):
        equipment_state.trust = 100  # type: ignore[misc]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Правильно ли я понимаю, что для вас важно сохранить срок?",
            {ActionTag.OPEN_QUESTION, ActionTag.ACTIVE_LISTENING},
        ),
        ("Сверим предложение с рыночным диапазоном.", {ActionTag.OBJECTIVE_CRITERION}),
        ("Предлагаю два варианта на выбор: быстрый либо экономный.", {ActionTag.OPTION}),
        (
            "Предлагаю два равноценных пакета. Первый: 6 млн рублей и старт через 20 дней. "
            "Второй: 7 млн рублей и старт через 28 дней.",
            {ActionTag.OPTION},
        ),
        (
            "Согласен на четыре часа отчётности, если фиксируем бюджет 6 млн рублей и трёх специалистов.",
            {ActionTag.OPTION, ActionTag.CONDITIONAL_AGREEMENT},
        ),
        ("Если вы увеличите гарантию, то мы повысим аванс.", {ActionTag.CONDITIONAL_AGREEMENT}),
        ("Зафиксируем ответственного и контрольную точку.", {ActionTag.COMMITMENT}),
        ("Вы не понимаете предмет и некомпетентны.", {ActionTag.PERSONAL_ATTACK}),
        ("Иначе я сообщу руководству, будут последствия.", {ActionTag.THREAT}),
        ("Ладно, согласен без встречных условий.", {ActionTag.UNILATERAL_CONCESSION, ActionTag.ACCEPT}),
        ("Это предложение не подходит, отклоняю.", {ActionTag.REJECT}),
        ("Прекращаю переговоры, сделки не будет.", {ActionTag.WALK_AWAY}),
    ],
)
def test_russian_action_classifier(
    equipment: ScenarioDefinition, text: str, expected: set[ActionTag]
) -> None:
    action = classify_action(equipment, initial_state(equipment), text)
    assert set(action.tags) >= expected


def test_issue_extraction_covers_both_scenarios(
    equipment: ScenarioDefinition, resources: ScenarioDefinition
) -> None:
    equipment_values = {
        item.issue_id: item.value
        for item in extract_issue_values(equipment, _equipment_offer_text("9,7"))
    }
    resource_values = {
        item.issue_id: item.value
        for item in extract_issue_values(resources, _resource_offer_text())
    }

    assert equipment_values == {
        "delay_penalty": 0.25,
        "delivery_days": 40.0,
        "prepayment": 45.0,
        "price": 9_700_000.0,
        "warranty_months": 24.0,
    }
    assert resource_values == {
        "budget": 6.25,
        "reporting_hours": 4.0,
        "specialists": 3.0,
        "start_days": 25.0,
    }


def test_natural_russian_word_numbers_keep_package_terms_separate(
    resources: ScenarioDefinition,
) -> None:
    values = {
        item.issue_id: item.value
        for item in extract_issue_values(
            resources,
            "Предлагаю пакет: 6 млн, три специалиста, старт через 20 дней "
            "и четыре часа отчётности в неделю.",
        )
    }

    assert values == {
        "budget": 6.0,
        "reporting_hours": 4.0,
        "specialists": 3.0,
        "start_days": 20.0,
    }


def test_unlabelled_market_range_uses_the_following_concrete_anchor(
    equipment: ScenarioDefinition,
) -> None:
    values = {
        item.issue_id: item.value
        for item in extract_issue_values(
            equipment,
            "Рыночный диапазон сопоставимых линий — 9–11 млн рублей, "
            "поэтому отправной точкой считаю 9,5 млн рублей.",
        )
    }

    assert values["price"] == 9_500_000.0


@pytest.mark.parametrize(
    "text",
    [
        "Рыночный диапазон сопоставимых линий — 9–11 млн рублей.",
        "Рыночный диапазон сопоставимых линий — от 9 до 11 млн рублей.",
        "Рыночный диапазон сопоставимых линий — между 9 и 11 млн рублей.",
        "Рыночный диапазон: 9 млн — 11 млн рублей.",
    ],
)
def test_market_range_is_evidence_not_an_actionable_offer(
    equipment: ScenarioDefinition, text: str
) -> None:
    state = initial_state(equipment)
    action = classify_action(equipment, state, text)
    result = transition_turn(equipment, state, text)

    assert ActionTag.OBJECTIVE_CRITERION in action.tags
    assert not action.issue_values
    assert result.state.status is NegotiationStatus.ACTIVE
    assert result.directive.kind is not DirectiveKind.WALK_AWAY


def test_final_resource_confirmation_overrides_previous_counteroffer(
    resources: ScenarioDefinition,
) -> None:
    state = initial_state(resources)
    proposed = transition_turn(
        resources,
        state,
        "Предлагаю пакет: 6 млн, три специалиста, старт через 20 дней "
        "и четыре часа отчётности в неделю.",
    ).state
    confirmed = transition_turn(
        resources,
        proposed,
        "Согласен, если фиксируем 6 млн, трёх специалистов, старт через 20 дней "
        "и четыре часа отчётности в неделю.",
    ).state

    assert confirmed.accepted_offer is not None
    assert {item.issue_id: item.value for item in confirmed.accepted_offer.values} == {
        "budget": 6.0,
        "reporting_hours": 4.0,
        "specialists": 3.0,
        "start_days": 20.0,
    }


@pytest.mark.parametrize(
    ("scenario_name", "text"),
    [
        ("equipment-supply", _equipment_offer_text()),
        ("project-resources", _resource_offer_text()),
    ],
)
def test_offer_assessment_inside_zopa_and_batna(
    scenario_name: str, text: str
) -> None:
    scenario = _scenario(scenario_name)
    state = initial_state(scenario)
    offer = make_offer(
        state.participant_role_id,
        extract_issue_values(scenario, text),
        source_turn=1,
    )
    assessment = assess_offer(scenario, offer)

    assert assessment.complete
    assert assessment.acceptable_for_all
    assert not assessment.zopa_violation_issue_ids
    assert all(item.meets_batna for item in assessment.role_utilities)


def test_offer_outside_opponent_boundary_causes_counter_not_walk_away(
    equipment: ScenarioDefinition,
) -> None:
    state = initial_state(equipment)
    # Buyer-safe price, but below the supplier reservation. The configured
    # buyer walk-away condition does not match, so the opponent counters.
    result = transition_turn(equipment, state, _equipment_offer_text("9,0"))

    assert result.directive.kind is DirectiveKind.COUNTER
    assert result.state.status is NegotiationStatus.ACTIVE
    assert ReasonCode.OFFER_RESERVATION_VIOLATION in {
        item.code for item in result.events
    }
    assert result.directive.offer is not None
    # The supplier no longer concedes every issue into the ZOPA on turn one.
    assessment = assess_offer(equipment, result.directive.offer)
    assert not assessment.acceptable_for_all
    assert {item.issue_id for item in assessment.reservation_violations if item.role_id == "buyer"} == {"price"}
    assert {item.issue_id: item.value for item in result.directive.offer.values}["delivery_days"] == 40.0
    assert not any(item.role_id == "supplier" for item in assessment.reservation_violations)


def test_initial_counter_preserves_two_negotiable_conflicts_across_catalog(
    equipment: ScenarioDefinition, resources: ScenarioDefinition,
) -> None:
    for scenario in (equipment, resources, *build_random_scenarios((equipment, resources))):
        state = initial_state(scenario)
        counter = deterministic_counter_offer(scenario, state.opponent_role_id, 1)
        initial = assess_offer(scenario, counter)
        participant_conflicts = {
            item.issue_id for item in initial.reservation_violations
            if item.role_id == state.participant_role_id
        }
        assert len(participant_conflicts) >= 2, scenario.metadata.id
        assert not initial.acceptable_for_all, scenario.metadata.id
        assert not any(
            item.role_id == state.opponent_role_id for item in initial.reservation_violations
        ), scenario.metadata.id

        # A substantive exchange can still reach a viable package; no case is
        # made unwinnable by the stronger opening position.
        workable = deterministic_counter_offer(
            scenario, state.opponent_role_id, 4, negotiation_progress=36
        )
        assert assess_offer(scenario, workable).acceptable_for_all, scenario.metadata.id


def test_repeating_refusal_does_not_buy_concessions(equipment: ScenarioDefinition) -> None:
    first = transition_turn(equipment, initial_state(equipment), "Предлагаю цену 9 млн рублей.")
    assert first.directive.kind is DirectiveKind.COUNTER
    second = transition_turn(equipment, first.state, "Не согласен с вашей ценой.")
    assert second.directive.kind is DirectiveKind.COUNTER
    assert second.directive.offer is not None
    assert second.directive.offer.values == first.directive.offer.values


def test_director_does_not_offer_more_budget_than_requested(
    resources: ScenarioDefinition,
) -> None:
    counter = deterministic_counter_offer(
        resources,
        "division_director",
        4,
        negotiation_progress=42,
        participant_values=(IssueValue(issue_id="budget", value=6.0),),
    )
    values = {item.issue_id: item.value for item in counter.values}
    assert values["budget"] == 6.0
    assert values["specialists"] == 3.0
    assert assess_offer(resources, counter).acceptable_for_all


def test_reply_parser_uses_last_explicit_value_for_same_issue(
    resources: ScenarioDefinition,
) -> None:
    reply = (
        "Бюджет 6 млн рублей для нас высок. Наш пакет: бюджет 4 млн рублей, "
        "2 специалиста, старт через 25 дней, отчётность 4 часа в неделю."
    )
    values = extract_issue_values(resources, reply, prefer_last=True)
    assert {item.issue_id: item.value for item in values}["budget"] == 4.0

    natural_counter = (
        "Цена 10,8 млн рублей, срок поставки 50 календарных дней, "
        "предоплата 45%, гарантия 24 месяца и штраф за задержку 0,25% в день."
    )
    equipment = _scenario("equipment-supply")
    assert len(extract_issue_values(equipment, natural_counter, prefer_last=True)) == 5
    labelled_counter = (
        "Цена контракта — 10,8 млн рублей; Срок поставки — 50 дней; "
        "Предоплата — 45 процентов; Гарантия — 24 месяца; "
        "Штраф за задержку — 0,25 процента в день."
    )
    assert len(extract_issue_values(equipment, labelled_counter, prefer_last=True)) == 5


def test_partial_reply_to_strong_anchor_does_not_trigger_false_walk_away(
    equipment: ScenarioDefinition,
) -> None:
    first = transition_turn(equipment, initial_state(equipment), "Предлагаю цену 9 млн рублей.")
    second = transition_turn(
        equipment,
        first.state,
        "По объективным рыночным предложениям давайте обсудим цену 9,6 млн рублей.",
    )
    assert second.state.status is NegotiationStatus.ACTIVE
    assert second.directive.kind is DirectiveKind.COUNTER


def test_configured_walk_away_predicates_are_evaluated(
    equipment: ScenarioDefinition, resources: ScenarioDefinition
) -> None:
    bad_for_buyer = transition_turn(
        equipment,
        initial_state(equipment),
        (
            "Предлагаю цену 11,5 млн рублей, поставку за 60 дней, "
            "предоплату 70%, гарантию 12 месяцев и штраф 0% в день."
        ),
    )
    insufficient_team = transition_turn(
        resources, initial_state(resources), _resource_offer_text(specialists=2)
    )

    for result in (bad_for_buyer, insufficient_team):
        assert result.directive.kind is DirectiveKind.WALK_AWAY
        assert result.state.outcome is NegotiationOutcome.WALK_AWAY
        assert ReasonCode.WALK_AWAY_CONDITION_MATCHED in {
            item.code for item in result.events
        }


def test_configured_compensation_prevents_automatic_walk_away(
    equipment: ScenarioDefinition,
) -> None:
    result = transition_turn(
        equipment,
        initial_state(equipment),
        (
            "Если вы обеспечите расширенный сервис, то предлагаю цену 11,5 млн рублей, "
            "поставку за 60 дней, предоплату 70%, гарантию 12 месяцев и штраф 0% в день."
        ),
    )

    assert ActionTag.CONDITIONAL_AGREEMENT in result.action.tags
    assert result.directive.kind is DirectiveKind.COUNTER
    assert result.state.status is NegotiationStatus.ACTIVE


def test_disclosure_only_reveals_opponent_owned_interest(
    equipment: ScenarioDefinition, resources: ScenarioDefinition
) -> None:
    equipment_state = initial_state(equipment).model_copy(update={"trust": 65})
    first = transition_turn(
        equipment, equipment_state, "Что для вас важно в структуре оплаты?"
    )
    second = transition_turn(
        equipment, first.state, "Какие ограничения есть у производства?"
    )

    assert second.state.disclosed_interest_ids == ("supplier.cashgap",)
    assert "buyer.audit" not in second.state.disclosed_interest_ids
    assert any("аванс" in fact.casefold() for fact in second.directive.public_facts)
    journal_json = "".join(item.model_dump_json() for item in second.events)
    assert "supplier.cashgap" not in journal_json
    assert "buyer.audit" not in journal_json
    assert '"role_id"' not in journal_json
    assert '"interest_id"' not in journal_json

    # Active-listening rule owned by the participant must never be emitted.
    resource_result = transition_turn(
        resources,
        initial_state(resources),
        "Правильно ли я понимаю, что для вас важно сохранить операционную мощность?",
    )
    assert "lead.scope" not in resource_result.state.disclosed_interest_ids
    assert not any("полный функциональный" in fact for fact in resource_result.directive.public_facts)


def test_listening_improves_and_threat_harms_state(
    equipment: ScenarioDefinition,
) -> None:
    state = initial_state(equipment)
    listening = transition_turn(
        equipment,
        state,
        "Правильно ли я понимаю, что для вас важно загрузить производство?",
    )
    threat = transition_turn(
        equipment, state, "Иначе я сообщу руководству, и будут последствия."
    )

    assert listening.state.trust > state.trust
    assert listening.state.tension < state.tension
    assert threat.state.trust < state.trust
    assert threat.state.tension > state.tension
    assert threat.state.relationship < state.relationship


def test_equipment_offer_can_reach_agreement(equipment: ScenarioDefinition) -> None:
    result = transition_turn(
        equipment, initial_state(equipment), _equipment_offer_text()
    )

    assert result.directive.kind is DirectiveKind.ACCEPT
    assert result.state.status is NegotiationStatus.COMPLETED
    assert result.state.outcome is NegotiationOutcome.AGREEMENT
    assert result.state.accepted_offer is not None
    assert result.state.progress == 100


def test_project_offer_requires_explicit_commitment_before_agreement(
    resources: ScenarioDefinition,
) -> None:
    proposed = transition_turn(
        resources, initial_state(resources), _resource_offer_text()
    )
    assert proposed.directive.kind is DirectiveKind.CLARIFY
    assert proposed.directive.template_key == "opponent.clarify_commitment"
    assert proposed.state.status is NegotiationStatus.ACTIVE
    assert ReasonCode.COMMITMENT_REQUIRED in {item.code for item in proposed.events}

    committed = transition_turn(
        resources,
        proposed.state,
        "Подтверждаю и фиксируем ответственных, сроки и контрольную точку.",
    )
    assert committed.directive.kind is DirectiveKind.ACCEPT
    assert committed.state.outcome is NegotiationOutcome.AGREEMENT
    assert len(committed.state.preliminary_commitments) == 1


def test_repeated_positions_reach_impasse_after_scenario_minimum(
    equipment: ScenarioDefinition,
) -> None:
    state = initial_state(equipment)
    result = None
    for _ in range(equipment.turn_limits.minimum):
        result = transition_turn(equipment, state, "Моя позиция остаётся прежней.")
        state = result.state

    assert result is not None
    assert result.directive.kind is DirectiveKind.IMPASSE
    assert result.state.outcome is NegotiationOutcome.IMPASSE


def test_resource_impasse_respects_discovered_interest_predicate(
    resources: ScenarioDefinition,
) -> None:
    state = initial_state(resources)
    for text in (
        "Что для вас сейчас важно?",
        "Какие ограничения нужно учесть?",
    ):
        state = transition_turn(resources, state, text).state

    assert state.disclosed_interest_ids == ("director.audit",)
    for _ in range(3):
        result = transition_turn(resources, state, "Моя позиция остаётся прежней.")
        state = result.state

    assert state.turn_count >= resources.turn_limits.minimum
    assert state.stagnant_turns >= 3
    assert state.status is NegotiationStatus.ACTIVE
    assert result.directive.kind is DirectiveKind.CLARIFY


def test_explicit_exit_and_turn_limit(
    equipment: ScenarioDefinition,
) -> None:
    explicit = transition_turn(
        equipment, initial_state(equipment), "Прекращаю переговоры, сделки не будет."
    )
    assert explicit.state.outcome is NegotiationOutcome.WALK_AWAY

    almost_expired = initial_state(equipment).model_copy(
        update={"turn_count": equipment.turn_limits.maximum - 1}
    )
    expired = transition_turn(equipment, almost_expired, "Нужно продолжить обсуждение.")
    assert expired.state.status is NegotiationStatus.COMPLETED
    assert expired.state.outcome is NegotiationOutcome.IMPASSE
    assert ReasonCode.TURN_LIMIT_REACHED in {item.code for item in expired.events}


def test_state_is_bounded_and_transition_is_byte_deterministic(
    equipment: ScenarioDefinition,
) -> None:
    state = initial_state(equipment).model_copy(
        update={"trust": 1, "tension": 99, "relationship": 2}
    )
    text = "Иначе я сообщу руководству, и будут последствия."
    first = transition_turn(equipment, state, text)
    second = transition_turn(equipment, state, text)

    assert first.model_dump_json() == second.model_dump_json()
    assert 0 <= first.state.trust <= 100
    assert 0 <= first.state.tension <= 100
    assert 0 <= first.state.progress <= 100
    assert 0 <= first.state.relationship <= 100
    assert all(0 <= item.remaining <= 100 for item in first.state.concession_budget)


def test_state_from_another_scenario_is_rejected(
    equipment: ScenarioDefinition, resources: ScenarioDefinition
) -> None:
    with pytest.raises(ValueError, match="another scenario"):
        transition_turn(resources, initial_state(equipment), "Что для вас важно?")
