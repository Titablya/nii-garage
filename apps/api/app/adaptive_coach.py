"""Private, budgeted learning layer that never mutates the official negotiation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from .db.database import Database
from .db.models import AdaptiveCoachArtifact, AdaptivePrebrief
from .engine import ActionTag
from .engine.classifier import classify_action
from .learning import SKILL_BY_ID, _attempt_scores
from .llm import GenerationRequest, LLMProvider, LLMProviderError
from .models import (
    AdaptiveCoachSummary,
    AdaptiveDrillCheck,
    AdaptiveDrillFeedback,
    CoachBudget,
    CoachHintRequest,
    CoachHintResponse,
    CoachRewriteImpact,
    CoachRewriteRequest,
    CoachRewriteResponse,
    CompleteAdaptiveDrillRequest,
    NegotiationSession,
    PersonalizedMiniDrill,
    PrebriefWorksheetRequest,
    PrebriefWorksheetResponse,
    ReportResponse,
)
from .repository import SessionRepository
from .scenario_catalog import ScenarioCatalog


MAX_COACH_TOKENS = 3_600
MAX_COACH_CALLS = 8
_COACH_KINDS = {"hint", "rewrite"}
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)")
_FORBIDDEN_LEAKS = (
    "zopa",
    "batna оппонента",
    "батна оппонента",
    "reservation point оппонента",
    "скрытая граница оппонента",
    "минимум оппонента",
    "максимум оппонента",
)

_HINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
    "additionalProperties": False,
}
_REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "possible_reply": {"type": "string"},
        "analysis": {"type": "string"},
    },
    "required": ["possible_reply", "analysis"],
    "additionalProperties": False,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class PrebriefRecord:
    session_id: UUID
    user_id: UUID | None
    payload: PrebriefWorksheetRequest
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CoachArtifactRecord:
    id: UUID
    session_id: UUID
    user_id: UUID | None
    kind: str
    fingerprint: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    provider: str
    fallback: bool
    estimated_tokens: int
    created_at: datetime


class AdaptiveCoachRepository(Protocol):
    def get_prebrief(self, session_id: UUID) -> PrebriefRecord | None: ...
    def save_prebrief(self, session: NegotiationSession, payload: PrebriefWorksheetRequest) -> PrebriefRecord: ...
    def find_cached(self, session_id: UUID, kind: str, fingerprint: str) -> CoachArtifactRecord | None: ...
    def save_artifact(self, record: CoachArtifactRecord) -> CoachArtifactRecord: ...
    def list_artifacts(self, session_id: UUID) -> tuple[CoachArtifactRecord, ...]: ...
    def delete_for_user(self, user_id: UUID) -> None: ...


class InMemoryAdaptiveCoachRepository:
    def __init__(self) -> None:
        self._prebriefs: dict[UUID, PrebriefRecord] = {}
        self._artifacts: dict[UUID, list[CoachArtifactRecord]] = {}

    def get_prebrief(self, session_id: UUID) -> PrebriefRecord | None:
        return self._prebriefs.get(session_id)

    def save_prebrief(self, session: NegotiationSession, payload: PrebriefWorksheetRequest) -> PrebriefRecord:
        now = _utc_now()
        previous = self._prebriefs.get(session.id)
        record = PrebriefRecord(
            session.id,
            session.participant_user_id,
            payload,
            previous.created_at if previous else now,
            now,
        )
        self._prebriefs[session.id] = record
        return record

    def find_cached(self, session_id: UUID, kind: str, fingerprint: str) -> CoachArtifactRecord | None:
        return next(
            (
                item
                for item in self._artifacts.get(session_id, [])
                if item.kind == kind and item.fingerprint == fingerprint
            ),
            None,
        )

    def save_artifact(self, record: CoachArtifactRecord) -> CoachArtifactRecord:
        self._artifacts.setdefault(record.session_id, []).append(record)
        return record

    def list_artifacts(self, session_id: UUID) -> tuple[CoachArtifactRecord, ...]:
        return tuple(self._artifacts.get(session_id, ()))

    def delete_for_user(self, user_id: UUID) -> None:
        session_ids = {
            item.session_id for item in self._prebriefs.values() if item.user_id == user_id
        }
        session_ids.update(
            item.session_id
            for items in self._artifacts.values()
            for item in items
            if item.user_id == user_id
        )
        self._prebriefs = {
            key: value for key, value in self._prebriefs.items() if value.user_id != user_id
        }
        self._artifacts = {
            key: value for key, value in self._artifacts.items() if key not in session_ids
        }


class SqlAlchemyAdaptiveCoachRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _prebrief(row: AdaptivePrebrief) -> PrebriefRecord:
        return PrebriefRecord(
            session_id=UUID(row.session_id),
            user_id=UUID(row.user_id) if row.user_id else None,
            payload=PrebriefWorksheetRequest.model_validate(row.payload),
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
        )

    @staticmethod
    def _artifact(row: AdaptiveCoachArtifact) -> CoachArtifactRecord:
        return CoachArtifactRecord(
            id=UUID(row.id),
            session_id=UUID(row.session_id),
            user_id=UUID(row.user_id) if row.user_id else None,
            kind=row.kind,
            fingerprint=row.fingerprint,
            request_payload=dict(row.request_payload),
            response_payload=dict(row.response_payload),
            provider=row.provider,
            fallback=row.fallback,
            estimated_tokens=row.estimated_tokens,
            created_at=_as_utc(row.created_at),
        )

    def get_prebrief(self, session_id: UUID) -> PrebriefRecord | None:
        with self._database.session_factory() as db:
            row = db.get(AdaptivePrebrief, str(session_id))
            return self._prebrief(row) if row else None

    def save_prebrief(self, session: NegotiationSession, payload: PrebriefWorksheetRequest) -> PrebriefRecord:
        now = _utc_now()
        with self._database.session_factory.begin() as db:
            row = db.get(AdaptivePrebrief, str(session.id))
            if row is None:
                row = AdaptivePrebrief(
                    session_id=str(session.id),
                    user_id=str(session.participant_user_id) if session.participant_user_id else None,
                    focus_skill=payload.focus_skill,
                    payload=payload.model_dump(mode="json"),
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.focus_skill = payload.focus_skill
                row.payload = payload.model_dump(mode="json")
                row.updated_at = now
            db.flush()
            return self._prebrief(row)

    def find_cached(self, session_id: UUID, kind: str, fingerprint: str) -> CoachArtifactRecord | None:
        with self._database.session_factory() as db:
            row = db.scalar(
                select(AdaptiveCoachArtifact).where(
                    AdaptiveCoachArtifact.session_id == str(session_id),
                    AdaptiveCoachArtifact.kind == kind,
                    AdaptiveCoachArtifact.fingerprint == fingerprint,
                )
            )
            return self._artifact(row) if row else None

    def save_artifact(self, record: CoachArtifactRecord) -> CoachArtifactRecord:
        with self._database.session_factory.begin() as db:
            db.add(
                AdaptiveCoachArtifact(
                    id=str(record.id),
                    session_id=str(record.session_id),
                    user_id=str(record.user_id) if record.user_id else None,
                    kind=record.kind,
                    fingerprint=record.fingerprint,
                    request_payload=record.request_payload,
                    response_payload=record.response_payload,
                    provider=record.provider,
                    fallback=record.fallback,
                    estimated_tokens=record.estimated_tokens,
                    created_at=record.created_at,
                )
            )
        return record

    def list_artifacts(self, session_id: UUID) -> tuple[CoachArtifactRecord, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                select(AdaptiveCoachArtifact)
                .where(AdaptiveCoachArtifact.session_id == str(session_id))
                .order_by(AdaptiveCoachArtifact.created_at)
            ).all()
            return tuple(self._artifact(row) for row in rows)

    def delete_for_user(self, user_id: UUID) -> None:
        with self._database.session_factory.begin() as db:
            db.execute(delete(AdaptiveCoachArtifact).where(AdaptiveCoachArtifact.user_id == str(user_id)))
            db.execute(delete(AdaptivePrebrief).where(AdaptivePrebrief.user_id == str(user_id)))


_SKILL_TITLES = {item.id: item.title for item in SKILL_BY_ID.values()}
_TAG_SKILLS: dict[ActionTag, tuple[str, str]] = {
    ActionTag.OPEN_QUESTION: ("questions", "Открытый вопрос"),
    ActionTag.ACTIVE_LISTENING: ("active_listening", "Активное слушание"),
    ActionTag.OBJECTIVE_CRITERION: ("criteria", "Объективный критерий"),
    ActionTag.MESO: ("meso", "Несколько равноценных вариантов"),
    ActionTag.CONDITIONAL_AGREEMENT: ("exchanges", "Условный обмен"),
    ActionTag.COMMITMENT: ("commitments", "Фиксация обязательств"),
}
_SOCRATIC_HINTS = {
    "interests": "Какой интерес собеседника вы пока предполагаете, но ещё не проверили открытым вопросом?",
    "questions": "Какой один открытый вопрос сейчас даст новую информацию, а не подтолкнёт собеседника к вашему ответу?",
    "active_listening": "Как вы кратко отразите услышанное и проверите, что поняли собеседника правильно?",
    "criteria": "Какой проверяемый внешний критерий поможет обеим сторонам оценить предложение одинаково?",
    "meso": "Какие три параметра можно переставить между двумя-тремя равноценными пакетами, чтобы выявить приоритеты?",
    "exchanges": "Какую уступку вы готовы связать с каким измеримым встречным условием по формуле «если — то»?",
    "batna": "Как проверить, что следующий пакет не хуже вашей собственной альтернативы, не раскрывая лишних деталей?",
    "commitments": "Что именно, кто и к какому сроку должен подтвердить, чтобы договорённость стала исполнимой?",
}


class AdaptiveCoachService:
    def __init__(
        self,
        sessions: SessionRepository,
        catalog: ScenarioCatalog,
        repository: AdaptiveCoachRepository,
        provider: LLMProvider | None,
        *,
        model: str | None = None,
    ) -> None:
        self._sessions = sessions
        self._catalog = catalog
        self._repository = repository
        self._provider = provider
        self._model = model

    def delete_for_user(self, user_id: UUID) -> None:
        self._repository.delete_for_user(user_id)

    def prebrief(self, session: NegotiationSession) -> PrebriefWorksheetResponse:
        record = self._repository.get_prebrief(session.id)
        if record:
            return self._prebrief_response(record, saved=True)
        inherited = None
        if session.previous_session_id:
            inherited = self._repository.get_prebrief(session.previous_session_id)
        payload = inherited.payload if inherited else PrebriefWorksheetRequest(
            focus_skill="interests",
            goal=session.configuration.objective,
            interests=[],
            participant_batna="Определить лучшую альтернативу, если договориться не получится.",
            participant_reservation="Зафиксировать собственную минимально допустимую границу до диалога.",
            planned_questions=["Что для вас важнее всего в этом соглашении и почему?"],
        )
        return PrebriefWorksheetResponse(
            **payload.model_dump(),
            id=None,
            session_id=session.id,
            saved=False,
            inherited_from_attempt=session.attempt_number - 1 if inherited else None,
            updated_at=None,
        )

    def save_prebrief(
        self, session: NegotiationSession, payload: PrebriefWorksheetRequest
    ) -> PrebriefWorksheetResponse:
        return self._prebrief_response(
            self._repository.save_prebrief(session, payload), saved=True
        )

    async def hint(
        self, session: NegotiationSession, request: CoachHintRequest
    ) -> CoachHintResponse:
        worksheet = self.prebrief(session)
        skill = request.skill_id or worksheet.focus_skill
        request_payload = {
            "turn": session.engine_state.turn_count,
            "skill_id": skill,
            "draft": request.draft,
            "mode": request.mode,
        }
        fingerprint = self._fingerprint("hint", request_payload)
        cached = self._repository.find_cached(session.id, "hint", fingerprint)
        if cached:
            return CoachHintResponse.model_validate(cached.response_payload).model_copy(
                update={"cached": True, "budget": self.budget(session.id)}
            )

        question = _SOCRATIC_HINTS[skill]
        provider_name = "deterministic"
        fallback = True
        prompt = self._hint_prompt(session, worksheet, skill, request.draft)
        attempted = self._provider is not None and self._can_call(session.id)
        if attempted:
            try:
                generated = await self._provider.generate(
                    GenerationRequest(
                        prompt=prompt,
                        response_json_schema=_HINT_SCHEMA,
                        max_output_tokens=180,
                    )
                )
                candidate = json.loads(generated.reply)["question"].strip()
                if not self._valid_socratic_question(candidate, prompt):
                    raise ValueError("hint_role_alignment_failed")
                question = candidate
                provider_name = "gemini"
                fallback = False
            except (LLMProviderError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass

        response = CoachHintResponse(
            question=question,
            skill_id=skill,
            provider=provider_name,
            fallback=fallback,
            cached=False,
            budget=CoachBudget(used_tokens=0, remaining_tokens=MAX_COACH_TOKENS, used_calls=0, remaining_calls=MAX_COACH_CALLS),
        )
        tokens = self._estimated_tokens(prompt, question) if attempted else 0
        self._save_artifact(session, "hint", fingerprint, request_payload, response.model_dump(mode="json"), provider_name, fallback, tokens, attempted)
        return response.model_copy(update={"budget": self.budget(session.id)})

    async def rewrite(
        self, session: NegotiationSession, request: CoachRewriteRequest
    ) -> CoachRewriteResponse:
        original = next(
            (item for item in session.messages if item.id == request.message_id and item.role == "participant"),
            None,
        )
        if original is None:
            raise KeyError("participant_message_not_found")
        last_participant = next(
            (item for item in reversed(session.messages) if item.role == "participant"),
            None,
        )
        if last_participant is None or last_participant.id != original.id:
            raise ValueError("only_last_participant_message_can_be_rewritten")

        request_payload = {
            "message_id": str(request.message_id),
            "revised_text": request.revised_text,
            "turn": session.engine_state.turn_count,
        }
        fingerprint = self._fingerprint("rewrite", request_payload)
        cached = self._repository.find_cached(session.id, "rewrite", fingerprint)
        if cached:
            return CoachRewriteResponse.model_validate(cached.response_payload).model_copy(
                update={"cached": True, "budget": self.budget(session.id)}
            )

        impacts = self._rewrite_impacts(session, original.content, request.revised_text)
        possible_reply = self._fallback_reaction(request.revised_text)
        analysis = self._fallback_rewrite_analysis(impacts)
        provider_name = "deterministic"
        fallback = True
        prompt = self._rewrite_prompt(session, original.content, request.revised_text)
        attempted = self._provider is not None and self._can_call(session.id)
        if attempted:
            try:
                generated = await self._provider.generate(
                    GenerationRequest(
                        prompt=prompt,
                        response_json_schema=_REWRITE_SCHEMA,
                        max_output_tokens=320,
                    )
                )
                parsed = json.loads(generated.reply)
                candidate_reply = parsed["possible_reply"].strip()
                candidate_analysis = parsed["analysis"].strip()
                if not self._valid_public_output(candidate_reply + " " + candidate_analysis, prompt):
                    raise ValueError("rewrite_role_alignment_failed")
                if self._role_drift(candidate_reply, session.configuration.participant_role):
                    raise ValueError("rewrite_role_drift")
                possible_reply = candidate_reply
                analysis = candidate_analysis
                provider_name = "gemini"
                fallback = False
            except (LLMProviderError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass

        response = CoachRewriteResponse(
            official_message_id=original.id,
            original_text=original.content,
            revised_text=request.revised_text,
            possible_opponent_reply=possible_reply,
            analysis=analysis,
            impacts=impacts,
            provider=provider_name,
            fallback=fallback,
            cached=False,
            budget=CoachBudget(used_tokens=0, remaining_tokens=MAX_COACH_TOKENS, used_calls=0, remaining_calls=MAX_COACH_CALLS),
        )
        tokens = self._estimated_tokens(prompt, possible_reply + analysis) if attempted else 0
        self._save_artifact(session, "rewrite", fingerprint, request_payload, response.model_dump(mode="json"), provider_name, fallback, tokens, attempted)
        return response.model_copy(update={"budget": self.budget(session.id)})

    def mini_drill(
        self, session: NegotiationSession, report: ReportResponse
    ) -> PersonalizedMiniDrill:
        prebrief = self.prebrief(session)
        skill = prebrief.focus_skill
        spec = SKILL_BY_ID[skill]
        point = report.coaching.points[0] if report.coaching and report.coaching.points else None
        improvement = report.improvements[0] if report.improvements else None
        quote = point.quote if point and point.quote else improvement.original_quote if improvement else None
        turn = point.turn if point else None
        problem = point.problem if point else improvement.rationale if improvement else report.next_step
        prompt = (
            f"Перепишите реальную реплику так, чтобы усилить навык «{spec.title}». "
            f"Диагностика: {problem}"
        )
        if quote:
            prompt += f" Исходная реплика: «{quote}»"
        return PersonalizedMiniDrill(
            id=f"adaptive.{session.id}.{skill}.v1",
            session_id=session.id,
            skill_id=skill,
            title=f"Исправить реальную ошибку: {spec.title}",
            prompt=prompt,
            source_turn=turn,
            source_quote=quote,
            instructions=list(spec.drill.instructions),
            success_checklist=list(spec.drill.success_checklist),
            suggested_template=spec.drill.suggested_template,
        )

    def complete_mini_drill(
        self,
        session: NegotiationSession,
        report: ReportResponse,
        request: CompleteAdaptiveDrillRequest,
    ) -> AdaptiveDrillFeedback:
        drill = self.mini_drill(session, report)
        checks = self._drill_checks(session, drill.skill_id, request.answer)
        score = round(sum(item.met for item in checks) * 100 / len(checks))
        response = AdaptiveDrillFeedback(
            drill_id=drill.id,
            skill_id=drill.skill_id,
            score=score,
            passed=score >= 67,
            feedback=(
                "Реплика закрывает выбранный навык. Используйте её как намерение, а не как заученный скрипт."
                if score >= 67
                else "Усилите реплику по двум невыполненным пунктам чек-листа и попробуйте ещё раз."
            ),
            checks=checks,
        )
        fingerprint = self._fingerprint(
            "drill_submission", {"drill_id": drill.id, "answer": request.answer}
        )
        if self._repository.find_cached(session.id, "drill_submission", fingerprint) is None:
            self._save_artifact(
                session,
                "drill_submission",
                fingerprint,
                {"drill_id": drill.id, "answer": request.answer, "llm_attempted": False},
                response.model_dump(mode="json"),
                "deterministic",
                False,
                0,
                False,
            )
        return response

    def summary(self, session: NegotiationSession) -> AdaptiveCoachSummary:
        prebrief = self.prebrief(session)
        artifacts = self._repository.list_artifacts(session.id)
        current_score = None
        previous_score = None
        report = self._sessions.get_report(session.id)
        if report:
            current_score = _attempt_scores(session, report)[prebrief.focus_skill]
        if session.previous_session_id:
            previous = self._sessions.get(session.previous_session_id)
            previous_report = self._sessions.get_report(session.previous_session_id)
            if (
                previous
                and previous_report
                and report
                and previous_report.rubric_version == report.rubric_version
                and previous_report.evaluator_version == report.evaluator_version
            ):
                previous_score = _attempt_scores(previous, previous_report)[prebrief.focus_skill]
        return AdaptiveCoachSummary(
            session_id=session.id,
            focus_skill=prebrief.focus_skill,
            hint_count=sum(item.kind == "hint" for item in artifacts),
            rewrite_count=sum(item.kind == "rewrite" for item in artifacts),
            drill_completed=any(item.kind == "drill_submission" for item in artifacts),
            previous_skill_score=previous_score,
            current_skill_score=current_score,
            skill_delta=(current_score - previous_score if current_score is not None and previous_score is not None else None),
            budget=self.budget(session.id),
        )

    def budget(self, session_id: UUID) -> CoachBudget:
        artifacts = self._repository.list_artifacts(session_id)
        attempted = [
            item
            for item in artifacts
            if item.kind in _COACH_KINDS and item.request_payload.get("llm_attempted") is True
        ]
        used_tokens = min(MAX_COACH_TOKENS, sum(item.estimated_tokens for item in attempted))
        used_calls = min(MAX_COACH_CALLS, len(attempted))
        return CoachBudget(
            used_tokens=used_tokens,
            remaining_tokens=MAX_COACH_TOKENS - used_tokens,
            used_calls=used_calls,
            remaining_calls=MAX_COACH_CALLS - used_calls,
        )

    def _can_call(self, session_id: UUID) -> bool:
        budget = self.budget(session_id)
        return budget.remaining_calls > 0 and budget.remaining_tokens >= 180

    @staticmethod
    def _prebrief_response(record: PrebriefRecord, *, saved: bool) -> PrebriefWorksheetResponse:
        return PrebriefWorksheetResponse(
            **record.payload.model_dump(),
            id=record.session_id,
            session_id=record.session_id,
            saved=saved,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _fingerprint(kind: str, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{kind}:{serialized}".encode()).hexdigest()

    @staticmethod
    def _estimated_tokens(prompt: str, output: str) -> int:
        return min(MAX_COACH_TOKENS, max(1, (len(prompt) + len(output) + 3) // 4))

    def _save_artifact(
        self,
        session: NegotiationSession,
        kind: str,
        fingerprint: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        provider: str,
        fallback: bool,
        tokens: int,
        attempted: bool,
    ) -> None:
        persisted_request = dict(request_payload)
        persisted_request["llm_attempted"] = attempted
        self._repository.save_artifact(
            CoachArtifactRecord(
                id=uuid4(),
                session_id=session.id,
                user_id=session.participant_user_id,
                kind=kind,
                fingerprint=fingerprint,
                request_payload=persisted_request,
                response_payload=response_payload,
                provider=provider,
                fallback=fallback,
                estimated_tokens=tokens,
                created_at=_utc_now(),
            )
        )

    def _hint_prompt(
        self,
        session: NegotiationSession,
        worksheet: PrebriefWorksheetResponse,
        skill: str,
        draft: str,
    ) -> str:
        transcript = self._public_transcript(session)
        return (
            "Return JSON with exactly one Socratic coaching question in Russian. "
            "Do not give a ready answer, offer, number, opponent secret, or hidden economic inference. "
            "Stay outside both negotiation roles. The question must end with '?'.\n"
            f"PUBLIC TOPIC: {session.configuration.topic}\n"
            f"PUBLIC CONTEXT: {session.configuration.context}\n"
            f"PARTICIPANT ROLE: {session.configuration.participant_role}\n"
            f"OPPONENT ROLE: {session.configuration.opponent_role}\n"
            f"PUBLIC OBJECTIVE: {session.configuration.objective}\n"
            f"PRIVATE PARTICIPANT FOCUS: {_SKILL_TITLES[skill]}\n"
            f"PARTICIPANT'S OWN GOAL: {worksheet.goal}\n"
            f"PARTICIPANT'S OWN ALTERNATIVE: {worksheet.participant_batna}\n"
            f"PARTICIPANT'S OWN LIMIT: {worksheet.participant_reservation}\n"
            f"PUBLIC TRANSCRIPT: {transcript}\n"
            f"UNSENT DRAFT: {draft or '[empty]'}"
        )

    def _rewrite_prompt(
        self, session: NegotiationSession, original: str, revised: str
    ) -> str:
        return (
            "Return JSON in Russian with a possible_opponent_reply and a concise analysis. "
            "This is an unofficial learning branch. Never claim the official transcript or score changed. "
            "Speak only as the configured opponent in possible_opponent_reply. Do not invent numbers, "
            "hidden limits, opponent alternatives, or deal economics not present below.\n"
            f"PUBLIC TOPIC: {session.configuration.topic}\n"
            f"PUBLIC CONTEXT: {session.configuration.context}\n"
            f"PARTICIPANT ROLE: {session.configuration.participant_role}\n"
            f"OPPONENT ROLE: {session.configuration.opponent_role}\n"
            f"PUBLIC TRANSCRIPT: {self._public_transcript(session)}\n"
            f"ORIGINAL PARTICIPANT MESSAGE: {original}\n"
            f"REVISED PARTICIPANT MESSAGE: {revised}"
        )

    @staticmethod
    def _public_transcript(session: NegotiationSession) -> str:
        rows = []
        for item in session.messages[-8:]:
            role = "participant" if item.role == "participant" else "opponent"
            rows.append(f"{role}: {item.content[:700]}")
        return " | ".join(rows) if rows else "[no messages yet]"

    @staticmethod
    def _valid_public_output(output: str, prompt: str) -> bool:
        normalized = output.casefold().replace("ё", "е")
        if any(term in normalized for term in _FORBIDDEN_LEAKS):
            return False
        return set(_NUMBER.findall(output)) <= set(_NUMBER.findall(prompt))

    @classmethod
    def _valid_socratic_question(cls, question: str, prompt: str) -> bool:
        if not 10 <= len(question) <= 500 or not question.rstrip().endswith("?"):
            return False
        normalized = question.casefold()
        if any(token in normalized for token in ("скажите так", "готовый ответ", "предложите цену")):
            return False
        return cls._valid_public_output(question, prompt)

    @staticmethod
    def _role_drift(reply: str, participant_role: str) -> bool:
        normalized = reply.casefold().replace("ё", "е")
        role = participant_role.casefold().replace("ё", "е")
        return normalized.startswith(("участник:", "тренер:", "совет:")) or f"я, {role}" in normalized

    def _rewrite_impacts(
        self, session: NegotiationSession, original: str, revised: str
    ) -> list[CoachRewriteImpact]:
        definition = self._catalog.get_definition(session.scenario_id)
        if definition is None:
            return [
                CoachRewriteImpact(
                    skill_id="interests",
                    title="Ясность намерения",
                    effect="unchanged",
                    explanation="Альтернативная формулировка сохранена для сравнения без изменения официального диалога.",
                )
            ]
        original_tags = set(classify_action(definition, session.engine_state, original).tags)
        revised_tags = set(classify_action(definition, session.engine_state, revised).tags)
        impacts: list[CoachRewriteImpact] = []
        for tag, (skill_id, title) in _TAG_SKILLS.items():
            if tag in revised_tags or tag in original_tags:
                effect = "improved" if tag in revised_tags and tag not in original_tags else "weakened" if tag in original_tags and tag not in revised_tags else "unchanged"
                impacts.append(
                    CoachRewriteImpact(
                        skill_id=skill_id,
                        title=title,
                        effect=effect,
                        explanation=(
                            "В новой версии появился наблюдаемый индикатор навыка."
                            if effect == "improved"
                            else "Наблюдаемый индикатор сохранился."
                            if effect == "unchanged"
                            else "Индикатор из исходной реплики потерян."
                        ),
                    )
                )
        if not impacts:
            impacts.append(
                CoachRewriteImpact(
                    skill_id="interests",
                    title="Выявление интересов",
                    effect="unchanged",
                    explanation="Формулировка изменилась, но новый наблюдаемый переговорный приём пока не появился.",
                )
            )
        return impacts[:4]

    @staticmethod
    def _fallback_reaction(revised: str) -> str:
        if "?" in revised:
            return "Это важный вопрос. Для нас приоритетны управляемый риск и исполнимость договорённости; уточните, какой пакет вы готовы обсуждать."
        if re.search(r"\bесли\b.+\bто\b|при условии|в обмен на", revised, re.IGNORECASE):
            return "Такой взаимный обмен можно обсуждать. Давайте уточним параметры и зафиксируем, что получает каждая сторона."
        return "Формулировка понятна. Уточните, пожалуйста, как это предложение учитывает наши приоритеты и ограничения."

    @staticmethod
    def _fallback_rewrite_analysis(impacts: list[CoachRewriteImpact]) -> str:
        improved = [item.title for item in impacts if item.effect == "improved"]
        return (
            f"Новая версия усиливает: {', '.join(improved)}. Проверьте реакцию собеседника и затем возвращайтесь к официальной ветке."
            if improved
            else "Новая версия меняет подачу, но не добавляет нового наблюдаемого приёма. Усильте вопрос, критерий или взаимный обмен."
        )

    def _drill_checks(
        self, session: NegotiationSession, skill: str, answer: str
    ) -> list[AdaptiveDrillCheck]:
        definition = self._catalog.get_definition(session.scenario_id)
        tags = set(classify_action(definition, session.engine_state, answer).tags) if definition else set()
        expected = {
            "interests": ActionTag.OPEN_QUESTION,
            "questions": ActionTag.OPEN_QUESTION,
            "active_listening": ActionTag.ACTIVE_LISTENING,
            "criteria": ActionTag.OBJECTIVE_CRITERION,
            "meso": ActionTag.MESO,
            "exchanges": ActionTag.CONDITIONAL_AGREEMENT,
            "commitments": ActionTag.COMMITMENT,
        }.get(skill)
        if skill == "batna":
            technique = bool(re.search(r"нежизнеспособ|границ|альтернатив|если.+то|можем продолжить", answer, re.IGNORECASE))
        else:
            technique = expected in tags if expected else False
        safe = not bool(tags & {ActionTag.PERSONAL_ATTACK, ActionTag.THREAT, ActionTag.UNILATERAL_CONCESSION})
        return [
            AdaptiveDrillCheck(title="Реплика достаточно конкретна", met=len(answer) >= 40),
            AdaptiveDrillCheck(title=f"Наблюдается навык «{_SKILL_TITLES[skill]}»", met=technique),
            AdaptiveDrillCheck(title="Нет угрозы, атаки или односторонней уступки", met=safe),
        ]


__all__ = [
    "AdaptiveCoachRepository",
    "AdaptiveCoachService",
    "InMemoryAdaptiveCoachRepository",
    "SqlAlchemyAdaptiveCoachRepository",
    "MAX_COACH_CALLS",
    "MAX_COACH_TOKENS",
]
