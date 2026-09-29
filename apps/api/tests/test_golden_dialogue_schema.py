from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.golden_dialogue import (
    DialogueOutcome,
    GoldenCaseType,
    GoldenDialogueDefinition,
)
from app.domain.rubric import DEFAULT_RUBRIC_V01
from app.domain.scenario import ScenarioDefinition, ScenarioStatus
from app.golden_catalog import GoldenDialogueConfigurationError, load_golden_dialogue_catalog
from app.scenario_catalog import DEFAULT_SCENARIOS_PATH


def _valid_payload() -> dict:
    return {
        "schema_version": "1.0",
        "dialogue_id": "equipment-supply:v1:strong_success",
        "scenario_version_id": "equipment-supply:v1",
        "rubric_version": "0.1",
        "case_type": "strong_success",
        "title": "Эталон содержательных переговоров",
        "learning_objective": "Показать проверку интересов до формирования пакетного предложения.",
        "messages": [
            {
                "sequence": 1,
                "role": "participant",
                "text": "Верно ли я понимаю, что для вас важнее всего срок ввода линии?",
                "annotations": [
                    {
                        "indicator_id": "I2",
                        "methodology_modules": ["active_listening"],
                        "rationale": "Участник проверяет понимание приоритета другой стороны.",
                        "evidence": {
                            "message_sequence": 1,
                            "quote": "важнее всего срок ввода линии",
                        },
                    }
                ],
            },
            {
                "sequence": 2,
                "role": "opponent",
                "text": "Да, простой после этой даты обойдётся нам дороже закупки.",
                "annotations": [],
            },
            {
                "sequence": 3,
                "role": "participant",
                "text": "Тогда предлагаю сначала сопоставить варианты поставки.",
                "annotations": [],
            },
            {
                "sequence": 4,
                "role": "opponent",
                "text": "Готов обсудить варианты, если сохраним требования к качеству.",
                "annotations": [],
            },
            {
                "sequence": 5,
                "role": "participant",
                "text": "Зафиксируем качество как обязательное условие каждого варианта.",
                "annotations": [],
            },
            {
                "sequence": 6,
                "role": "opponent",
                "text": "Это снимает моё основное опасение.",
                "annotations": [],
            },
            {
                "sequence": 7,
                "role": "participant",
                "text": "Подтверждаю согласованный срок и порядок контроля.",
                "annotations": [],
            },
            {
                "sequence": 8,
                "role": "opponent",
                "text": "Согласен с итоговыми условиями.",
                "annotations": [],
            },
        ],
        "expected": {
            "outcome": "agreement",
            "process_quality": "strong",
            "state_delta": {
                "trust": 15,
                "tension": -10,
                "progress": 30,
                "relationship": 12,
                "concession_budget_delta": {"buyer": -5.0, "supplier": -3.0},
            },
            "score_band": {"minimum": 82, "maximum": 92},
            "block_expectations": [
                {
                    "block_id": "preparation",
                    "minimum_points": 16,
                    "maximum_points": 20,
                    "rationale": "Участник защищает интересы и границы.",
                    "evidence_sequences": [1],
                },
                {
                    "block_id": "process",
                    "minimum_points": 20,
                    "maximum_points": 25,
                    "rationale": "Открытый вопрос даёт значимую информацию.",
                    "evidence_sequences": [1],
                },
                {
                    "block_id": "value",
                    "minimum_points": 15,
                    "maximum_points": 20,
                    "rationale": "Формируется пространство вариантов.",
                    "evidence_sequences": [1],
                },
                {
                    "block_id": "result",
                    "minimum_points": 20,
                    "maximum_points": 25,
                    "rationale": "Ожидается реализуемое соглашение.",
                    "evidence_sequences": [1],
                },
                {
                    "block_id": "relationship",
                    "minimum_points": 8,
                    "maximum_points": 10,
                    "rationale": "Деловые отношения укрепляются.",
                    "evidence_sequences": [1],
                },
            ],
            "penalties": [],
        },
        "methodological_explanation": (
            "Участник отделяет позицию от интереса и создаёт основание для взаимовыгодного обмена."
        ),
    }


def _validate(payload: dict) -> GoldenDialogueDefinition:
    return GoldenDialogueDefinition.model_validate_json(json.dumps(payload, ensure_ascii=False))


def test_valid_definition_is_strict_frozen_and_machine_readable() -> None:
    definition = _validate(_valid_payload())

    assert definition.case_type is GoldenCaseType.STRONG_SUCCESS
    assert definition.messages[0].annotations[0].evidence.message_sequence == 1
    assert definition.model_dump(mode="json")["expected"]["score_band"] == {
        "minimum": 82,
        "maximum": 92,
    }
    with pytest.raises(ValidationError):
        definition.title = "Изменение запрещено"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutation", "error_fragment"),
    [
        (lambda value: value["messages"][1].update(sequence=3), "без пропусков"),
        (lambda value: value["messages"][1].update(role="participant"), "строго чередоваться"),
        (
            lambda value: value["messages"][0]["annotations"][0]["evidence"].update(
                message_sequence=2
            ),
            "аннотируемую реплику",
        ),
        (
            lambda value: value["messages"][0]["annotations"][0]["evidence"].update(
                quote="этой цитаты нет"
            ),
            "точным фрагментом",
        ),
        (
            lambda value: value["expected"]["block_expectations"][0].update(
                evidence_sequences=[2]
            ),
            "только на participant",
        ),
        (lambda value: value["expected"]["score_band"].update(minimum=95), "больше maximum"),
        (lambda value: value.update(dialogue_id="equipment-supply:v1:weak"), "каноническим"),
    ],
)
def test_cross_field_invariants_are_enforced(mutation, error_fragment: str) -> None:
    payload = copy.deepcopy(_valid_payload())
    mutation(payload)

    with pytest.raises(ValidationError, match=error_fragment):
        _validate(payload)


def test_opponent_cannot_carry_participant_annotations() -> None:
    payload = _valid_payload()
    payload["messages"][1]["annotations"] = copy.deepcopy(payload["messages"][0]["annotations"])
    payload["messages"][1]["annotations"][0]["evidence"]["message_sequence"] = 2

    with pytest.raises(ValidationError, match="только реплики участника"):
        _validate(payload)


def test_dialogue_requires_eight_to_fourteen_messages() -> None:
    payload = _valid_payload()
    payload["messages"] = payload["messages"][:6]

    with pytest.raises(ValidationError, match="at least 8 items"):
        _validate(payload)


def test_dialogue_rejects_more_than_fourteen_messages() -> None:
    payload = _valid_payload()
    for sequence in range(9, 16):
        payload["messages"].append(
            {
                "sequence": sequence,
                "role": "participant" if sequence % 2 else "opponent",
                "text": f"Дополнительная реплика номер {sequence}.",
                "annotations": [],
            }
        )

    with pytest.raises(ValidationError, match="at most 14 items"):
        _validate(payload)


def test_first_message_must_belong_to_participant() -> None:
    payload = _valid_payload()
    for index, message in enumerate(payload["messages"]):
        message["role"] = "opponent" if index % 2 == 0 else "participant"
    payload["messages"][0]["annotations"] = []
    payload["messages"][1]["annotations"] = [
        {
            "indicator_id": "I2",
            "methodology_modules": ["active_listening"],
            "rationale": "Участник проверяет понимание.",
            "evidence": {"message_sequence": 2, "quote": "простой после этой даты"},
        }
    ]
    payload["expected"]["block_expectations"][0]["evidence_sequences"] = [2]

    with pytest.raises(ValidationError, match="Первую реплику.*participant"):
        _validate(payload)


def test_message_has_at_most_two_annotations() -> None:
    payload = _valid_payload()
    original = payload["messages"][0]["annotations"][0]
    for indicator_id in ("I3", "I4"):
        annotation = copy.deepcopy(original)
        annotation["indicator_id"] = indicator_id
        payload["messages"][0]["annotations"].append(annotation)

    with pytest.raises(ValidationError, match="at most 2 items"):
        _validate(payload)


def test_case_semantics_are_enforced() -> None:
    payload = _valid_payload()
    payload["expected"]["outcome"] = "impasse"

    with pytest.raises(ValidationError, match="strong_success должен завершаться agreement"):
        _validate(payload)


def test_strong_process_bad_result_cannot_be_an_agreement() -> None:
    payload = _valid_payload()
    payload.update(
        dialogue_id="equipment-supply:v1:strong_process_bad_result",
        case_type="strong_process_bad_result",
    )

    with pytest.raises(ValidationError, match="не может завершаться agreement"):
        _validate(payload)


def test_extra_fields_are_rejected() -> None:
    payload = _valid_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _validate(payload)


def test_rubric_references_and_block_maximum_are_strict() -> None:
    payload = _valid_payload()
    payload["expected"]["block_expectations"][0].update(
        block_id="unknown", maximum_points=25
    )

    with pytest.raises(ValidationError, match="preparation.*process.*value"):
        _validate(payload)

    payload = _valid_payload()
    payload["expected"]["block_expectations"][0]["maximum_points"] = 26
    with pytest.raises(ValidationError, match="не может превышать 20"):
        _validate(payload)

    payload = _valid_payload()
    payload["expected"]["penalties"] = [
        {
            "penalty_id": "penalty.n1",
            "minimum_occurrences": 1,
            "maximum_occurrences": 1,
            "rationale": "Неканоническая ссылка.",
            "evidence_sequences": [1],
        }
    ]
    with pytest.raises(ValidationError, match="penalty.personal_attack"):
        _validate(payload)


def test_all_rubric_blocks_are_required() -> None:
    payload = _valid_payload()
    payload["expected"]["block_expectations"].pop()

    with pytest.raises(ValidationError, match="все пять блоков"):
        _validate(payload)


def _write_payload(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_loader_indexes_nested_corpus_by_scenario_and_case(tmp_path: Path) -> None:
    nested = tmp_path / "equipment-supply"
    nested.mkdir()
    _write_payload(nested / "strong-success.json", _valid_payload())

    catalog = load_golden_dialogue_catalog(tmp_path)

    assert len(catalog.list()) == 1
    assert len(catalog.for_scenario("equipment-supply:v1")) == 1
    assert catalog.get("equipment-supply:v1", "strong_success") is not None
    assert catalog.get("equipment-supply:v1", GoldenCaseType.WEAK) is None


def test_loader_rejects_duplicate_scenario_case_pair(tmp_path: Path) -> None:
    payload = _valid_payload()
    _write_payload(tmp_path / "one.json", payload)
    _write_payload(tmp_path / "two.json", payload)

    with pytest.raises(GoldenDialogueConfigurationError, match="Duplicate golden dialogue"):
        load_golden_dialogue_catalog(tmp_path)


def test_loader_rejects_array_root_and_reports_source(tmp_path: Path) -> None:
    (tmp_path / "invalid.json").write_text("[]", encoding="utf-8")

    with pytest.raises(
        GoldenDialogueConfigurationError, match="invalid.json.*root must be exactly one object"
    ):
        load_golden_dialogue_catalog(tmp_path)


def _published_scenarios() -> dict[str, ScenarioDefinition]:
    definitions = (
        ScenarioDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(DEFAULT_SCENARIOS_PATH.glob("*.json"))
    )
    return {
        item.metadata.version_id: item
        for item in definitions
        if item.metadata.status is ScenarioStatus.PUBLISHED
    }


def test_complete_corpus_covers_every_published_scenario_and_outcome() -> None:
    scenarios = _published_scenarios()
    catalog = load_golden_dialogue_catalog()
    corpus_scenario_ids = {item.scenario_version_id for item in catalog.list()}

    assert corpus_scenario_ids == set(scenarios)
    for scenario_version_id in sorted(scenarios):
        items = catalog.for_scenario(scenario_version_id)
        assert {item.case_type for item in items} == set(GoldenCaseType), scenario_version_id
        assert {item.expected.outcome for item in items} >= {
            DialogueOutcome.AGREEMENT,
            DialogueOutcome.IMPASSE,
            DialogueOutcome.WALK_AWAY,
        }, scenario_version_id


def test_complete_corpus_references_scenario_and_rubric_contracts() -> None:
    scenarios = _published_scenarios()
    errors: list[str] = []

    for dialogue in load_golden_dialogue_catalog().list():
        scenario = scenarios[dialogue.scenario_version_id]
        scenario_methods = set(scenario.methodology_modules)
        role_ids = {role.id for role in scenario.roles}
        if dialogue.rubric_version != DEFAULT_RUBRIC_V01.version:
            errors.append(
                f"{dialogue.dialogue_id}: rubric {dialogue.rubric_version} != "
                f"{DEFAULT_RUBRIC_V01.version}"
            )
        budget_roles = set(dialogue.expected.state_delta.concession_budget_delta)
        if budget_roles != role_ids:
            errors.append(
                f"{dialogue.dialogue_id}: concession roles {sorted(budget_roles)} != "
                f"{sorted(role_ids)}"
            )
        for message in dialogue.messages:
            for annotation in message.annotations:
                invalid = set(annotation.methodology_modules) - scenario_methods
                if invalid:
                    errors.append(
                        f"{dialogue.dialogue_id}#{message.sequence}: annotation methods "
                        f"{sorted(item.value for item in invalid)} are not enabled"
                    )
            alternative = message.alternative_participant_utterance
            if alternative is not None:
                invalid = set(alternative.methodology_modules) - scenario_methods
                if invalid:
                    errors.append(
                        f"{dialogue.dialogue_id}#{message.sequence}: alternative methods "
                        f"{sorted(item.value for item in invalid)} are not enabled"
                    )

    assert not errors, "\n".join(errors)


def test_complete_corpus_score_bands_and_negative_indicators_are_consistent() -> None:
    penalty_points = {item.id: item.points for item in DEFAULT_RUBRIC_V01.penalties}
    indicator_penalties = {
        "N1": "penalty.personal_attack",
        "N2": "penalty.threat",
        "N3": "penalty.unilateral_concession",
        "N4": "penalty.fabricated_fact",
        "N5": "penalty.ignored_concern",
    }
    errors: list[str] = []

    for dialogue in load_golden_dialogue_catalog().list():
        expected = dialogue.expected
        raw_minimum = sum(item.minimum_points for item in expected.block_expectations)
        raw_maximum = sum(item.maximum_points for item in expected.block_expectations)
        worst_penalties = sum(
            penalty_points[item.penalty_id.value] * item.maximum_occurrences
            for item in expected.penalties
        )
        least_penalties = sum(
            penalty_points[item.penalty_id.value] * item.minimum_occurrences
            for item in expected.penalties
        )
        achievable_minimum = max(0, min(100, raw_minimum + worst_penalties))
        achievable_maximum = max(0, min(100, raw_maximum + least_penalties))
        score_band = expected.score_band
        if not (
            achievable_minimum
            <= score_band.minimum
            <= score_band.maximum
            <= achievable_maximum
        ):
            errors.append(
                f"{dialogue.dialogue_id}: declared [{score_band.minimum}, {score_band.maximum}] "
                f"outside achievable [{achievable_minimum}, {achievable_maximum}]"
            )

        penalties_by_id = {item.penalty_id.value: item for item in expected.penalties}
        for message in dialogue.messages:
            for annotation in message.annotations:
                penalty_id = indicator_penalties.get(annotation.indicator_id.value)
                if penalty_id is None:
                    continue
                penalty = penalties_by_id.get(penalty_id)
                if penalty is None:
                    errors.append(
                        f"{dialogue.dialogue_id}#{message.sequence}: "
                        f"{annotation.indicator_id.value} has no {penalty_id} expectation"
                    )
                elif (
                    penalty.minimum_occurrences < 1
                    or message.sequence not in penalty.evidence_sequences
                ):
                    errors.append(
                        f"{dialogue.dialogue_id}#{message.sequence}: "
                        f"{annotation.indicator_id.value} is not evidence for {penalty_id}"
                    )

    assert not errors, "\n".join(errors)
