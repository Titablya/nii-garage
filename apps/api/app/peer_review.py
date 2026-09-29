"""Anonymous peer review workflow for the School 21-inspired learning loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from uuid import UUID, uuid4

from .domain.golden_dialogue import DialogueRole, GoldenCaseType
from .domain.rubric import DEFAULT_RUBRIC_V01
from .engine import initial_state, transition_turn
from .golden_catalog import GoldenDialogueCatalog, get_golden_dialogue_catalog
from .models import (
    Message,
    NegotiationSession,
    PeerReviewAssignment,
    PeerReviewAppealResponse,
    PeerReviewComparison,
    PeerReviewCriterion,
    PeerReviewMessage,
    PeerReviewPublicItem,
    PeerReviewResult,
    PeerReviewSessionStatus,
    PeerReviewSla,
    ReportResponse,
    ReviewerReputation,
    SessionStatus,
    SubmitPeerReviewRequest,
)
from .reporting import evaluate_session
from .peer_repository import (
    InMemoryPeerReviewRepository,
    PeerReviewRecord,
    PeerReviewRepository,
)
from .repository import SessionRepository
from .scenario_catalog import ScenarioCatalog
from .services import (
    default_session_configuration,
    materialize_public_scenario,
    materialize_session_definition,
)


class PeerReviewNotFoundError(LookupError):
    pass


class PeerReviewConflictError(RuntimeError):
    pass


class PeerReviewValidationError(ValueError):
    pass


class PeerReviewService:
    """Keeps private evaluator data behind the submit boundary."""

    def __init__(
        self,
        repository: SessionRepository,
        scenario_catalog: ScenarioCatalog,
        golden_catalog: GoldenDialogueCatalog | None = None,
        review_repository: PeerReviewRepository | None = None,
    ) -> None:
        self._repository = repository
        self._scenario_catalog = scenario_catalog
        self._golden_catalog = golden_catalog or get_golden_dialogue_catalog()
        self._review_repository = review_repository or InMemoryPeerReviewRepository()

    dispute_threshold = 20

    def next_assignment(
        self,
        exclude_session_id: UUID | None = None,
        reviewer_user_id: UUID | None = None,
        *,
        language: str = "ru",
        difficulty: str | None = None,
    ) -> PeerReviewAssignment:
        active = self._review_repository.get_open(exclude_session_id, reviewer_user_id)
        if active is not None:
            return active.assignment

        if language not in {"ru", "en"}:
            raise PeerReviewValidationError("unsupported_review_language")
        if difficulty not in {None, "easy", "medium", "hard"}:
            raise PeerReviewValidationError("unsupported_review_difficulty")

        # A registered reviewer starts with a golden calibration exercise. It
        # trains the rubric without consuming a real learner's dialogue.
        calibration = bool(
            reviewer_user_id is not None
            and self._review_repository.count_submitted_for_user(reviewer_user_id) == 0
        )
        if calibration:
            if language != "ru":
                raise PeerReviewNotFoundError("calibration_language_unavailable")
            session = self._calibration_session()
            return self._build_assignment(
                session,
                reviewer_user_id,
                language=language,
                assignment_kind="calibration",
                review_round=1,
            )

        candidates: list[tuple[int, NegotiationSession, int]] = []
        for item in self._repository.list_completed():
            if item.id == exclude_session_id or not item.messages:
                continue
            if self._is_calibration_session(item):
                continue
            if self._session_language(item) != language:
                continue
            if difficulty is not None and item.configuration.difficulty.value != difficulty:
                continue
            if reviewer_user_id is not None:
                if item.participant_user_id == reviewer_user_id:
                    continue
                if self._review_repository.has_review(item.id, reviewer_user_id):
                    continue
                if item.participant_user_id is not None and self._review_repository.has_pair_conflict(
                    reviewer_user_id, item.participant_user_id
                ):
                    continue
            submitted = [record for record in self._review_repository.list_for_session(item.id) if record.submitted]
            if len(submitted) >= 2:
                continue
            disputed = bool(
                submitted
                and (
                    submitted[0].appeal_status == "pending"
                    or (submitted[0].result is not None and submitted[0].result.second_review_required)
                )
            )
            if disputed and reviewer_user_id is None:
                continue
            if submitted and not disputed:
                continue
            candidates.append((0 if disputed else 1, item, len(submitted) + 1))

        if candidates:
            _, session, review_round = sorted(candidates, key=lambda item: item[0])[0]
            return self._build_assignment(
                session,
                reviewer_user_id,
                language=language,
                assignment_kind="peer",
                review_round=review_round,
            )

        if language != "ru":
            raise PeerReviewNotFoundError("review_material_unavailable")
        session = self._calibration_session()
        return self._build_assignment(
            session,
            reviewer_user_id,
            language=language,
            assignment_kind="calibration",
            review_round=1,
        )

    def _build_assignment(
        self,
        session: NegotiationSession,
        reviewer_user_id: UUID | None,
        *,
        language: str,
        assignment_kind: str,
        review_round: int,
    ) -> PeerReviewAssignment:
        source_session_id = session.id

        definition = self._scenario_catalog.get_definition(session.scenario_id)
        scenario = self._scenario_catalog.get(session.scenario_id)
        if definition is None or scenario is None:
            raise PeerReviewNotFoundError("scenario_unavailable")
        automatic_report = evaluate_session(
            materialize_session_definition(definition, session.configuration),
            session,
        )
        public_scenario = materialize_public_scenario(scenario, session.configuration)
        assignment_id = uuid4()
        participant_alias = f"Участник P-{hashlib.sha256(str(session.id).encode()).hexdigest()[:4].upper()}"
        reviewer_source = str(reviewer_user_id or assignment_id)
        reviewer_alias = f"Рецензент R-{hashlib.sha256(reviewer_source.encode()).hexdigest()[:4].upper()}"
        matching_reasons = [
            f"Язык: {language.upper()}",
            f"Сложность: {session.configuration.difficulty.value}",
            "Конфликт интересов исключён",
        ]
        if review_round == 2:
            matching_reasons.append("Независимая повторная проверка")
        if assignment_kind == "calibration":
            matching_reasons = ["Калибровочное задание по эталонному диалогу"]
        assignment = PeerReviewAssignment(
            assignment_id=assignment_id,
            scenario_id=session.scenario_id,
            scenario_title=public_scenario.title,
            participant_alias=participant_alias,
            reviewer_alias=reviewer_alias,
            language=language,
            difficulty=session.configuration.difficulty,
            assignment_kind=assignment_kind,
            review_round=review_round,
            matching_reasons=matching_reasons,
            sla=PeerReviewSla(due_at=datetime.now(timezone.utc) + timedelta(hours=24)),
            instructions=(
                "Оцените участника по пяти блокам. Для каждого блока выберите реплику участника, "
                "объясните оценку и предложите улучшенную формулировку при низком балле."
            ),
            messages=[
                PeerReviewMessage(
                    id=message.id,
                    sequence=index,
                    role=message.role,
                    author_label=participant_alias if message.role == "participant" else "Сторона B",
                    content=message.content,
                )
                for index, message in enumerate(session.messages, start=1)
                if message.role in {"participant", "opponent"}
            ],
            criteria=[
                PeerReviewCriterion(
                    id=block.id,
                    title=block.title,
                    description=" ".join(criterion.description for criterion in block.criteria),
                    max_score=block.max_points,
                    low_score_threshold=block.max_points // 2,
                )
                for block in DEFAULT_RUBRIC_V01.blocks
            ],
        )
        self._review_repository.create(PeerReviewRecord(
            assignment=assignment,
            automatic_report=automatic_report,
            source_session_id=source_session_id,
            subject_user_id=session.participant_user_id,
            assignment_kind=assignment_kind,
            language=language,
            difficulty=session.configuration.difficulty.value,
            review_round=review_round,
            participant_alias=participant_alias,
            reviewer_alias=reviewer_alias,
        ), reviewer_user_id)
        return assignment

    def submit(self, payload: SubmitPeerReviewRequest) -> PeerReviewResult:
        record = self._review_repository.get(payload.assignment_id)
        if record is None:
            raise PeerReviewNotFoundError("assignment_not_found")
        if record.submitted:
            raise PeerReviewConflictError("assignment_already_submitted")

        criteria = {item.id: item for item in record.assignment.criteria}
        submitted_ids = [item.criterion_id for item in payload.items]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise PeerReviewValidationError("criterion_must_be_unique")
        if set(submitted_ids) != set(criteria):
            raise PeerReviewValidationError("all_criteria_are_required")

        messages_by_id = {item.id: item for item in record.assignment.messages}
        for item in payload.items:
            criterion = criteria[item.criterion_id]
            if item.score > criterion.max_score:
                raise PeerReviewValidationError("score_exceeds_maximum")
            if item.message_id not in messages_by_id:
                raise PeerReviewValidationError("message_is_not_in_assignment")
            if messages_by_id[item.message_id].role != "participant":
                raise PeerReviewValidationError("evidence_must_reference_participant")
            if item.score <= criterion.low_score_threshold and not item.suggested_text:
                raise PeerReviewValidationError("low_score_requires_suggested_text")

        automatic_by_id = {block.id: block for block in record.automatic_report.blocks}
        items_by_id = {item.criterion_id: item for item in payload.items}
        comparison = [
            PeerReviewComparison(
                criterion_id=criterion.id,
                title=criterion.title,
                peer_score=items_by_id[criterion.id].score,
                automatic_score=automatic_by_id[criterion.id].score,
                max_score=criterion.max_score,
                difference=items_by_id[criterion.id].score - automatic_by_id[criterion.id].score,
            )
            for criterion in record.assignment.criteria
        ]
        peer_score = sum(item.score for item in payload.items)
        automatic_score = record.automatic_report.score
        difference = peer_score - automatic_score
        absolute_difference = abs(difference)
        accuracy = max(0, 100 - absolute_difference * 2)
        evidence_quality = round(sum(min(100, len(item.comment) * 2) for item in payload.items) / len(payload.items))
        low_items = [
            item for item in payload.items
            if item.score <= criteria[item.criterion_id].low_score_threshold
        ]
        alternatives = sum(1 for item in low_items if item.suggested_text)
        usefulness = min(100, 55 + min(25, len(payload.overall_comment) // 8) + (20 if not low_items or alternatives == len(low_items) else 0))
        reputation_points = round(accuracy * 0.55 + evidence_quality * 0.25 + usefulness * 0.20)
        if reputation_points >= 85:
            label = "Точный рецензент"
        elif reputation_points >= 65:
            label = "Стабильный рецензент"
        else:
            label = "Развивающийся рецензент"

        previous = [item for item in self._review_repository.list_for_session(record.source_session_id) if item.submitted]
        if record.assignment.assignment_kind == "calibration":
            review_status = "calibrated"
            reviews_required = 1
        elif previous:
            review_status = "resolved"
            reviews_required = 2
        elif absolute_difference >= self.dispute_threshold:
            review_status = "second_review_required"
            reviews_required = 2
        else:
            review_status = "accepted"
            reviews_required = 1
        result = PeerReviewResult(
            assignment_id=payload.assignment_id,
            peer_score=peer_score,
            automatic_score=automatic_score,
            difference=difference,
            absolute_difference=absolute_difference,
            comparison=comparison,
            reputation=ReviewerReputation(
                points=reputation_points,
                label=label,
                explanation=(
                    "Репутация учитывает точность, качество доказательств и полезность "
                    "обратной связи. Строгость сама по себе не награждается."
                ),
                accuracy=accuracy,
                evidence_quality=evidence_quality,
                helpfulness=usefulness,
                reviews_completed=self._review_repository.count_submitted_for_user(record.reviewer_user_id) + 1 if record.reviewer_user_id else 1,
            ),
            assignment_kind=record.assignment.assignment_kind,
            review_round=record.assignment.review_round,
            review_status=review_status,
            reviews_received=len(previous) + 1,
            reviews_required=reviews_required,
            second_review_required=review_status == "second_review_required",
            feedback=(
                "Калибровка завершена: сравните аргументацию с эталонной рубрикой."
                if review_status == "calibrated"
                else "Оценки хорошо согласуются с рубрикой."
                if absolute_difference <= 10
                else "Назначена независимая повторная проверка; официальный балл остаётся прежним."
                if review_status == "second_review_required"
                else "Повторная проверка завершена; сравните расхождения по доказательствам."
            ),
        )
        self._review_repository.submit(payload, result)
        if review_status == "resolved":
            self._review_repository.resolve_session_appeals(
                record.source_session_id,
                "Спор пересмотрен независимым вторым рецензентом; официальный авто-балл не изменён.",
            )
        return result

    def session_status(
        self,
        session: NegotiationSession,
        viewer_user_id: UUID | None,
    ) -> PeerReviewSessionStatus:
        records = list(self._review_repository.list_for_session(session.id))
        submitted = [item for item in records if item.submitted and item.result is not None]
        pending_appeal = any(item.appeal_status == "pending" for item in submitted)
        disputed = any(item.result and item.result.second_review_required for item in submitted)
        if len(submitted) >= 2:
            status = "resolved"
        elif pending_appeal:
            status = "re_reviewing"
        elif disputed:
            status = "disputed"
        elif submitted:
            status = "reviewed"
        else:
            status = "waiting"
        required = 2 if pending_appeal or disputed or len(submitted) >= 2 else 1
        scores = [item.result.peer_score for item in submitted if item.result]
        sla = records[0].assignment.sla if records else PeerReviewSla()
        is_owner = bool(viewer_user_id and session.participant_user_id == viewer_user_id)
        can_appeal = bool(
            is_owner
            and len(submitted) == 1
            and submitted[0].assignment_kind == "peer"
            and submitted[0].appeal_status == "none"
        )
        return PeerReviewSessionStatus(
            session_id=session.id,
            status=status,
            reviews_received=len(submitted),
            reviews_required=required,
            consensus_score=(round(sum(scores) / len(scores)) if scores else None),
            can_appeal=can_appeal,
            sla=sla,
            reviews=[
                PeerReviewPublicItem(
                    assignment_id=item.assignment.assignment_id,
                    reviewer_alias=item.reviewer_alias,
                    peer_score=(item.result.peer_score if item.result else None),
                    review_round=item.review_round,
                    status=(item.result.review_status if item.result else "draft"),
                    appeal_status=item.appeal_status,  # type: ignore[arg-type]
                    submitted_at=item.submitted_at,
                )
                for item in records
            ],
        )

    def appeal(
        self,
        assignment_id: UUID,
        participant_user_id: UUID,
        reason: str,
    ) -> PeerReviewAppealResponse:
        record = self._review_repository.get(assignment_id)
        if record is None or record.subject_user_id != participant_user_id:
            raise PeerReviewNotFoundError("assignment_not_found")
        submitted = [item for item in self._review_repository.list_for_session(record.source_session_id) if item.submitted]
        if not record.submitted:
            raise PeerReviewConflictError("review_not_submitted")
        if record.assignment_kind != "peer":
            raise PeerReviewConflictError("calibration_cannot_be_appealed")
        if record.appeal_status != "none":
            raise PeerReviewConflictError("appeal_already_exists")
        if len(submitted) >= 2:
            raise PeerReviewConflictError("review_already_reconsidered")
        self._review_repository.appeal(assignment_id, reason)
        return PeerReviewAppealResponse(
            assignment_id=assignment_id,
            appeal_status="pending",
            review_status="re_reviewing",
            message="Жалоба принята. Диалог направлен второму независимому рецензенту.",
        )

    def _seed_session(self) -> NegotiationSession:
        case = self._golden_catalog.get(
            "equipment-supply:v1", GoldenCaseType.AGREEMENT_BAD_PROCESS
        )
        definition = self._scenario_catalog.get_definition("equipment-supply")
        if case is None or definition is None:
            raise PeerReviewNotFoundError("review_material_unavailable")

        public_scenario = self._scenario_catalog.get("equipment-supply")
        if public_scenario is None:
            raise PeerReviewNotFoundError("review_material_unavailable")
        configuration = default_session_configuration(public_scenario, definition)
        state = initial_state(definition)
        messages: list[Message] = []
        for item in case.messages:
            role = "participant" if item.role is DialogueRole.PARTICIPANT else "opponent"
            messages.append(Message(role=role, content=item.text))
            if role == "participant":
                state = transition_turn(definition, state, item.text).state
        return NegotiationSession(
            scenario_id="equipment-supply",
            scenario_version_id=case.scenario_version_id,
            configuration=configuration,
            engine_state=state,
            status=SessionStatus.COMPLETED,
            messages=messages,
            completed_at=datetime.now(timezone.utc),
        )

    def _is_calibration_session(self, session: NegotiationSession) -> bool:
        case = self._golden_catalog.get(
            "equipment-supply:v1", GoldenCaseType.AGREEMENT_BAD_PROCESS
        )
        if case is None or session.scenario_version_id != case.scenario_version_id:
            return False
        expected = [item.text for item in case.messages]
        actual = [item.content for item in session.messages if item.role in {"participant", "opponent"}]
        return actual == expected

    @staticmethod
    def _session_language(session: NegotiationSession) -> str:
        text = " ".join(
            [
                session.configuration.topic,
                session.configuration.context,
                session.configuration.participant_role,
                session.configuration.opponent_role,
                session.configuration.objective,
                *[item.content for item in session.messages if item.role == "participant"],
            ]
        ).casefold()
        cyrillic = sum("а" <= character <= "я" or character == "ё" for character in text)
        latin = sum("a" <= character <= "z" for character in text)
        return "en" if latin > cyrillic else "ru"

    def _calibration_session(self) -> NegotiationSession:
        existing = next(
            (item for item in self._repository.list_completed() if self._is_calibration_session(item)),
            None,
        )
        if existing is not None:
            return existing
        session = self._seed_session()
        self._repository.create(session)
        return session
