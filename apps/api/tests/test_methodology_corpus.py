"""Hand-authored regression expectations for negotiation methodology.

These fixtures are executable examples, not independent expert annotations or
evidence of inter-rater agreement. The corpus provenance is kept in the JSON.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import pytest

from app.domain.scenario import MethodologyModule, PreferenceDirection, ScenarioDefinition
from app.engine import assess_offer, classify_action, initial_state, make_offer, transition_turn
from app.engine.contracts import IssueValue
from app.models import Message, NegotiationSession, SessionStatus
from app.reporting import evaluate_session
from app.scenario_catalog import DEFAULT_SCENARIOS_PATH, load_scenario_catalog


CORPUS_PATH = Path(__file__).with_name("methodology_corpus.json")
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


@cache
def _scenario(scenario_id: str) -> ScenarioDefinition:
    scenario = load_scenario_catalog(DEFAULT_SCENARIOS_PATH).get_definition(scenario_id)
    assert scenario is not None, scenario_id
    return scenario


def _midpoint_offer(scenario: ScenarioDefinition, *, changed_issue: str, value: float):
    values = {
        item.issue_id: (item.lower + item.upper) / 2
        for item in scenario.zopa
        if item.status == "overlap"
    }
    assert len(values) == len(scenario.issues), scenario.metadata.id
    assert changed_issue in values, changed_issue
    values[changed_issue] = value
    return make_offer(
        scenario.public_briefing.participant_role_id,
        tuple(IssueValue(issue_id=key, value=issue_value) for key, issue_value in values.items()),
        source_turn=1,
    )


def _report_for_dialogue(case: dict):
    scenario = _scenario(case["scenario_id"])
    state = initial_state(scenario)
    messages: list[Message] = []
    for item in case["messages"]:
        messages.append(Message(role=item["role"], content=item["text"]))
        if item["role"] == "participant":
            state = transition_turn(scenario, state, item["text"]).state
    session = NegotiationSession(
        scenario_id=scenario.metadata.id,
        scenario_version_id=scenario.metadata.version_id,
        engine_state=state,
        status=SessionStatus.COMPLETED,
        messages=messages,
    )
    return evaluate_session(scenario, session), messages


def test_corpus_provenance_and_supported_methodology_coverage() -> None:
    provenance = CORPUS["provenance"]
    assert provenance == {
        "label_source": "hand_authored_regression_expectations",
        "independent_expert_raters": 0,
        "expert_annotation_count": 0,
        "inter_rater_agreement": None,
    }

    sections = ("utterances", "dialogues", "benefit_directions", "boundary_offers")
    all_cases = [case for section in sections for case in CORPUS[section]]
    ids = [case["id"] for case in all_cases]
    assert len(ids) == len(set(ids)), "Corpus case IDs must be unique"

    covered = set()
    for case in (*CORPUS["utterances"], *CORPUS["dialogues"]):
        scenario_methods = {module.value for module in _scenario(case["scenario_id"]).methodology_modules}
        assert case["methodologies"], case["id"]
        assert set(case["methodologies"]) <= scenario_methods, case["id"]
        covered.update(case["methodologies"])

    published_methods = {
        module.value
        for scenario_id in ("equipment-supply", "project-resources", "random-roadmap-conflict")
        for module in _scenario(scenario_id).methodology_modules
    }
    assert covered == published_methods
    assert set(CORPUS["coverage_gap_without_native_scenario"]) == {
        module.value for module in MethodologyModule
    } - published_methods


@pytest.mark.parametrize("case", CORPUS["utterances"], ids=lambda case: case["id"])
def test_hand_authored_russian_utterance_boundaries(case: dict) -> None:
    scenario = _scenario(case["scenario_id"])
    action = classify_action(scenario, initial_state(scenario), case["text"])
    tags = {tag.value for tag in action.tags}

    assert set(case["required_tags"]) <= tags
    assert not set(case["forbidden_tags"]) & tags
    if "issue_values" in case:
        assert {item.issue_id: item.value for item in action.issue_values} == case["issue_values"]
    if "equivalent_packages" in case:
        packages = case["equivalent_packages"]
        assert len(packages) in (2, 3) and len({tuple(sorted(item.items())) for item in packages}) == len(packages)
        proposer_role = scenario.public_briefing.participant_role_id
        utilities = []
        for package in packages:
            offer = make_offer(
                proposer_role,
                tuple(IssueValue(issue_id=key, value=value) for key, value in package.items()),
                source_turn=1,
            )
            assessment = assess_offer(scenario, offer)
            assert assessment.complete
            utilities.append(next(item.utility for item in assessment.role_utilities if item.role_id == proposer_role))
        assert max(utilities) - min(utilities) <= case["max_proposer_utility_spread"]


@pytest.mark.parametrize("case", CORPUS["dialogues"], ids=lambda case: case["id"])
def test_hand_authored_dialogue_report_boundaries(case: dict) -> None:
    report, messages = _report_for_dialogue(case)
    strengths = {item.code for item in report.strengths}
    penalties = {item.id for item in report.penalties}
    criteria = {item.id: item for block in report.blocks for item in block.criteria}
    participant_messages = {item.id: item.content for item in messages if item.role == "participant"}

    assert set(case["required_strengths"]) <= strengths
    assert not set(case["forbidden_strengths"]) & strengths
    assert set(case["required_penalties"]) <= penalties
    assert not set(case["forbidden_penalties"]) & penalties
    for criterion_id, bounds in case["criterion_points"].items():
        score = criteria[criterion_id].score
        assert score >= bounds.get("minimum", 0), criterion_id
        assert score <= bounds.get("maximum", criteria[criterion_id].max_score), criterion_id
    if "minimum_trust_delta" in case:
        assert report.trajectory[-1].trust - report.trajectory[0].trust >= case["minimum_trust_delta"]

    for finding in (*report.strengths, *report.penalties):
        for evidence in finding.evidence:
            assert evidence.message_id in participant_messages
            assert evidence.quote.rstrip("…") in participant_messages[evidence.message_id]


@pytest.mark.parametrize("case", CORPUS["benefit_directions"], ids=lambda case: case["id"])
def test_role_benefit_direction_with_isolated_issue_change(case: dict) -> None:
    scenario = _scenario(case["scenario_id"])
    lower = assess_offer(
        scenario,
        _midpoint_offer(scenario, changed_issue=case["issue_id"], value=case["lower_value"]),
    )
    higher = assess_offer(
        scenario,
        _midpoint_offer(scenario, changed_issue=case["issue_id"], value=case["higher_value"]),
    )
    lower_utilities = {item.role_id: item.utility for item in lower.role_utilities}
    higher_utilities = {item.role_id: item.utility for item in higher.role_utilities}
    issue = next(item for item in scenario.issues if item.id == case["issue_id"])

    assert case["lower_value"] < case["higher_value"]
    assert set(lower_utilities) == {case["lower_favors_role"], case["higher_favors_role"]}
    assert issue.party_ranges[case["lower_favors_role"]].direction is PreferenceDirection.MINIMIZE
    assert issue.party_ranges[case["higher_favors_role"]].direction is PreferenceDirection.MAXIMIZE
    assert lower_utilities[case["lower_favors_role"]] > higher_utilities[case["lower_favors_role"]]
    assert higher_utilities[case["higher_favors_role"]] > lower_utilities[case["higher_favors_role"]]


@pytest.mark.parametrize("case", CORPUS["boundary_offers"], ids=lambda case: case["id"])
def test_offer_boundary_identifies_the_role_whose_limit_is_crossed(case: dict) -> None:
    scenario = _scenario(case["scenario_id"])
    offer = _midpoint_offer(scenario, changed_issue=case["issue_id"], value=case["value"])
    assessment = assess_offer(scenario, offer)

    assert assessment.complete
    assert not assessment.acceptable_for_all
    assert {(item.role_id, item.issue_id) for item in assessment.reservation_violations} == {
        (case["violated_role"], case["issue_id"])
    }
    assert set(assessment.zopa_violation_issue_ids) == {case["issue_id"]}
