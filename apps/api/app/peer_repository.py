from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload

from .db.database import Database
from .db.models import PeerReview, PeerReviewItem, User
from .models import (
    AccountPeerReviewItem,
    PeerReviewAssignment,
    PeerReviewResult,
    ReportResponse,
    SubmitPeerReviewRequest,
)


@dataclass(slots=True)
class PeerReviewRecord:
    assignment: PeerReviewAssignment
    automatic_report: ReportResponse
    source_session_id: UUID
    submitted: bool = False
    reviewer_user_id: UUID | None = None
    subject_user_id: UUID | None = None
    assignment_kind: str = "peer"
    language: str = "ru"
    difficulty: str = "medium"
    review_round: int = 1
    participant_alias: str = "Участник A"
    reviewer_alias: str = "Рецензент R"
    appeal_status: str = "none"
    appeal_reason: str | None = None
    appeal_resolution: str | None = None
    created_at: datetime | None = None
    submitted_at: datetime | None = None
    result: PeerReviewResult | None = None


class PeerReviewRepository(Protocol):
    def get_open(self, exclude_session_id: UUID | None = None, reviewer_user_id: UUID | None = None) -> PeerReviewRecord | None: ...

    def get(self, assignment_id: UUID) -> PeerReviewRecord | None: ...

    def create(self, record: PeerReviewRecord, reviewer_user_id: UUID | None = None) -> PeerReviewRecord: ...

    def has_review(self, session_id: UUID, reviewer_user_id: UUID) -> bool: ...

    def has_pair_conflict(self, reviewer_user_id: UUID, subject_user_id: UUID) -> bool: ...

    def count_submitted_for_user(self, reviewer_user_id: UUID) -> int: ...

    def list_for_session(self, session_id: UUID) -> tuple[PeerReviewRecord, ...]: ...

    def list_for_user(self, user_id: UUID) -> tuple[AccountPeerReviewItem, ...]: ...

    def delete_for_user(self, user_id: UUID) -> None: ...

    def submit(
        self,
        payload: SubmitPeerReviewRequest,
        result: PeerReviewResult,
    ) -> None: ...

    def appeal(self, assignment_id: UUID, reason: str) -> PeerReviewRecord: ...

    def resolve_session_appeals(self, session_id: UUID, resolution: str) -> None: ...


class InMemoryPeerReviewRepository:
    def __init__(self) -> None:
        self._records: dict[UUID, PeerReviewRecord] = {}

    def get_open(self, exclude_session_id: UUID | None = None, reviewer_user_id: UUID | None = None) -> PeerReviewRecord | None:
        if reviewer_user_id is None:
            return None
        return next(
            (
                record
                for record in reversed(tuple(self._records.values()))
                if not record.submitted and record.source_session_id != exclude_session_id and record.reviewer_user_id == reviewer_user_id
            ),
            None,
        )

    def get(self, assignment_id: UUID) -> PeerReviewRecord | None:
        return self._records.get(assignment_id)

    def create(self, record: PeerReviewRecord, reviewer_user_id: UUID | None = None) -> PeerReviewRecord:
        record.reviewer_user_id = reviewer_user_id
        record.created_at = record.created_at or datetime.now(timezone.utc)
        self._records[record.assignment.assignment_id] = record
        return record

    def has_review(self, session_id: UUID, reviewer_user_id: UUID) -> bool:
        return any(record.source_session_id == session_id and record.reviewer_user_id == reviewer_user_id for record in self._records.values())

    def has_pair_conflict(self, reviewer_user_id: UUID, subject_user_id: UUID) -> bool:
        if reviewer_user_id == subject_user_id:
            return True
        return any(
            record.reviewer_user_id is not None
            and record.subject_user_id is not None
            and {
                record.reviewer_user_id,
                record.subject_user_id,
            } == {reviewer_user_id, subject_user_id}
            for record in self._records.values()
        )

    def count_submitted_for_user(self, reviewer_user_id: UUID) -> int:
        return sum(1 for record in self._records.values() if record.reviewer_user_id == reviewer_user_id and record.submitted)

    def list_for_session(self, session_id: UUID) -> tuple[PeerReviewRecord, ...]:
        return tuple(record for record in self._records.values() if record.source_session_id == session_id)

    def list_for_user(self, user_id: UUID) -> tuple[AccountPeerReviewItem, ...]:
        now = datetime.now(timezone.utc)
        return tuple(
            AccountPeerReviewItem(
                assignment_id=record.assignment.assignment_id,
                scenario_title=record.assignment.scenario_title,
                status="submitted" if record.submitted else "draft",
                peer_score=(record.result.peer_score if record.result else None),
                reputation_points=(record.result.reputation.points if record.result else None),
                assignment_kind=record.assignment_kind,  # type: ignore[arg-type]
                review_status=("submitted" if record.submitted else "draft"),
                created_at=record.created_at or now,
                submitted_at=record.submitted_at or (now if record.submitted else None),
            )
            for record in self._records.values()
            if record.reviewer_user_id == user_id
        )

    def delete_for_user(self, user_id: UUID) -> None:
        self._records = {key: value for key, value in self._records.items() if value.reviewer_user_id != user_id}

    def submit(
        self,
        payload: SubmitPeerReviewRequest,
        result: PeerReviewResult,
    ) -> None:
        record = self._records[payload.assignment_id]
        record.submitted = True
        record.submitted_at = datetime.now(timezone.utc)
        record.result = result

    def appeal(self, assignment_id: UUID, reason: str) -> PeerReviewRecord:
        record = self._records[assignment_id]
        record.appeal_status = "pending"
        record.appeal_reason = reason
        return record

    def resolve_session_appeals(self, session_id: UUID, resolution: str) -> None:
        for record in self._records.values():
            if record.source_session_id == session_id and record.appeal_status == "pending":
                record.appeal_status = "resolved"
                record.appeal_resolution = resolution


class SqlAlchemyPeerReviewRepository:
    """Persists anonymized assignments and submitted review evidence."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_open(self, exclude_session_id: UUID | None = None, reviewer_user_id: UUID | None = None) -> PeerReviewRecord | None:
        if reviewer_user_id is None:
            return None
        with self._database.session_factory() as db:
            statement = (
                select(PeerReview)
                .where(PeerReview.status == "draft")
                .order_by(PeerReview.created_at.desc())
                .limit(1)
            )
            if exclude_session_id is not None:
                statement = statement.where(
                    PeerReview.session_id != str(exclude_session_id)
                )
            statement = statement.where(PeerReview.reviewer_user_id == str(reviewer_user_id))
            row = db.scalar(statement)
            return self._to_record(row) if row is not None else None

    def get(self, assignment_id: UUID) -> PeerReviewRecord | None:
        with self._database.session_factory() as db:
            row = db.scalar(
                select(PeerReview)
                .where(PeerReview.id == str(assignment_id))
                .options(selectinload(PeerReview.items))
            )
            return self._to_record(row) if row is not None else None

    def create(self, record: PeerReviewRecord, reviewer_user_id: UUID | None = None) -> PeerReviewRecord:
        assignment_id = str(record.assignment.assignment_id)
        with self._database.session_factory.begin() as db:
            reviewer_id = str(reviewer_user_id) if reviewer_user_id else assignment_id
            if reviewer_user_id is None:
                db.add(User(id=assignment_id, email=None, display_name="Анонимный рецензент"))
                db.flush()
            db.add(
                PeerReview(
                    id=assignment_id,
                    session_id=str(record.source_session_id),
                    reviewer_user_id=reviewer_id,
                    status="draft",
                    assignment_kind=record.assignment_kind,
                    language=record.language,
                    difficulty=record.difficulty,
                    review_round=record.review_round,
                    subject_user_id=(str(record.subject_user_id) if record.subject_user_id else None),
                    participant_alias=record.participant_alias,
                    reviewer_alias=record.reviewer_alias,
                    assignment_payload=record.assignment.model_dump(mode="json"),
                    automatic_report=record.automatic_report.model_dump(mode="json"),
                )
            )
        record.reviewer_user_id = UUID(reviewer_id)
        return record

    def has_review(self, session_id: UUID, reviewer_user_id: UUID) -> bool:
        with self._database.session_factory() as db:
            return db.scalar(
                select(PeerReview.id).where(
                    PeerReview.session_id == str(session_id),
                    PeerReview.reviewer_user_id == str(reviewer_user_id),
                ).limit(1)
            ) is not None

    def has_pair_conflict(self, reviewer_user_id: UUID, subject_user_id: UUID) -> bool:
        if reviewer_user_id == subject_user_id:
            return True
        reviewer = str(reviewer_user_id)
        subject = str(subject_user_id)
        with self._database.session_factory() as db:
            return db.scalar(
                select(PeerReview.id).where(
                    or_(
                        (PeerReview.reviewer_user_id == reviewer) & (PeerReview.subject_user_id == subject),
                        (PeerReview.reviewer_user_id == subject) & (PeerReview.subject_user_id == reviewer),
                    )
                ).limit(1)
            ) is not None

    def count_submitted_for_user(self, reviewer_user_id: UUID) -> int:
        with self._database.session_factory() as db:
            return len(db.scalars(select(PeerReview.id).where(
                PeerReview.reviewer_user_id == str(reviewer_user_id),
                PeerReview.status == "submitted",
            )).all())

    def list_for_session(self, session_id: UUID) -> tuple[PeerReviewRecord, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                select(PeerReview)
                .where(PeerReview.session_id == str(session_id))
                .options(selectinload(PeerReview.items))
                .order_by(PeerReview.review_round, PeerReview.created_at)
            ).all()
            return tuple(self._to_record(row) for row in rows)

    def list_for_user(self, user_id: UUID) -> tuple[AccountPeerReviewItem, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                select(PeerReview)
                .where(PeerReview.reviewer_user_id == str(user_id))
                .order_by(PeerReview.created_at.desc())
            ).all()
            return tuple(
                AccountPeerReviewItem(
                    assignment_id=UUID(row.id),
                    scenario_title=(row.assignment_payload or {}).get("scenario_title", "Переговорный кейс"),
                    status=row.status,
                    peer_score=(row.result_payload or {}).get("peer_score"),
                    reputation_points=((row.result_payload or {}).get("reputation") or {}).get("points"),
                    assignment_kind=row.assignment_kind,
                    review_status=(row.result_payload or {}).get("review_status", row.status),
                    created_at=row.created_at,
                    submitted_at=row.submitted_at,
                )
                for row in rows
            )

    def delete_for_user(self, user_id: UUID) -> None:
        with self._database.session_factory.begin() as db:
            db.execute(delete(PeerReview).where(PeerReview.reviewer_user_id == str(user_id)))

    def submit(
        self,
        payload: SubmitPeerReviewRequest,
        result: PeerReviewResult,
    ) -> None:
        with self._database.session_factory.begin() as db:
            row = db.scalar(
                select(PeerReview)
                .where(PeerReview.id == str(payload.assignment_id))
                .options(selectinload(PeerReview.items))
                .with_for_update()
            )
            if row is None:
                raise KeyError("assignment_not_found")
            if row.status == "submitted":
                raise ValueError("assignment_already_submitted")
            row.status = "submitted"
            row.overall_comment = payload.overall_comment
            row.submitted_at = datetime.now(timezone.utc)
            row.result_payload = result.model_dump(mode="json")
            row.items = [
                PeerReviewItem(
                    criterion_code=item.criterion_id,
                    score=item.score,
                    comment=item.comment,
                    message_id=str(item.message_id),
                    suggested_text=item.suggested_text,
                )
                for item in payload.items
            ]

    def appeal(self, assignment_id: UUID, reason: str) -> PeerReviewRecord:
        with self._database.session_factory.begin() as db:
            row = db.scalar(
                select(PeerReview)
                .where(PeerReview.id == str(assignment_id))
                .options(selectinload(PeerReview.items))
                .with_for_update()
            )
            if row is None:
                raise KeyError("assignment_not_found")
            row.appeal_status = "pending"
            row.appeal_reason = reason
            row.appealed_at = datetime.now(timezone.utc)
        result = self.get(assignment_id)
        if result is None:
            raise KeyError("assignment_not_found")
        return result

    def resolve_session_appeals(self, session_id: UUID, resolution: str) -> None:
        with self._database.session_factory.begin() as db:
            rows = db.scalars(
                select(PeerReview).where(
                    PeerReview.session_id == str(session_id),
                    PeerReview.appeal_status == "pending",
                ).with_for_update()
            ).all()
            now = datetime.now(timezone.utc)
            for row in rows:
                row.appeal_status = "resolved"
                row.appeal_resolution = resolution
                row.resolved_at = now

    @staticmethod
    def _to_record(row: PeerReview) -> PeerReviewRecord:
        if row.assignment_payload is None or row.automatic_report is None:
            raise ValueError(f"peer review {row.id} has no persisted assignment data")
        return PeerReviewRecord(
            assignment=PeerReviewAssignment.model_validate(row.assignment_payload),
            automatic_report=ReportResponse.model_validate(row.automatic_report),
            source_session_id=UUID(row.session_id),
            submitted=row.status == "submitted",
            reviewer_user_id=UUID(row.reviewer_user_id),
            subject_user_id=(UUID(row.subject_user_id) if row.subject_user_id else None),
            assignment_kind=row.assignment_kind,
            language=row.language,
            difficulty=row.difficulty,
            review_round=row.review_round,
            participant_alias=row.participant_alias,
            reviewer_alias=row.reviewer_alias,
            appeal_status=row.appeal_status,
            appeal_reason=row.appeal_reason,
            appeal_resolution=row.appeal_resolution,
            created_at=row.created_at,
            submitted_at=row.submitted_at,
            result=(PeerReviewResult.model_validate(row.result_payload) if row.result_payload else None),
        )
