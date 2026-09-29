from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.rubric import DEFAULT_RUBRIC_V01, RubricDefinition
from app.domain.scenario import ScenarioDefinition


SCENARIO_DIR = Path(__file__).parents[1] / "scenarios"


def load_raw(name: str = "equipment-supply.v1.json") -> dict[str, Any]:
    return json.loads((SCENARIO_DIR / name).read_text(encoding="utf-8"))


def validate(raw: dict[str, Any]) -> ScenarioDefinition:
    return ScenarioDefinition.model_validate_json(json.dumps(raw, ensure_ascii=False))


@pytest.mark.parametrize("filename", ["equipment-supply.v1.json", "project-resources.v1.json"])
def test_published_scenario_files_are_valid(filename: str) -> None:
    scenario = ScenarioDefinition.model_validate_json((SCENARIO_DIR / filename).read_text(encoding="utf-8"))

    assert scenario.metadata.version_id == f"{scenario.metadata.id}:v{scenario.metadata.version}"
    assert sum(issue.party_weights[scenario.roles[0].id] for issue in scenario.issues) == 100
    assert {item.issue_id for item in scenario.zopa} == {issue.id for issue in scenario.issues}
    assert scenario.rubric_version == DEFAULT_RUBRIC_V01.version


def test_rubric_contract_and_json_schema_are_valid() -> None:
    restored = RubricDefinition.model_validate_json(DEFAULT_RUBRIC_V01.model_dump_json())
    schema = ScenarioDefinition.model_json_schema()
    exported_schema = json.loads(
        (Path(__file__).parents[3] / "docs" / "schema" / "scenario.schema.json").read_text(encoding="utf-8")
    )

    assert restored.total_points == 100
    assert sum(block.max_points for block in restored.blocks) == 100
    assert schema["additionalProperties"] is False
    assert "metadata" in schema["required"]
    assert exported_schema == schema


def test_rubric_rejects_inconsistent_total() -> None:
    raw = json.loads(DEFAULT_RUBRIC_V01.model_dump_json())
    raw["blocks"][0]["max_points"] = 19
    raw["blocks"][0]["criteria"][1]["max_points"] = 9

    with pytest.raises(ValidationError, match="Сумма блоков рубрики должна быть равна total_points"):
        RubricDefinition.model_validate_json(json.dumps(raw, ensure_ascii=False))


def test_models_are_strict_and_version_identity_is_frozen() -> None:
    raw = load_raw()
    raw["unexpected"] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate(raw)

    scenario = validate(load_raw())
    with pytest.raises(ValidationError, match="Instance is frozen"):
        scenario.metadata.version = 2  # type: ignore[misc]


def test_version_id_must_match_scenario_id_and_integer_version() -> None:
    raw = load_raw()
    raw["metadata"]["version_id"] = "equipment-supply:v2"

    with pytest.raises(ValidationError, match="version_id должен быть каноническим"):
        validate(raw)


def test_ids_must_be_unique_across_graph_collections() -> None:
    raw = load_raw()
    raw["issues"][1]["id"] = raw["issues"][0]["id"]

    with pytest.raises(ValidationError, match="issues: id должны быть уникальны"):
        validate(raw)


@pytest.mark.parametrize(
    ("direction", "reservation", "aspiration"),
    [("maximize", 80.0, 40.0), ("minimize", 20.0, 70.0)],
)
def test_aspiration_must_be_better_than_reservation(
    direction: str, reservation: float, aspiration: float
) -> None:
    raw = load_raw()
    price_range = raw["issues"][0]["party_ranges"]["buyer"]
    price_range.update(
        {"minimum": 0.0, "maximum": 100.0, "direction": direction, "reservation": reservation, "aspiration": aspiration}
    )

    with pytest.raises(ValidationError, match="aspiration должен быть"):
        validate(raw)


def test_issue_weights_must_total_one_hundred_for_each_party() -> None:
    raw = load_raw()
    raw["issues"][0]["party_weights"]["buyer"] = 34.0

    with pytest.raises(ValidationError, match="Сумма весов вопросов для роли buyer должна быть равна 100"):
        validate(raw)


def test_zopa_must_cover_every_issue_exactly_once() -> None:
    raw = load_raw()
    raw["zopa"].pop()

    with pytest.raises(ValidationError, match="ZOPA должна содержать все и только вопросы сценария"):
        validate(raw)


def test_zopa_bounds_must_match_party_reservation_points() -> None:
    raw = load_raw()
    raw["zopa"][0]["lower"] = 9400000.0

    with pytest.raises(ValidationError, match="Границы ZOPA вопроса price не соответствуют reservation point сторон"):
        validate(raw)


def test_public_briefing_must_not_repeat_hidden_information() -> None:
    raw = load_raw()
    secret = raw["roles"][1]["hidden_interests"][0]["description"]
    raw["public_briefing"]["known_facts"].append(secret)

    with pytest.raises(ValidationError, match="Публичный брифинг содержит скрытые данные"):
        validate(raw)


def test_context_method_must_apply_to_negotiation_type() -> None:
    raw = load_raw()
    raw["methodology_modules"].append("spin")

    with pytest.raises(ValidationError, match="Методы не применимы к типу procurement: spin"):
        validate(raw)


def test_meso_requires_equivalent_simultaneous_offers() -> None:
    raw = load_raw()
    for offer in raw["offer_templates"]:
        offer["equivalent_group"] = None

    with pytest.raises(ValidationError, match="MESO требует минимум два предложения"):
        validate(raw)


def test_all_references_must_point_to_declared_entities() -> None:
    raw = deepcopy(load_raw())
    raw["trade_options"][0]["receive_issue_id"] = "unknown_issue"

    with pytest.raises(ValidationError, match="содержит неизвестные ссылки: unknown_issue"):
        validate(raw)


def test_published_version_requires_publication_timestamp() -> None:
    raw = load_raw()
    raw["metadata"]["published_at"] = None

    with pytest.raises(ValidationError, match="У опубликованной версии должен быть published_at"):
        validate(raw)
