"""Deterministic comparison of immutable negotiation attempts."""

from __future__ import annotations

from .models import (
    AttemptBlockDelta,
    AttemptComparisonResponse,
    AttemptSnapshot,
    AttemptTaskDelta,
    HistoricalAttemptComparisonResponse,
    NegotiationSession,
    ReportResponse,
    SessionStatus,
)
from .scenario_catalog import ScenarioCatalog


def _validate_attempts(
    catalog: ScenarioCatalog,
    previous_session: NegotiationSession,
    current_session: NegotiationSession,
    previous_report: ReportResponse,
    current_report: ReportResponse,
) -> None:
    if previous_session.status != SessionStatus.COMPLETED or current_session.status != SessionStatus.COMPLETED:
        raise ValueError("attempts_must_be_completed")
    if previous_session.series_id != current_session.series_id:
        raise ValueError("attempt_series_mismatch")
    if previous_session.scenario_version_id != current_session.scenario_version_id:
        raise ValueError("scenario_version_mismatch")
    if previous_session.completed_at is None or current_session.completed_at is None:
        raise ValueError("completion_timestamp_missing")
    if previous_report.session_id != previous_session.id or current_report.session_id != current_session.id:
        raise ValueError("report_session_mismatch")
    if catalog.get(current_session.scenario_id) is None:
        raise ValueError("scenario_unavailable")


def _snapshot(session: NegotiationSession, report: ReportResponse) -> AttemptSnapshot:
    if session.completed_at is None:
        raise ValueError("completion_timestamp_missing")
    return AttemptSnapshot(
        session_id=session.id,
        attempt_number=session.attempt_number,
        rubric_version=report.rubric_version,
        evaluator_version=report.evaluator_version,
        score=report.score,
        level=report.level,
        outcome_kind=report.outcome.kind,
        outcome_label=report.outcome.label,
        turns=sum(message.role == "participant" for message in session.messages),
        tasks_met=sum(item.status == "met" for item in report.task_checks),
        tasks_total=len(report.task_checks),
        completed_at=session.completed_at,
    )


def historical_attempts(
    catalog: ScenarioCatalog,
    previous_session: NegotiationSession,
    current_session: NegotiationSession,
    previous_report: ReportResponse,
    current_report: ReportResponse,
) -> HistoricalAttemptComparisonResponse:
    """Display immutable attempts even when their scoring versions differ.

    This endpoint does not apply an unvalidated score or criterion mapping.
    """
    _validate_attempts(catalog, previous_session, current_session, previous_report, current_report)
    versions_match = (
        previous_report.rubric_version == current_report.rubric_version
        and previous_report.evaluator_version == current_report.evaluator_version
    )
    summary = (
        "Отчёты построены по одной версии рубрики и оценщика. Для дельт используйте обычное сравнение."
        if versions_match else
        "Отчёты построены по разным версиям рубрики или оценщика. Баллы показаны отдельно; "
        "дельта без проверенного сопоставления версий не вычисляется."
    )
    return HistoricalAttemptComparisonResponse(
        series_id=current_session.series_id,
        scenario_id=current_session.scenario_id,
        scenario_title=current_session.configuration.topic,
        previous=_snapshot(previous_session, previous_report),
        current=_snapshot(current_session, current_report),
        versions_match=versions_match,
        summary=summary,
    )


def compare_attempts(
    catalog: ScenarioCatalog,
    previous_session: NegotiationSession,
    current_session: NegotiationSession,
    previous_report: ReportResponse,
    current_report: ReportResponse,
) -> AttemptComparisonResponse:
    _validate_attempts(catalog, previous_session, current_session, previous_report, current_report)
    if previous_report.rubric_version != current_report.rubric_version:
        raise ValueError("rubric_version_mismatch")
    if previous_report.evaluator_version != current_report.evaluator_version:
        raise ValueError("evaluator_version_mismatch")

    previous_blocks = {item.id: item for item in previous_report.blocks}
    current_blocks = {item.id: item for item in current_report.blocks}
    if set(previous_blocks) != set(current_blocks):
        raise ValueError("rubric_blocks_mismatch")
    if any(previous_blocks[item.id].max_score != item.max_score for item in current_report.blocks):
        raise ValueError("rubric_block_weights_mismatch")
    block_deltas = [
        AttemptBlockDelta(
            block_id=block.id,
            title=block.title,
            previous_score=previous_blocks[block.id].score,
            current_score=block.score,
            max_score=block.max_score,
            delta=block.score - previous_blocks[block.id].score,
        )
        for block in current_report.blocks
    ]

    previous_tasks = {item.id: item for item in previous_report.task_checks}
    current_tasks = {item.id: item for item in current_report.task_checks}
    if set(previous_tasks) != set(current_tasks):
        raise ValueError("scenario_tasks_mismatch")
    task_deltas = []
    for task in current_report.task_checks:
        before = previous_tasks[task.id]
        if before.status == task.status:
            change = "unchanged"
        elif before.status == "not_met" and task.status == "met":
            change = "improved"
        else:
            change = "regressed"
        task_deltas.append(
            AttemptTaskDelta(
                task_id=task.id,
                title=task.title,
                previous_status=before.status,
                current_status=task.status,
                change=change,
            )
        )

    previous_focus = {item.indicator_id: item.title for item in previous_report.improvements}
    current_focus = {item.indicator_id: item.title for item in current_report.improvements}
    resolved_focus = [title for key, title in previous_focus.items() if key not in current_focus]
    new_focus = [title for key, title in current_focus.items() if key not in previous_focus]
    score_delta = current_report.score - previous_report.score
    if score_delta > 0:
        summary = f"Результат вырос на {score_delta} баллов. Сильнее всего изменились блоки с положительной дельтой."
    elif score_delta < 0:
        summary = f"Результат снизился на {abs(score_delta)} баллов. Сравните новые ошибки и верните работающие действия прошлой попытки."
    else:
        summary = "Итоговый балл не изменился. Поблочная картина показывает, какие улучшения компенсировались новыми потерями."

    return AttemptComparisonResponse(
        series_id=current_session.series_id,
        scenario_id=current_session.scenario_id,
        scenario_title=current_session.configuration.topic,
        previous=_snapshot(previous_session, previous_report),
        current=_snapshot(current_session, current_report),
        score_delta=score_delta,
        outcome_changed=previous_report.outcome.kind != current_report.outcome.kind,
        block_deltas=block_deltas,
        task_deltas=task_deltas,
        improved_blocks=[item.title for item in block_deltas if item.delta > 0],
        regressed_blocks=[item.title for item in block_deltas if item.delta < 0],
        resolved_focus=resolved_focus,
        new_focus=new_focus,
        summary=summary,
        next_step=current_report.next_step,
    )
