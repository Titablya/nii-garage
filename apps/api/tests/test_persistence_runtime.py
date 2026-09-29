from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.database import create_database
from app.db.models import EvaluationRun
from app.db.settings import DatabaseSettings
from app.llm.opponent import OpponentGenerator
from app.models import PeerReviewItemInput, SubmitPeerReviewRequest
from app.peer_repository import SqlAlchemyPeerReviewRepository
from app.peer_review import PeerReviewConflictError, PeerReviewService
from app.repository import SqlAlchemySessionRepository
from app.scenario_catalog import get_scenario_catalog
from app.services import (
    add_participant_message,
    build_report,
    complete_session,
    create_session,
    retry_session,
)


def _database(path: Path):
    database = create_database(DatabaseSettings(url=f"sqlite:///{path.as_posix()}"))
    Base.metadata.create_all(database.engine)
    return database


def _completed_session(repository, catalog):
    session = create_session(repository, catalog, "equipment-supply")
    asyncio.run(
        add_participant_message(
            repository,
            catalog,
            OpponentGenerator(None),
            session.id,
            "Какие сроки и условия оплаты для вас наиболее важны?",
        )
    )
    return complete_session(repository, session.id)


def test_sessions_reports_and_attempt_lineage_survive_repository_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.db"
    catalog = get_scenario_catalog()
    first_database = _database(database_path)
    first_repository = SqlAlchemySessionRepository(first_database, catalog)
    completed = _completed_session(first_repository, catalog)
    report = build_report(catalog, completed)
    first_repository.save_report(report)
    replacement = report.model_copy(update={"evaluator_version": "2.0"})
    assert first_repository.save_report(replacement) == report
    with first_database.session_factory() as db:
        stored = db.scalar(
            select(EvaluationRun).where(EvaluationRun.session_id == str(completed.id))
        )
        assert stored is not None
        assert stored.evaluator_version == report.evaluator_version
        assert stored.result["evaluator_version"] == report.evaluator_version
        assert db.scalar(
            select(func.count()).select_from(EvaluationRun).where(
                EvaluationRun.session_id == str(completed.id)
            )
        ) == 1
    first_database.engine.dispose()

    second_database = create_database(
        DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}")
    )
    second_repository = SqlAlchemySessionRepository(second_database, catalog)
    restored = second_repository.get(completed.id)

    assert restored is not None
    assert restored.model_dump(mode="json") == completed.model_dump(mode="json")
    assert second_repository.get_report(completed.id) == report

    retry = retry_session(second_repository, catalog, completed.id)
    assert retry.previous_session_id == completed.id
    assert retry.series_id == completed.series_id
    assert retry.attempt_number == 2
    assert [item.id for item in second_repository.list_series(completed.series_id)] == [
        completed.id,
        retry.id,
    ]


def test_peer_review_submission_survives_restart_without_sharing_anonymous_draft(tmp_path: Path) -> None:
    catalog = get_scenario_catalog()
    database = _database(tmp_path / "peer-review.db")
    sessions = SqlAlchemySessionRepository(database, catalog)
    completed = _completed_session(sessions, catalog)

    first_service = PeerReviewService(
        sessions,
        catalog,
        review_repository=SqlAlchemyPeerReviewRepository(database),
    )
    assignment = first_service.next_assignment()

    restarted_service = PeerReviewService(
        sessions,
        catalog,
        review_repository=SqlAlchemyPeerReviewRepository(database),
    )
    restored = restarted_service.next_assignment()
    assert restored.assignment_id != assignment.assignment_id

    payload = SubmitPeerReviewRequest(
        assignment_id=assignment.assignment_id,
        overall_comment="Рецензия содержит оценки и ссылки на конкретные реплики диалога.",
        items=[
            PeerReviewItemInput(
                criterion_id=criterion.id,
                score=criterion.max_score,
                message_id=assignment.messages[0].id,
                comment="Реплика содержит наблюдаемое поведение по выбранному критерию.",
            )
            for criterion in assignment.criteria
        ],
    )
    result = restarted_service.submit(payload)
    assert result.assignment_id == assignment.assignment_id

    after_second_restart = PeerReviewService(
        sessions,
        catalog,
        review_repository=SqlAlchemyPeerReviewRepository(database),
    )
    with pytest.raises(PeerReviewConflictError):
        after_second_restart.submit(payload)

    assert sessions.get(completed.id) is not None
