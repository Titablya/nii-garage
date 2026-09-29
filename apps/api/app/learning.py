"""Explainable skill map and personal learning trajectory."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from .db.database import Database
from .db.models import LearningPreference, SkillDrillCompletion
from .engine import ActionTag
from .models import (
    DrillDefinition,
    LearningDashboardResponse,
    LearningGoal,
    NegotiationSession,
    ReportResponse,
    ScenarioSkillProgress,
    SkillProgress,
    TrainerRecommendation,
    WeeklySkillProgress,
)
from .repository import SessionRepository
from .scenario_catalog import ScenarioCatalog


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class LearningGoalRecord:
    skill_id: str
    target_score: int
    weekly_sessions: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DrillCompletionRecord:
    id: UUID
    skill_id: str
    drill_id: str
    self_rating: int
    completed_at: datetime


class LearningRepository(Protocol):
    def get_goal(self, user_id: UUID) -> LearningGoalRecord | None: ...
    def save_goal(self, user_id: UUID, skill_id: str, target_score: int, weekly_sessions: int) -> LearningGoalRecord: ...
    def list_completions(self, user_id: UUID) -> tuple[DrillCompletionRecord, ...]: ...
    def add_completion(self, user_id: UUID, skill_id: str, drill_id: str, self_rating: int) -> DrillCompletionRecord: ...
    def delete_for_user(self, user_id: UUID) -> None: ...


class InMemoryLearningRepository:
    def __init__(self) -> None:
        self._goals: dict[UUID, LearningGoalRecord] = {}
        self._completions: dict[UUID, list[DrillCompletionRecord]] = defaultdict(list)

    def get_goal(self, user_id: UUID) -> LearningGoalRecord | None:
        return self._goals.get(user_id)

    def save_goal(self, user_id: UUID, skill_id: str, target_score: int, weekly_sessions: int) -> LearningGoalRecord:
        record = LearningGoalRecord(skill_id, target_score, weekly_sessions, _utc_now())
        self._goals[user_id] = record
        return record

    def list_completions(self, user_id: UUID) -> tuple[DrillCompletionRecord, ...]:
        return tuple(sorted(self._completions.get(user_id, []), key=lambda item: item.completed_at))

    def add_completion(self, user_id: UUID, skill_id: str, drill_id: str, self_rating: int) -> DrillCompletionRecord:
        record = DrillCompletionRecord(uuid4(), skill_id, drill_id, self_rating, _utc_now())
        self._completions[user_id].append(record)
        return record

    def delete_for_user(self, user_id: UUID) -> None:
        self._goals.pop(user_id, None)
        self._completions.pop(user_id, None)


class SqlAlchemyLearningRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _goal(row: LearningPreference) -> LearningGoalRecord:
        return LearningGoalRecord(row.goal_skill_id, row.target_score, row.weekly_sessions, _as_utc(row.updated_at))

    @staticmethod
    def _completion(row: SkillDrillCompletion) -> DrillCompletionRecord:
        return DrillCompletionRecord(UUID(row.id), row.skill_id, row.drill_id, row.self_rating, _as_utc(row.created_at))

    def get_goal(self, user_id: UUID) -> LearningGoalRecord | None:
        with self._database.session_factory() as db:
            row = db.get(LearningPreference, str(user_id))
            return self._goal(row) if row else None

    def save_goal(self, user_id: UUID, skill_id: str, target_score: int, weekly_sessions: int) -> LearningGoalRecord:
        now = _utc_now()
        with self._database.session_factory.begin() as db:
            row = db.get(LearningPreference, str(user_id))
            if row is None:
                row = LearningPreference(
                    user_id=str(user_id),
                    goal_skill_id=skill_id,
                    target_score=target_score,
                    weekly_sessions=weekly_sessions,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.goal_skill_id = skill_id
                row.target_score = target_score
                row.weekly_sessions = weekly_sessions
                row.updated_at = now
            db.flush()
            return self._goal(row)

    def list_completions(self, user_id: UUID) -> tuple[DrillCompletionRecord, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                select(SkillDrillCompletion)
                .where(SkillDrillCompletion.user_id == str(user_id))
                .order_by(SkillDrillCompletion.created_at)
            ).all()
            return tuple(self._completion(row) for row in rows)

    def add_completion(self, user_id: UUID, skill_id: str, drill_id: str, self_rating: int) -> DrillCompletionRecord:
        now = _utc_now()
        row = SkillDrillCompletion(
            id=str(uuid4()),
            user_id=str(user_id),
            skill_id=skill_id,
            drill_id=drill_id,
            self_rating=self_rating,
            created_at=now,
        )
        with self._database.session_factory.begin() as db:
            db.add(row)
        return self._completion(row)

    def delete_for_user(self, user_id: UUID) -> None:
        with self._database.session_factory.begin() as db:
            db.execute(delete(SkillDrillCompletion).where(SkillDrillCompletion.user_id == str(user_id)))
            db.execute(delete(LearningPreference).where(LearningPreference.user_id == str(user_id)))


@dataclass(frozen=True, slots=True)
class SkillSpec:
    id: str
    title: str
    description: str
    scenario_id: str
    drill: DrillDefinition


def _drill(
    skill_id: str,
    title: str,
    prompt: str,
    instructions: list[str],
    checklist: list[str],
    template: str,
) -> DrillDefinition:
    return DrillDefinition(
        id=f"{skill_id}.micro-v1",
        skill_id=skill_id,
        title=title,
        duration_minutes=4,
        prompt=prompt,
        instructions=instructions,
        success_checklist=checklist,
        suggested_template=template,
    )


SKILLS: tuple[SkillSpec, ...] = (
    SkillSpec("interests", "Интересы", "Отделять позиции от причин, ограничений и приоритетов сторон.", "project-resources", _drill("interests", "Три слоя за позицией", "Оппонент говорит: «Нам нужен запуск через две недели». Сформулируйте ответ, который раскрывает причины срока.", ["Не спорьте с позицией", "Задайте один открытый вопрос", "Назовите возможный интерес без утверждения"], ["Есть вопрос «что/почему/какой»", "Нет преждевременной уступки", "Гипотеза об интересе звучит нейтрально"], "Правильно понимаю, что для вас срок связан с …? Что произойдёт, если запуск будет позже?")),
    SkillSpec("questions", "Вопросы", "Получать новую информацию открытыми и уточняющими вопросами.", "project-resources", _drill("questions", "Воронка из трёх вопросов", "Вам отказали в дополнительном ресурсе без объяснения. Подготовьте три вопроса: широкий, уточняющий и проверочный.", ["Начните с широкого вопроса", "Уточните ограничение", "Завершите проверкой понимания"], ["Вопросы не подсказывают ответ", "Каждый следующий опирается на предыдущий", "Нет вопроса-обвинения"], "Что сейчас ограничивает выделение ресурса? Какой из факторов главный? Верно ли, что …?")),
    SkillSpec("active_listening", "Активное слушание", "Точно отражать услышанное и использовать его в следующем ходе.", "project-resources", _drill("active_listening", "Отразить и связать", "Оппонент опасается, что ваш проект заберёт ключевых специалистов у текущих задач. Ответьте без защиты и спора.", ["Кратко перефразируйте опасение", "Проверьте точность", "Свяжите услышанное со следующим вопросом"], ["Опасение названо конкретно", "Есть проверка «верно ли»", "Следующий вопрос учитывает услышанное"], "Верно ли я услышал: главный риск — просадка текущих задач? Тогда давайте уточним …")),
    SkillSpec("criteria", "Объективные критерии", "Опира́ться на проверяемые ориентиры и применять их к пакету условий.", "equipment-supply", _drill("criteria", "Ориентир вместо мнения", "Стороны спорят о цене оборудования. Предложите способ перейти от мнений к проверяемому критерию.", ["Назовите источник критерия", "Объясните его применимость", "Предложите одинаковое правило для обеих сторон"], ["Критерий можно проверить", "Он относится к предмету сделки", "Нет выдуманных цифр"], "Предлагаю сверить пакет с … и одинаково применить этот ориентир к цене и объёму работ.")),
    SkillSpec("meso", "MESO", "Предлагать несколько равноценных пакетов для выявления предпочтений.", "equipment-supply", _drill("meso", "Три равноценных пакета", "Соберите три пакета поставки, меняя срок, сервис и график оплаты, но сохраняя сопоставимую ценность для себя.", ["Используйте минимум три параметра", "Сделайте пакеты различимыми", "Попросите сравнить, а не выбрать «да/нет»"], ["Есть 3 пакета", "Пакеты равноценны для автора", "Ответ выявит приоритеты оппонента"], "Вариант A: …; B: …; C: …. Какой ближе и что в нём для вас важнее всего?")),
    SkillSpec("exchanges", "Взаимные обмены", "Связывать каждую уступку со встречным условием.", "equipment-supply", _drill("exchanges", "Если — то", "Оппонент просит ускорить поставку. Сформулируйте условный обмен без угрозы.", ["Назовите, что можете изменить", "Сразу обозначьте встречное условие", "Объясните деловую логику"], ["Формула содержит обе части обмена", "Условие измеримо", "Тон остаётся партнёрским"], "Если мы сокращаем срок до …, тогда нам потребуется …, потому что это компенсирует …")),
    SkillSpec("batna", "BATNA и границы", "Сравнивать соглашение с альтернативой и защищать минимально допустимый результат.", "equipment-supply", _drill("batna", "Граница без ультиматума", "Предложение ниже вашей допустимой границы. Откажите и оставьте пространство для жизнеспособного пакета.", ["Не раскрывайте лишние скрытые данные", "Назовите неприемлемость текущего пакета", "Предложите путь обратно в допустимую зону"], ["Нет сделки хуже альтернативы", "Нет личной угрозы", "Есть конкретное условие продолжения"], "В текущем виде пакет для нас нежизнеспособен. Мы можем продолжить, если скорректируем …")),
    SkillSpec("commitments", "Фиксация", "Закреплять действия, сроки, ответственных и измеримые параметры.", "project-resources", _drill("commitments", "Закрыть встречу протоколом", "Стороны устно согласились на пилот. Завершите переговоры так, чтобы договорённость можно было исполнить.", ["Назовите действие", "Укажите ответственного и срок", "Добавьте контрольную точку"], ["Есть кто, что и когда", "Параметры можно проверить", "Следующий контакт зафиксирован"], "Фиксирую: … отвечает за … до …. Статус сверяем … по метрике ….")),
)

SKILL_BY_ID = {item.id: item for item in SKILLS}
DRILL_TO_SKILL = {item.drill.id: item for item in SKILLS}


def _criterion(report: ReportResponse, criterion_id: str) -> int | None:
    for block in report.blocks:
        for item in block.criteria:
            if item.id == criterion_id:
                return round(item.score * 100 / item.max_score)
    return None


def _event_count(session: NegotiationSession, tag: ActionTag) -> int:
    count = sum(item.action_tag == tag for item in session.reason_events)
    if tag is ActionTag.OPEN_QUESTION:
        count = max(count, session.engine_state.open_question_count)
    if tag is ActionTag.ACTIVE_LISTENING:
        count = max(count, session.engine_state.active_listening_count)
    return count


def _action_score(count: int) -> int:
    return 0 if count <= 0 else 55 if count == 1 else 80 if count == 2 else 100


def _attempt_scores(session: NegotiationSession, report: ReportResponse) -> dict[str, int]:
    outcome = _criterion(report, "preparation.outcome") or 0
    quality = _criterion(report, "result.quality") or 0
    return {
        "interests": _criterion(report, "preparation.interests") or 0,
        "questions": _action_score(_event_count(session, ActionTag.OPEN_QUESTION)),
        "active_listening": _action_score(_event_count(session, ActionTag.ACTIVE_LISTENING)),
        "criteria": _criterion(report, "process.criteria") or 0,
        "meso": _action_score(_event_count(session, ActionTag.MESO)),
        "exchanges": _action_score(_event_count(session, ActionTag.CONDITIONAL_AGREEMENT)),
        "batna": round(outcome * 0.6 + quality * 0.4),
        "commitments": _criterion(report, "result.commitments") or 0,
    }


def _status(score: int | None) -> str:
    if score is None:
        return "new"
    if score < 50:
        return "focus"
    if score < 75:
        return "developing"
    return "strong"


class LearningService:
    def __init__(self, sessions: SessionRepository, catalog: ScenarioCatalog, learning: LearningRepository) -> None:
        self._sessions = sessions
        self._catalog = catalog
        self._learning = learning

    def set_goal(self, user_id: UUID, skill_id: str, target_score: int, weekly_sessions: int) -> LearningGoalRecord:
        if skill_id not in SKILL_BY_ID:
            raise ValueError("unknown_skill")
        return self._learning.save_goal(user_id, skill_id, target_score, weekly_sessions)

    def complete_drill(self, user_id: UUID, drill_id: str, self_rating: int) -> DrillCompletionRecord:
        skill = DRILL_TO_SKILL.get(drill_id)
        if skill is None:
            raise ValueError("unknown_drill")
        return self._learning.add_completion(user_id, skill.id, drill_id, self_rating)

    def delete_for_user(self, user_id: UUID) -> None:
        self._learning.delete_for_user(user_id)

    def dashboard(self, user_id: UUID) -> LearningDashboardResponse:
        session_reports: list[tuple[NegotiationSession, ReportResponse]] = []
        for session in self._sessions.list_for_user(user_id):
            report = self._sessions.get_report(session.id)
            if report is not None and session.completed_at is not None:
                session_reports.append((session, report))
        session_reports.sort(key=lambda item: item[0].completed_at or item[0].created_at)

        rubric_version = session_reports[-1][1].rubric_version if session_reports else None
        evaluator_version = session_reports[-1][1].evaluator_version if session_reports else None
        comparable = [
            item for item in session_reports
            if item[1].rubric_version == rubric_version
            and item[1].evaluator_version == evaluator_version
        ]
        excluded = len(session_reports) - len(comparable)
        scored = [(session, report, _attempt_scores(session, report)) for session, report in comparable]

        goal_record = self._learning.get_goal(user_id)
        goal = LearningGoal(
            skill_id=goal_record.skill_id,
            target_score=goal_record.target_score,
            weekly_sessions=goal_record.weekly_sessions,
            updated_at=goal_record.updated_at,
        ) if goal_record else None
        completions = self._learning.list_completions(user_id)
        now = _utc_now()
        skill_map: list[SkillProgress] = []
        for spec in SKILLS:
            values = [(session, scores[spec.id]) for session, _, scores in scored]
            latest = values[-1] if values else None
            previous = values[-2] if len(values) > 1 else None
            score = latest[1] if latest else None
            previous_score = previous[1] if previous else None
            skill_completions = [item for item in completions if item.skill_id == spec.id]
            next_due = None
            due = False
            if skill_completions:
                intervals = (1, 3, 7, 14, 30)
                last = skill_completions[-1]
                interval = intervals[min(len(skill_completions) - 1, len(intervals) - 1)]
                if last.self_rating <= 2:
                    interval = 1
                elif last.self_rating == 3:
                    interval = min(interval, 3)
                next_due = last.completed_at + timedelta(days=interval)
                due = next_due <= now
            elif (score is not None and score < 75) or (goal_record is not None and goal_record.skill_id == spec.id):
                next_due = now
                due = True

            if latest:
                completed_at = latest[0].completed_at or latest[0].created_at
                average = round(mean(item[1] for item in values))
                reason = (
                    f"Последняя сопоставимая попытка «{latest[0].configuration.topic}» — {score}/100; "
                    f"среднее по {len(values)} попыткам — {average}/100."
                )
            else:
                completed_at = None
                reason = "Пока нет завершённых попыток по текущей версии рубрики."
            skill_map.append(SkillProgress(
                id=spec.id,
                title=spec.title,
                description=spec.description,
                score=score,
                previous_score=previous_score,
                delta=(score - previous_score if score is not None and previous_score is not None else None),
                attempts=len(values),
                status=_status(score),
                last_practiced_at=completed_at,
                next_due_at=next_due,
                due=due,
                evidence_reason=reason,
            ))

        focus_id = goal_record.skill_id if goal_record else self._weakest_skill(skill_map)
        focus = SKILL_BY_ID[focus_id]
        focus_progress = next(item for item in skill_map if item.id == focus_id)
        scenario = self._catalog.get(focus.scenario_id) or self._catalog.list()[0]
        if goal_record:
            reason = (
                f"Вы выбрали «{focus.title}» как личную цель до {goal_record.target_score}/100. "
                f"Текущий подтверждённый уровень: {focus_progress.score if focus_progress.score is not None else 'ещё не измерен'}; "
                f"источник — {focus_progress.attempts} попыток рубрики {rubric_version or 'без версии'} "
                f"и оценщика {evaluator_version or 'без версии'}."
            )
        elif focus_progress.score is None:
            reason = "Начните с базовой диагностики: этот сценарий создаёт условия для наблюдаемой практики навыка."
        else:
            reason = (
                f"Это самая слабая зона последней сопоставимой попытки: {focus_progress.score}/100. "
                f"Рекомендация основана на {focus_progress.attempts} завершённых сессиях рубрики "
                f"{rubric_version} и оценщика {evaluator_version}."
            )
        reason += f" Кейс выбран для наблюдаемой практики: {focus.description.lower()}"

        return LearningDashboardResponse(
            rubric_version=rubric_version,
            evaluator_version=evaluator_version,
            comparable_sessions=len(comparable),
            excluded_incompatible_sessions=excluded,
            goal=goal,
            skill_map=skill_map,
            weekly_progress=self._weekly(scored),
            scenario_progress=self._scenarios(scored),
            recommendation=TrainerRecommendation(
                skill_id=focus_id,
                scenario_id=scenario.id,
                scenario_title=scenario.title,
                reason=reason,
            ),
            recommended_drill=focus.drill,
        )

    @staticmethod
    def _weakest_skill(skill_map: list[SkillProgress]) -> str:
        measured = [item for item in skill_map if item.score is not None]
        return min(measured, key=lambda item: (item.score, item.id)).id if measured else "interests"

    @staticmethod
    def _weekly(scored: list[tuple[NegotiationSession, ReportResponse, dict[str, int]]]) -> list[WeeklySkillProgress]:
        grouped: dict[date, list[dict[str, int]]] = defaultdict(list)
        for session, _, scores in scored:
            value = (session.completed_at or session.created_at).date()
            period = value - timedelta(days=value.weekday())
            grouped[period].append(scores)
        result = []
        for period, items in sorted(grouped.items())[-8:]:
            result.append(WeeklySkillProgress(
                period_start=period,
                attempts=len(items),
                scores={skill.id: round(mean(item[skill.id] for item in items)) for skill in SKILLS},
            ))
        return result

    def _scenarios(self, scored: list[tuple[NegotiationSession, ReportResponse, dict[str, int]]]) -> list[ScenarioSkillProgress]:
        grouped: dict[str, list[tuple[NegotiationSession, dict[str, int]]]] = defaultdict(list)
        for session, _, scores in scored:
            grouped[session.scenario_id].append((session, scores))
        result = []
        for scenario_id, items in grouped.items():
            scenario = self._catalog.get(scenario_id)
            result.append(ScenarioSkillProgress(
                scenario_id=scenario_id,
                scenario_title=scenario.title if scenario else items[-1][0].configuration.topic,
                attempts=len(items),
                scores={skill.id: round(mean(scores[skill.id] for _, scores in items)) for skill in SKILLS},
            ))
        return sorted(result, key=lambda item: (-item.attempts, item.scenario_title))
