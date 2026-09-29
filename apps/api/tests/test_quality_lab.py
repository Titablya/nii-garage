from __future__ import annotations

from collections import Counter
from copy import deepcopy

import pytest

from app.quality_lab import (
    _ab_outcome_metrics,
    _alpha_interval,
    _length_band,
    analyze_quality_lab,
)


def _empty() -> dict:
    return {
        "schema_version": "1.0",
        "analysis_at": "2026-09-27T00:00:00Z",
        "rubric_version": "0.1",
        "evaluator_version": "1.0",
        "cases": [],
        "annotations": [],
        "experiment": None,
    }


def _case(number: int) -> dict:
    return {
        "case_id": f"case-{number}",
        "scenario_id": "equipment-supply",
        "scenario_version_id": "version-1",
        "rubric_version": "0.1",
        "evaluator_version": "1.0",
        "methodology_modules": ["principled_negotiation"],
        "participant_turn_lengths": [60 + number],
        "writing_style": "direct",
        "model_block_scores": {"preparation": 10, "process": 12, "value": 10, "result": 13, "relationship": 5},
    }


def _synthetic_annotation(number: int, rater: int) -> dict:
    return {
        "annotation_id": f"annotation-{number}-{rater}",
        "case_id": f"case-{number}",
        "rater_id": f"synthetic-rater-{rater}",
        "source_kind": "synthetic",
        "source_record_id": f"synthetic-record-{number}-{rater}",
        "review_batch_id": "synthetic-test-batch",
        "submitted_at": "2026-09-26T00:00:00Z",
        "blinded_to_model": True,
        "blinded_to_peers": True,
        "block_scores": {"preparation": 10, "process": 12, "value": 10, "result": 13, "relationship": 5},
        "evidence_refs": {block: [f"turn-{number}"] for block in ("preparation", "process", "value", "result", "relationship")},
    }


def test_empty_export_withholds_all_results() -> None:
    report = analyze_quality_lab(_empty())
    assert report["coverage"]["paired_real_expert_cases"] == 0
    assert report["inter_rater_agreement"]["status"] == "unavailable"
    assert report["model_vs_expert"]["status"] == "unavailable"
    assert report["descriptive_bias"]["status"] == "unavailable"
    assert report["recommendation_ab"]["status"] == "unavailable"


def test_many_synthetic_annotations_never_unlock_expert_metrics() -> None:
    payload = _empty()
    payload["cases"] = [_case(number) for number in range(100)]
    payload["annotations"] = [
        _synthetic_annotation(number, rater) for number in range(100) for rater in (1, 2)
    ]
    report = analyze_quality_lab(payload)
    assert report["coverage"]["annotations"] == 200
    assert report["coverage"]["eligible_independent_expert_annotations"] == 0
    assert report["coverage"]["paired_real_expert_cases"] == 0
    assert report["inter_rater_agreement"]["status"] == "unavailable"
    assert report["model_vs_expert"]["status"] == "unavailable"
    assert report["descriptive_bias"]["status"] == "unavailable"
    assert "case-0" not in str(report)


def test_same_reviewer_cannot_submit_twice_on_one_case() -> None:
    payload = _empty()
    payload["cases"] = [_case(1)]
    first = _synthetic_annotation(1, 1)
    second = deepcopy(first)
    second["annotation_id"] = "another-annotation"
    second["source_record_id"] = "another-source-record"
    payload["annotations"] = [first, second]
    with pytest.raises(ValueError, match="same rater twice"):
        analyze_quality_lab(payload)


def test_one_source_record_cannot_be_reused_for_two_reviews() -> None:
    payload = _empty()
    payload["cases"] = [_case(1)]
    first = _synthetic_annotation(1, 1)
    second = _synthetic_annotation(1, 2)
    second["source_record_id"] = first["source_record_id"]
    payload["annotations"] = [first, second]
    with pytest.raises(ValueError, match="duplicate source_record_id"):
        analyze_quality_lab(payload)


def test_unblinded_claim_cannot_unlock_metrics() -> None:
    payload = _empty()
    payload["cases"] = [_case(1)]
    review = _synthetic_annotation(1, 1)
    review["source_kind"] = "real_human_expert"
    review["blinded_to_model"] = False
    payload["annotations"] = [review]
    report = analyze_quality_lab(payload)
    assert report["coverage"]["eligible_independent_expert_annotations"] == 0


def test_interval_alpha_math_and_degenerate_variation() -> None:
    assert _alpha_interval([[0, 0], [10, 10], [20, 20]]) == pytest.approx(1)
    assert _alpha_interval([[0, 1], [0, 1]]) == pytest.approx(-0.5)
    assert _alpha_interval([[5, 5], [5, 5]]) is None


def test_length_bands_are_fixed_before_observing_results() -> None:
    assert _length_band([79]) == "short_lt_80"
    assert _length_band([80, 239]) == "medium_80_239"
    assert _length_band([240]) == "long_ge_240"


def test_nonrandom_experiment_never_reports_effect() -> None:
    payload = _empty()
    payload["experiment"] = {
        "experiment_id": "test-experiment",
        "source_kind": "synthetic",
        "analysis_plan_id": "test-plan",
        "registered_at": "2026-09-01T00:00:00Z",
        "allocation_method": "manual",
        "outcome_window_days": 14,
        "assignments": [],
    }
    report = analyze_quality_lab(payload)
    assert report["recommendation_ab"]["status"] == "unavailable"
    assert "randomized" in report["recommendation_ab"]["reason"]


def test_ab_effect_arithmetic_is_separate_from_provenance() -> None:
    metrics = _ab_outcome_metrics(
        {"personalized": [10, 0, -2], "generic": [2, 0, 1]},
        Counter({"personalized": 2, "generic": 2}),
    )
    assert metrics["personalized_minus_generic"] == pytest.approx(5 / 3)
    assert metrics["arms"]["personalized"]["retry_rate"] == pytest.approx(2 / 3)


def test_version_mixing_requires_explicit_mapping() -> None:
    payload = _empty()
    payload["cases"] = [_case(1)]
    payload["cases"][0]["rubric_version"] = "0.2"
    with pytest.raises(ValueError, match="different rubric/evaluator version"):
        analyze_quality_lab(payload)


def test_sufficient_mock_review_records_exercise_all_aggregate_paths() -> None:
    # These are unit-test records only, not collected expert annotations.
    payload = _empty()
    payload["cases"] = [_case(number) for number in range(40)]
    payload["annotations"] = []
    for number, case in enumerate(payload["cases"]):
        case["writing_style"] = "formal" if number < 20 else "direct"
        case["participant_turn_lengths"] = [60 if number < 20 else 260]
        for rater in (1, 2):
            review = _synthetic_annotation(number, rater)
            review["source_kind"] = "real_human_expert"
            review["rater_id"] = f"expert-{rater}"
            review["block_scores"]["preparation"] = 8 + number % 5 + (rater - 1)
            payload["annotations"].append(review)
    report = analyze_quality_lab(payload)
    assert report["coverage"]["paired_real_expert_cases"] == 40
    assert report["inter_rater_agreement"]["status"] == "available"
    assert report["inter_rater_agreement"]["raw_block_total"]["krippendorff_alpha_interval"] is not None
    assert report["model_vs_expert"]["status"] == "available"
    assert report["descriptive_bias"]["status"] == "available"
    assert report["descriptive_bias"]["writing_style"]["status"] == "available"
    assert report["descriptive_bias"]["response_length"]["status"] == "available"


def test_mature_mock_randomized_records_exercise_ab_analysis() -> None:
    # Attestation gates are tested here; real allocation needs an external log audit.
    payload = _empty()
    payload["experiment"] = {
        "experiment_id": "test-recommendations",
        "source_kind": "real_server_events",
        "analysis_plan_id": "registered-test-plan",
        "registered_at": "2026-09-01T00:00:00Z",
        "allocation_method": "server_randomized",
        "outcome_window_days": 7,
        "assignments": [],
    }
    for number in range(60):
        arm = "personalized" if number % 2 == 0 else "generic"
        payload["experiment"]["assignments"].append({
            "assignment_id": f"assignment-{number}",
            "participant_id": f"participant-{number}",
            "arm": arm,
            "assignment_at": "2026-09-02T00:00:00Z",
            "randomized": True,
            "source_kind": "real_server_event",
            "baseline_score": 50,
            "next_score": 60 if arm == "personalized" else 53,
            "next_attempt_at": "2026-09-03T00:00:00Z",
            "rubric_version": "0.1",
            "evaluator_version": "1.0",
        })
    report = analyze_quality_lab(payload)
    experiment = report["recommendation_ab"]
    assert experiment["status"] == "available"
    assert experiment["arms"]["personalized"]["mature_randomized"] == 30
    assert experiment["arms"]["generic"]["mature_randomized"] == 30
    assert experiment["personalized_minus_generic"] == pytest.approx(7)
