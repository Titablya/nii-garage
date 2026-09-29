"""Offline analysis of independently reviewed negotiation reports.

This module is deliberately outside the runtime evaluator. It accepts exports
from a controlled review/experiment workflow; it does not create expert labels
or change official scores. The returned object contains aggregates only.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from math import sqrt
from statistics import mean, median, variance
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
BLOCK_MAXIMA = {
    "preparation": 20,
    "process": 25,
    "value": 20,
    "result": 25,
    "relationship": 10,
}
STYLES = {"formal", "conversational", "direct", "empathetic"}
MIN_AGREEMENT_CASES = 20
MIN_CALIBRATION_CASES = 30
MIN_BIAS_GROUP_CASES = 20
MIN_AB_ARM = 30


def _mapping(value: Any, name: str, required: set[str], optional: set[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required - (optional or set())
    if missing or extra:
        raise ValueError(f"{name} keys: missing={sorted(missing)}, unexpected={sorted(extra)}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{name} must be a nonempty string of at most 200 characters")
    return value.strip()


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{name} must be a number from {low} to {high}")
    return float(value)


def _timestamp(value: Any, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must contain a timezone")
    return parsed


def _scores(value: Any, name: str) -> dict[str, float]:
    scores = _mapping(value, name, set(BLOCK_MAXIMA))
    return {block: _number(scores[block], f"{name}.{block}", 0, maximum) for block, maximum in BLOCK_MAXIMA.items()}


def _unavailable(reason: str, **counts: Any) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, **counts}


def _length_band(lengths: list[int]) -> str:
    average = mean(lengths)
    if average < 80:
        return "short_lt_80"
    if average < 240:
        return "medium_80_239"
    return "long_ge_240"


def _parse_cases(raw: Any, rubric_version: str, evaluator_version: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("cases must be an array")
    cases: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(raw):
        name = f"cases[{index}]"
        item = _mapping(value, name, {
            "case_id", "scenario_id", "scenario_version_id", "rubric_version", "evaluator_version",
            "methodology_modules", "participant_turn_lengths", "writing_style", "model_block_scores",
        })
        case_id = _text(item["case_id"], f"{name}.case_id")
        if case_id in cases:
            raise ValueError(f"duplicate case_id: {case_id}")
        if item["rubric_version"] != rubric_version or item["evaluator_version"] != evaluator_version:
            raise ValueError(f"{name} has a different rubric/evaluator version")
        for field in ("scenario_id", "scenario_version_id"):
            _text(item[field], f"{name}.{field}")
        modules = item["methodology_modules"]
        if not isinstance(modules, list) or not modules or not all(isinstance(v, str) and v.strip() for v in modules):
            raise ValueError(f"{name}.methodology_modules must be a nonempty string array")
        if len(modules) != len(set(modules)):
            raise ValueError(f"{name}.methodology_modules contains duplicates")
        lengths = item["participant_turn_lengths"]
        if not isinstance(lengths, list) or not lengths:
            raise ValueError(f"{name}.participant_turn_lengths must be nonempty")
        for length in lengths:
            if isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= 20000:
                raise ValueError(f"{name}.participant_turn_lengths contains an invalid length")
        style = item["writing_style"]
        if not isinstance(style, str) or style not in STYLES:
            raise ValueError(f"{name}.writing_style must be one of {sorted(STYLES)}")
        cases[case_id] = {
            "scenario_id": item["scenario_id"],
            "methodology_modules": modules,
            "style": style,
            "length_band": _length_band(lengths),
            "model_scores": _scores(item["model_block_scores"], f"{name}.model_block_scores"),
        }
    return cases


def _parse_annotations(raw: Any, cases: Mapping[str, Any], analysis_at: datetime) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, list):
        raise ValueError("annotations must be an array")
    annotations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_ids: set[str] = set()
    seen_source_records: set[str] = set()
    seen_case_rater: set[tuple[str, str]] = set()
    for index, value in enumerate(raw):
        name = f"annotations[{index}]"
        item = _mapping(value, name, {
            "annotation_id", "case_id", "rater_id", "source_kind", "source_record_id",
            "review_batch_id", "submitted_at", "blinded_to_model", "blinded_to_peers",
            "block_scores", "evidence_refs",
        })
        annotation_id = _text(item["annotation_id"], f"{name}.annotation_id")
        case_id = _text(item["case_id"], f"{name}.case_id")
        rater_id = _text(item["rater_id"], f"{name}.rater_id")
        if annotation_id in seen_ids or (case_id, rater_id) in seen_case_rater:
            raise ValueError(f"duplicate annotation id or same rater twice on case {case_id}")
        seen_ids.add(annotation_id)
        seen_case_rater.add((case_id, rater_id))
        if case_id not in cases:
            raise ValueError(f"{name}.case_id does not exist")
        if not isinstance(item["source_kind"], str) or item["source_kind"] not in {"real_human_expert", "synthetic", "golden_author", "peer_review"}:
            raise ValueError(f"{name}.source_kind is unsupported")
        source_record_id = _text(item["source_record_id"], f"{name}.source_record_id")
        _text(item["review_batch_id"], f"{name}.review_batch_id")
        if source_record_id in seen_source_records:
            raise ValueError(f"duplicate source_record_id: {source_record_id}")
        seen_source_records.add(source_record_id)
        if _timestamp(item["submitted_at"], f"{name}.submitted_at") > analysis_at:
            raise ValueError(f"{name}.submitted_at is after analysis_at")
        for field in ("blinded_to_model", "blinded_to_peers"):
            if not isinstance(item[field], bool):
                raise ValueError(f"{name}.{field} must be a boolean")
        refs = _mapping(item["evidence_refs"], f"{name}.evidence_refs", set(BLOCK_MAXIMA))
        for block, block_refs in refs.items():
            if not isinstance(block_refs, list) or not block_refs or not all(isinstance(ref, str) and ref.strip() for ref in block_refs):
                raise ValueError(f"{name}.evidence_refs.{block} must contain references")
        annotations[case_id].append({
            "rater_id": rater_id,
            "eligible": item["source_kind"] == "real_human_expert" and item["blinded_to_model"] and item["blinded_to_peers"],
            "scores": _scores(item["block_scores"], f"{name}.block_scores"),
        })
    return annotations


def _alpha_interval(units: list[list[float]]) -> float | None:
    """Krippendorff alpha with squared interval distance and missing raters."""
    paired = [unit for unit in units if len(unit) >= 2]
    values = [score for unit in paired for score in unit]
    total = len(values)
    if total < 2:
        return None
    # sum over unordered squared pair gaps = n * sum(x²) - sum(x)².
    # The identity avoids a quadratic pass over the full annotation pool.
    observed = sum(
        2 * (len(unit) * sum(score * score for score in unit) - sum(unit) ** 2) / (len(unit) - 1)
        for unit in paired
    ) / total
    expected = 2 * (total * sum(score * score for score in values) - sum(values) ** 2) / (total * (total - 1))
    if expected == 0:
        return None  # No score variation: chance-corrected reliability is undefined.
    return 1 - observed / expected


def _agreement(paired: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if len(paired) < MIN_AGREEMENT_CASES:
        return _unavailable(f"at least {MIN_AGREEMENT_CASES} independently double-rated real cases are required", paired_cases=len(paired))
    raters = {annotation["rater_id"] for group in paired.values() for annotation in group}
    if len(raters) < 2:
        return _unavailable("at least two distinct expert raters are required", paired_cases=len(paired))
    def values(block: str | None) -> list[list[float]]:
        return [
            [sum(a["scores"].values()) if block is None else a["scores"][block] for a in group]
            for group in paired.values()
        ]

    def metrics(units: list[list[float]]) -> dict[str, Any]:
        gaps = [abs(left - right) for unit in units for left, right in combinations(unit, 2)]
        return {
            "krippendorff_alpha_interval": _alpha_interval(units),
            "mean_pair_absolute_gap": mean(gaps),
            "pair_comparisons": len(gaps),
        }

    return {
        "status": "available",
        "paired_cases": len(paired),
        "distinct_expert_raters": len(raters),
        "raw_block_total": metrics(values(None)),
        "blocks": {block: metrics(values(block)) for block in BLOCK_MAXIMA},
    }


def _calibrated_cases(cases: Mapping[str, dict[str, Any]], paired: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for case_id, annotations in paired.items():
        case = cases[case_id]
        consensus = {block: median(a["scores"][block] for a in annotations) for block in BLOCK_MAXIMA}
        model = case["model_scores"]
        result.append({
            "case_id": case_id,
            "scenario_id": case["scenario_id"],
            "methodology_modules": case["methodology_modules"],
            "style": case["style"],
            "length_band": case["length_band"],
            "error": sum(model.values()) - sum(consensus.values()),
            "block_errors": {block: model[block] - consensus[block] for block in BLOCK_MAXIMA},
        })
    return result


def _error_metrics(errors: list[float]) -> dict[str, float | int]:
    return {
        "cases": len(errors),
        "mean_absolute_error": mean(abs(error) for error in errors),
        "mean_signed_error": mean(errors),
        "within_10_points_rate": mean(abs(error) <= 10 for error in errors),
    }


def _calibration(calibrated: list[dict[str, Any]]) -> dict[str, Any]:
    if len(calibrated) < MIN_CALIBRATION_CASES:
        return _unavailable(f"at least {MIN_CALIBRATION_CASES} paired real cases are required", paired_cases=len(calibrated))
    return {
        "status": "available",
        "reference": "median of independently blinded human expert block scores",
        "model_measure": "sum of five raw rubric blocks; excludes penalties and score caps",
        "raw_block_total": _error_metrics([case["error"] for case in calibrated]),
        "blocks": {
            block: _error_metrics([case["block_errors"][block] for case in calibrated])
            for block in BLOCK_MAXIMA
        },
    }


def _bias_axis(calibrated: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for case in calibrated:
        grouped[case[field]].append(case["error"])
    eligible = {key: values for key, values in grouped.items() if len(values) >= MIN_BIAS_GROUP_CASES}
    if len(eligible) < 2:
        return _unavailable(
            f"at least two groups with {MIN_BIAS_GROUP_CASES} paired real cases each are required",
            group_counts={key: len(values) for key, values in sorted(grouped.items())},
        )
    summary = {key: _error_metrics(values) for key, values in sorted(eligible.items())}
    return {
        "status": "available",
        "groups": summary,
        "excluded_small_groups": {key: len(values) for key, values in sorted(grouped.items()) if key not in eligible},
        "mae_range": max(group["mean_absolute_error"] for group in summary.values()) - min(group["mean_absolute_error"] for group in summary.values()),
        "signed_error_range": max(group["mean_signed_error"] for group in summary.values()) - min(group["mean_signed_error"] for group in summary.values()),
        "interpretation": "descriptive disparity; scenario mix and true skill may confound it",
    }


def _bias(calibrated: list[dict[str, Any]]) -> dict[str, Any]:
    if len(calibrated) < 2 * MIN_BIAS_GROUP_CASES:
        return _unavailable(f"at least {2 * MIN_BIAS_GROUP_CASES} paired real cases are required", paired_cases=len(calibrated))
    style = _bias_axis(calibrated, "style")
    length = _bias_axis(calibrated, "length_band")
    if style["status"] == length["status"] == "unavailable":
        return _unavailable(
            "no writing-style or response-length axis has two sufficiently sized groups",
            writing_style=style,
            response_length=length,
        )
    return {"status": "available", "writing_style": style, "response_length": length}


def _ab_outcome_metrics(arms: dict[str, list[float]], retries: Counter[str]) -> dict[str, Any]:
    """Arithmetic only; provenance and sample gates belong to _experiment."""
    treatment = arms["personalized"]
    control = arms["generic"]
    effect = mean(treatment) - mean(control)
    standard_error = sqrt(variance(treatment) / len(treatment) + variance(control) / len(control))
    return {
        "arms": {
            arm: {
                "mature_randomized": len(values),
                "retried_in_window": retries[arm],
                "retry_rate": retries[arm] / len(values),
                "mean_change": mean(values),
            }
            for arm, values in arms.items()
        },
        "personalized_minus_generic": effect,
        "approximate_95_percent_interval": [effect - 1.96 * standard_error, effect + 1.96 * standard_error],
    }


def _experiment(raw: Any, analysis_at: datetime, rubric_version: str, evaluator_version: str) -> dict[str, Any]:
    if raw is None:
        return _unavailable("no randomized recommendation experiment was supplied")
    experiment = _mapping(raw, "experiment", {
        "experiment_id", "source_kind", "analysis_plan_id", "registered_at", "allocation_method",
        "outcome_window_days", "assignments",
    })
    for key in ("experiment_id", "analysis_plan_id"):
        _text(experiment[key], f"experiment.{key}")
    registered_at = _timestamp(experiment["registered_at"], "experiment.registered_at")
    window = experiment["outcome_window_days"]
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 90:
        raise ValueError("experiment.outcome_window_days must be an integer from 1 to 90")
    raw_assignments = experiment["assignments"]
    if not isinstance(raw_assignments, list):
        raise ValueError("experiment.assignments must be an array")
    if experiment["source_kind"] != "real_server_events" or experiment["allocation_method"] != "server_randomized":
        return _unavailable("only real server-randomized assignment logs are eligible", assignments=len(raw_assignments))
    if registered_at >= analysis_at:
        return _unavailable("the analysis plan must be registered before analysis")
    seen_participants: set[str] = set()
    seen_assignments: set[str] = set()
    arms: dict[str, list[float]] = {"personalized": [], "generic": []}
    retries = Counter()
    immature = 0
    for index, value in enumerate(raw_assignments):
        name = f"experiment.assignments[{index}]"
        item = _mapping(value, name, {
            "assignment_id", "participant_id", "arm", "assignment_at", "randomized", "source_kind",
            "baseline_score", "next_score", "next_attempt_at", "rubric_version", "evaluator_version",
        })
        assignment_id = _text(item["assignment_id"], f"{name}.assignment_id")
        participant_id = _text(item["participant_id"], f"{name}.participant_id")
        if assignment_id in seen_assignments or participant_id in seen_participants:
            raise ValueError("duplicate assignment or participant in experiment")
        seen_assignments.add(assignment_id)
        seen_participants.add(participant_id)
        if not isinstance(item["arm"], str) or item["arm"] not in arms:
            raise ValueError(f"{name}.arm must be personalized or generic")
        assigned_at = _timestamp(item["assignment_at"], f"{name}.assignment_at")
        if assigned_at > analysis_at:
            raise ValueError(f"{name}.assignment_at is after analysis_at")
        if item["randomized"] is not True or item["source_kind"] != "real_server_event":
            return _unavailable("an assignment lacks a real randomization event", assignments=len(raw_assignments))
        if assigned_at < registered_at:
            return _unavailable("assignments precede registration of the analysis plan", assignments=len(raw_assignments))
        if item["rubric_version"] != rubric_version or item["evaluator_version"] != evaluator_version:
            return _unavailable("experiment scores mix evaluator or rubric versions", assignments=len(raw_assignments))
        baseline = _number(item["baseline_score"], f"{name}.baseline_score", 0, 100)
        next_score = item["next_score"]
        next_at = item["next_attempt_at"]
        if (next_score is None) != (next_at is None):
            raise ValueError(f"{name} must contain both next_score and next_attempt_at, or neither")
        if next_score is not None:
            next_score = _number(next_score, f"{name}.next_score", 0, 100)
            next_at = _timestamp(next_at, f"{name}.next_attempt_at")
            if not assigned_at < next_at <= analysis_at:
                raise ValueError(f"{name}.next_attempt_at must follow assignment and precede analysis")
        if assigned_at + timedelta(days=window) > analysis_at:
            immature += 1
            continue
        followed = next_at is not None and next_at <= assigned_at + timedelta(days=window)
        if followed:
            retries[item["arm"]] += 1
        arms[item["arm"]].append(next_score - baseline if followed else 0.0)
    if any(len(values) < MIN_AB_ARM for values in arms.values()):
        return _unavailable(
            f"at least {MIN_AB_ARM} mature real randomized assignments per arm are required",
            mature_by_arm={arm: len(values) for arm, values in arms.items()},
            immature_assignments=immature,
        )
    return {
        "status": "available",
        "experiment_id": experiment["experiment_id"],
        "analysis_plan_id": experiment["analysis_plan_id"],
        "estimand": "difference in mean next-attempt score change within the window; no retry counts as zero change",
        **_ab_outcome_metrics(arms, retries),
        "immature_assignments_excluded": immature,
        "interpretation": "exploratory; review allocation integrity, missing events, and the registered plan before causal claims",
    }


def analyze_quality_lab(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an offline export and return safe aggregates with explicit gates.

    Human provenance and blinding are attestations from the export process. A
    report cannot itself prove reviewer identity or independent collection.
    """
    root = _mapping(payload, "quality_lab", {
        "schema_version", "analysis_at", "rubric_version", "evaluator_version", "cases", "annotations",
    }, {"experiment"})
    if root["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported quality_lab schema_version: {root['schema_version']}")
    if root["rubric_version"] != "0.1":
        raise ValueError("this quality lab contract supports rubric 0.1 only; map new versions explicitly")
    evaluator_version = _text(root["evaluator_version"], "evaluator_version")
    rubric_version = "0.1"
    analysis_at = _timestamp(root["analysis_at"], "analysis_at")
    cases = _parse_cases(root["cases"], rubric_version, evaluator_version)
    annotations = _parse_annotations(root["annotations"], cases, analysis_at)
    paired = {
        case_id: eligible
        for case_id, group in annotations.items()
        if len(eligible := [annotation for annotation in group if annotation["eligible"]]) >= 2
    }
    calibrated = _calibrated_cases(cases, paired)
    return {
        "schema_version": SCHEMA_VERSION,
        "rubric_version": rubric_version,
        "evaluator_version": evaluator_version,
        "coverage": {
            "cases": len(cases),
            "annotations": sum(map(len, annotations.values())),
            "eligible_independent_expert_annotations": sum(sum(a["eligible"] for a in group) for group in annotations.values()),
            "paired_real_expert_cases": len(paired),
            "paired_cases_by_methodology": dict(sorted(Counter(
                module for case_id in paired for module in cases[case_id]["methodology_modules"]
            ).items())),
        },
        "inter_rater_agreement": _agreement(paired),
        "model_vs_expert": _calibration(calibrated),
        "descriptive_bias": _bias(calibrated),
        "recommendation_ab": _experiment(root.get("experiment"), analysis_at, rubric_version, evaluator_version),
        "limitations": [
            "Reliability is not construct validity or proof that the rubric measures negotiation skill.",
            "Human provenance, blinding, and randomization must be audited against source records.",
            "No result authorizes personnel decisions without separate validation.",
        ],
    }
