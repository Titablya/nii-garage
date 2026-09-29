from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from ..domain.rubric import DEFAULT_RUBRIC_V01
from ..domain.scenario import MethodologyModule, ScenarioDefinition
from ..engine import ActionTag, NegotiationOutcome, initial_state, transition_turn
from ..engine.classifier import unquoted_text
from ..engine.contracts import ClassifiedAction, NegotiationState
from ..engine.offers import assess_offer
from ..models import (
    EvidenceItem,
    Finding,
    Improvement,
    MethodologyInfo,
    NegotiationSession,
    OutcomeAnalysis,
    PenaltyItem,
    ReportResponse,
    ScoreBlock,
    ScoreCriterion,
    TrajectoryPoint,
)
from ..tasking import display_issue_value, evaluate_task_checks


EVALUATOR_VERSION = "1.2"


@dataclass(frozen=True, slots=True)
class _Turn:
    number: int
    message_id: object
    text: str
    action: ClassifiedAction
    state: NegotiationState
    indicators: tuple[str, ...]
    opponent_context: str | None


_INDICATOR_TITLES = {
    "I1": "Исследование интересов",
    "I2": "Позиция переведена в интерес",
    "I3": "Активное слушание",
    "I4": "Совместная постановка задачи",
    "I5": "Объективный критерий",
    "I6": "Создание варианта",
    "I7": "Взаимный обмен",
    "I8": "Несколько равноценных пакетов",
    "I9": "Обоснованный якорь",
    "I10": "Уместный SPIN-вопрос",
    "I11": "Деэскалация",
    "I12": "Чёткое обязательство",
    "I13": "Последовательное влияние через контакт",
    "N1": "Личная атака",
    "N2": "Необоснованная угроза",
    "N3": "Односторонняя уступка",
    "N4": "Неподтверждённый факт",
    "N5": "Игнорирование опасения",
}

_INDICATOR_EXPLANATIONS = {
    "I1": "Открытый вопрос помог перейти от позиции к причинам и ограничениям.",
    "I2": "Реплика связывает требование с лежащей за ним потребностью.",
    "I3": "Опасение или приоритет другой стороны точно отражены в ответе.",
    "I4": "Проблема сформулирована как совместная задача, а не борьба сторон.",
    "I5": "Предложение связано с проверяемым внешним ориентиром.",
    "I6": "Внесён содержательный вариант решения.",
    "I7": "Уступка связана со встречным условием.",
    "I8": "Одновременно предложено несколько пакетов для выявления предпочтений.",
    "I9": "Числовая позиция обоснована критерием или расчётом.",
    "I10": "Вопрос уместно исследует ситуацию, проблему или последствия.",
    "I11": "Напряжение снижено через нейтральное наблюдение и конкретную просьбу.",
    "I12": "Зафиксированы действия, сроки или ответственные.",
    "I13": "После слушания и признания опасения оппонент подтвердил контакт, затем предложен совместный следующий шаг. Это наблюдаемая последовательность, не доказательство изменения поведения.",
    "N1": "Оценка личности ухудшает отношения и не решает предмет переговоров.",
    "N2": "Давление не обосновано публичной альтернативой или полномочиями.",
    "N3": "Ценность отдана без встречного условия или объяснения.",
    "N4": "В реплике использовано категоричное утверждение без публичного основания.",
    "N5": "Критичное опасение другой стороны осталось без содержательной реакции.",
}

_PENALTY_MAP = {
    "N1": ("penalty.personal_attack", "Личная атака", -8),
    "N2": ("penalty.threat", "Необоснованная угроза", -10),
    "N3": ("penalty.unilateral_concession", "Односторонняя уступка", -4),
    "N4": ("penalty.fabricated_fact", "Неподтверждённый факт", -3),
    "N5": ("penalty.ignored_concern", "Игнорирование критичного опасения", -3),
}

_INDICATOR_POINTS = {
    "I1": 4,
    "I2": 3,
    "I3": 4,
    "I4": 2,
    "I5": 4,
    "I6": 4,
    "I7": 3,
    "I8": 3,
    "I9": 3,
    "I10": 4,
    "I11": 2,
    "I12": 5,
    "I13": 4,
}


def _contains(text: str, *patterns: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)


def _previous_concern_ignored(
    previous_opponent: str | None, action: ClassifiedAction, participant_text: str
) -> bool:
    if not previous_opponent or not _contains(
        previous_opponent,
        r"риск|опасен|беспок|критич|нагрузк|затрат|бюджет|срок|предоплат|ресурс|неs+мож",
    ):
        return False
    responsive = {
        ActionTag.ACTIVE_LISTENING,
        ActionTag.OPEN_QUESTION,
        ActionTag.CONDITIONAL_AGREEMENT,
        ActionTag.OBJECTIVE_CRITERION,
    }
    if set(action.tags) & responsive:
        return False
    return _contains(
        participant_text,
        r"других вариант\w* не будет",
        r"обсудим потом",
        r"не должн\w* мешать",
        r"общ\w* пакет.+не нуж",
        r"услови\w* прежн",
        r"последн\w* слов",
        r"не обсужда",
        r"никак\w* нов\w* услов",
        r"по ходу работ\w*",
    )


def _nvc_deescalation(scenario: ScenarioDefinition, tags: set[ActionTag], text: str) -> bool:
    """Conservative observable proxy for NVC's observation/feeling/need/request."""

    if MethodologyModule.NVC not in scenario.methodology_modules:
        return False
    if {ActionTag.PERSONAL_ATTACK, ActionTag.THREAT} & tags:
        return False
    return all((
        _contains(text, r"\b(?:вчера|сегодня|на встрече|после|когда|наблюдаю|заметил)"),
        _contains(text, r"\b(?:тревож|пережива|беспоко|огорча|расстро|чувствую)"),
        _contains(text, r"\b(?:мне важно|нам важно|мне нужна|нам нужна|мне нужен|нам нужен|потребност)"),
        _contains(text, r"\b(?:прошу|можете|давайте)\b.+(?:свер|обсуд|соглас|выбер|зафикс|реш|провер)"),
    ))


def _stairway_progression(scenario: ScenarioDefinition, turns: list[_Turn]) -> list[_Turn]:
    """Mark only a transcript-observable listening→rapport→joint-request sequence."""

    if MethodologyModule.BEHAVIORAL_CHANGE_STAIRWAY not in scenario.methodology_modules:
        return turns
    if any({"N1", "N2"} & set(turn.indicators) for turn in turns):
        return turns
    for index, influence in enumerate(turns):
        if "I4" not in influence.indicators or not _contains(
            unquoted_text(influence.text), r"свер", r"соглас", r"вместе.+реш", r"общ\w* задач"
        ):
            continue
        if not _contains(influence.opponent_context or "", r"спасибо", r"услышал", r"готов.+обсуд", r"можно обсуд"):
            continue
        listeners = [turn for turn in turns[:index] if "I3" in turn.indicators]
        if len(listeners) < 2 or not any(
            _contains(unquoted_text(turn.text), r"понимаю.+беспокой", r"слышу.+трудно", r"вижу.+риск")
            for turn in listeners[1:]
        ):
            continue
        result = list(turns)
        result[index] = replace(influence, indicators=(*influence.indicators, "I13"))
        return result
    return turns


def _indicators(
    scenario: ScenarioDefinition,
    action: ClassifiedAction,
    text: str,
    previous_opponent: str | None,
) -> tuple[str, ...]:
    candidates: list[str] = []
    tags = set(action.tags)
    behavioral_text = unquoted_text(text)

    # Negative observations have priority in presentation, but a well-formed
    # package can legitimately demonstrate several independent skills at once
    # (for example objective criteria + MESO + a shared-problem frame).  Keep
    # every observed indicator so scoring and advice never claim that an action
    # visible in the transcript was missing.
    if ActionTag.PERSONAL_ATTACK in tags:
        candidates.append("N1")
    elif _contains(behavioral_text, r"не умеют считать", r"не понимаете.+управл", r"ваш\w* компетен"):
        candidates.append("N1")
    if ActionTag.THREAT in tags:
        candidates.append("N2")
    elif _contains(behavioral_text, r"добьюсь.+не рассматрив", r"сообщу.+блокир", r"эскалир.+руковод"):
        candidates.append("N2")
    if ActionTag.UNILATERAL_CONCESSION in tags:
        candidates.append("N3")
    elif _contains(behavioral_text, r"хорошо.+достаточно", r"ладно.+соглас", r"пусть будет"):
        candidates.append("N3")
    if _contains(
        behavioral_text,
        r"единственн\w* вариант",
        r"точно гарант\w*",
        r"конкурент\w* нет",
        r"все уже согласован",
        r"одобрен советом директор",
        r"ресурс\w* уже утвержден",
        r"рынок точно",
    ):
        candidates.append("N4")
    if _previous_concern_ignored(previous_opponent, action, behavioral_text):
        candidates.append("N5")

    if ActionTag.ACTIVE_LISTENING in tags:
        candidates.append("I3")
    if ActionTag.OPEN_QUESTION in tags:
        candidates.append("I1")
        if MethodologyModule.SPIN in scenario.methodology_modules:
            candidates.append("I10")
    if ActionTag.OBJECTIVE_CRITERION in tags:
        candidates.append("I5")
        if ActionTag.ANCHOR in tags:
            candidates.append("I9")
    if ActionTag.MESO in tags:
        candidates.append("I8")
    if ActionTag.CONDITIONAL_AGREEMENT in tags or _contains(behavioral_text, r"взаимн\w* обмен", r"связыва\w*.+с"):
        candidates.append("I7")
    if ActionTag.COMMITMENT in tags:
        candidates.append("I12")
    if _contains(behavioral_text, r"общ\w* задач", r"давайте.+вместе", r"найти решен", r"решим.+задач", r"предлагаю искать"):
        candidates.append("I4")
    if _contains(behavioral_text, r"потому что", r"причин", r"интерес", r"приоритет", r"потребност", r"ограничен"):
        candidates.append("I2")
    if ActionTag.OPTION in tags:
        candidates.append("I6")
    if _nvc_deescalation(scenario, tags, behavioral_text):
        candidates.append("I11")

    return tuple(dict.fromkeys(candidates))


def _evidence(turn: _Turn) -> EvidenceItem:
    quote = turn.text.strip()
    if len(quote) > 500:
        quote = quote[:497].rstrip() + "…"
    return EvidenceItem(message_id=turn.message_id, turn=turn.number, quote=quote)


def _first_turn(turns: Iterable[_Turn], *, indicator: str | None = None, tag: ActionTag | None = None) -> _Turn | None:
    for turn in turns:
        if indicator is not None and indicator in turn.indicators:
            return turn
        if tag is not None and tag in turn.action.tags:
            return turn
    return None


def _unique_evidence(*turns: _Turn | None) -> list[EvidenceItem]:
    result: list[EvidenceItem] = []
    seen: set[object] = set()
    for turn in turns:
        if turn is not None and turn.message_id not in seen:
            result.append(_evidence(turn))
            seen.add(turn.message_id)
    return result


def _replay(scenario: ScenarioDefinition, session: NegotiationSession) -> tuple[list[_Turn], list[TrajectoryPoint]]:
    state = initial_state(scenario)
    trajectory = [
        TrajectoryPoint(
            turn=0,
            trust=state.trust,
            tension=state.tension,
            progress=state.progress,
            relationship=state.relationship,
        )
    ]
    turns: list[_Turn] = []
    previous_opponent: str | None = None
    turn_number = 0
    for message in session.messages:
        if message.role == "opponent":
            previous_opponent = message.content
            continue
        if message.role != "participant":
            continue
        turn_number += 1
        transition = transition_turn(scenario, state, message.content)
        state = transition.state
        turns.append(
            _Turn(
                number=turn_number,
                message_id=message.id,
                text=message.content,
                action=transition.action,
                state=state,
                indicators=_indicators(scenario, transition.action, message.content, previous_opponent),
                opponent_context=previous_opponent,
            )
        )
        trajectory.append(
            TrajectoryPoint(
                turn=turn_number,
                trust=state.trust,
                tension=state.tension,
                progress=state.progress,
                relationship=state.relationship,
            )
        )

    # Classifier improvements may legitimately change derived process metrics
    # (trust, progress, detected indicators) for a session created by an older
    # application release.  The contractual result must still reproduce: same
    # scenario/roles, number of turns, terminal state, outcome and accepted
    # package.  This keeps historical reports available after a safe deploy
    # without accepting a history that changes the deal itself.
    authoritative = session.engine_state
    compatible = (
        state.scenario_version_id == authoritative.scenario_version_id
        and state.participant_role_id == authoritative.participant_role_id
        and state.opponent_role_id == authoritative.opponent_role_id
        and state.turn_count == authoritative.turn_count
        and state.status == authoritative.status
        and state.outcome == authoritative.outcome
        and state.accepted_offer == authoritative.accepted_offer
    )
    if not compatible:
        raise ValueError("Session history does not reproduce the stored engine state")
    return _stairway_progression(scenario, turns), trajectory


def _criterion(
    criterion_id: str,
    title: str,
    score: int,
    maximum: int,
    explanation: str,
    evidence: list[EvidenceItem],
) -> ScoreCriterion:
    return ScoreCriterion(
        id=criterion_id,
        title=title,
        score=score,
        max_score=maximum,
        explanation=explanation,
        evidence=evidence,
    )


def _block(block_id: str, title: str, maximum: int, criteria: list[ScoreCriterion]) -> ScoreBlock:
    score = sum(item.score for item in criteria)
    return ScoreBlock(
        id=block_id,
        title=title,
        score=score,
        max_score=maximum,
        explanation=f"Набрано {score} из {maximum}: баллы подтверждены репликами участника и результатом движка.",
        criteria=criteria,
    )


def _outcome_analysis(scenario: ScenarioDefinition, session: NegotiationSession) -> OutcomeAnalysis:
    state = session.engine_state
    participant_utility: float | None = None
    batna_utility: int | None = None
    meets_batna: bool | None = None
    reservation_respected: bool | None = None
    accepted_terms: list[str] = []

    if state.accepted_offer is not None:
        assessment = assess_offer(scenario, state.accepted_offer)
        participant_result = next(
            item for item in assessment.role_utilities if item.role_id == state.participant_role_id
        )
        participant_utility = round(participant_result.utility, 1)
        batna_utility = participant_result.batna_utility
        meets_batna = participant_result.meets_batna
        reservation_respected = not any(
            item.role_id == state.participant_role_id for item in assessment.reservation_violations
        )
        issue_by_id = {item.id: item for item in scenario.issues}
        for item in state.accepted_offer.values:
            issue = issue_by_id[item.issue_id]
            accepted_terms.append(
                f"{issue.title}: {display_issue_value(item.value, issue.unit)}"
            )

    if state.outcome is NegotiationOutcome.AGREEMENT:
        kind, label = "agreement", "Соглашение достигнуто"
        description = "Пакет прошёл проверку допустимых границ обеих сторон и был зафиксирован."
    elif state.outcome is NegotiationOutcome.WALK_AWAY:
        kind, label = "walk_away", "Осознанный выход"
        description = "Переговоры завершены без сделки; качество выхода зависит от его обоснования и сохранения альтернатив."
    elif state.outcome is NegotiationOutcome.IMPASSE:
        kind, label = "impasse", "Переговорный тупик"
        description = "Стороны завершили диалог без жизнеспособного соглашения."
    else:
        kind, label = "incomplete", "Сессия завершена вручную"
        description = "Детерминированный движок не зафиксировал соглашение, тупик или осознанный выход."

    return OutcomeAnalysis(
        kind=kind,
        label=label,
        description=description,
        participant_utility=participant_utility,
        batna_utility=batna_utility,
        meets_batna=meets_batna,
        reservation_respected=reservation_respected,
        accepted_terms=accepted_terms,
    )


def _score_blocks(
    scenario: ScenarioDefinition,
    session: NegotiationSession,
    turns: list[_Turn],
    outcome: OutcomeAnalysis,
) -> list[ScoreBlock]:
    indicator_turns: dict[str, list[_Turn]] = {
        code: [turn for turn in turns if code in turn.indicators]
        for code in _INDICATOR_TITLES
    }
    option_turns = [turn for turn in turns if ActionTag.OPTION in turn.action.tags]
    multi_issue = [turn for turn in option_turns if len(turn.action.issue_values) >= 2]
    terminal = turns[-1] if turns else None

    outcome_points = 0
    outcome_text = "Итог не подтверждён движком."
    if outcome.kind == "agreement":
        outcome_points = 6 if outcome.meets_batna else 0
        if outcome.reservation_respected:
            outcome_points += 4
        outcome_text = "Соглашение сопоставлено с BATNA и собственной допустимой границей."
    elif outcome.kind == "walk_away":
        explicit = _first_turn(turns, tag=ActionTag.WALK_AWAY)
        outcome_points = 10 if explicit else 6
        outcome_text = "Выход из переговоров зафиксирован и оценён как альтернатива плохой сделке."
    elif outcome.kind == "impasse":
        outcome_points = 4
        outcome_text = "Зафиксировано отсутствие соглашения; полной защиты альтернативы нет."

    defense_points = 4 if option_turns or _first_turn(turns, tag=ActionTag.WALK_AWAY) else 0
    interest_sources = indicator_turns["I1"] + indicator_turns["I2"] + indicator_turns["I3"]
    disclosed = len(session.engine_state.disclosed_interest_ids)
    interest_points = 6 if disclosed >= 2 or (interest_sources and option_turns) else 3 if interest_sources else 0
    preparation_interests = min(10, defense_points + interest_points)

    q_points = 6 if len(indicator_turns["I1"]) >= 2 else 4 if indicator_turns["I1"] else 0
    listening_points = 6 if indicator_turns["I3"] and option_turns else 4 if indicator_turns["I3"] else 0
    questions_score = min(12, q_points + listening_points)
    criterion_turns = indicator_turns["I5"]
    applied_criterion = [
        turn
        for turn in criterion_turns
        if ActionTag.OPTION in turn.action.tags or ActionTag.ANCHOR in turn.action.tags
    ]
    strong_communication = bool(indicator_turns["I1"] or indicator_turns["I3"])
    criteria_score = 13 if len(criterion_turns) >= 2 or (applied_criterion and outcome.kind == "agreement" and strong_communication) else 9 if applied_criterion else 4 if criterion_turns else 0

    option_score = 8 if len(option_turns) >= 2 or indicator_turns["I8"] else 4 if option_turns else 0
    if indicator_turns["I7"]:
        option_score += 4
    option_score = min(12, option_score)
    if indicator_turns["N3"] and not indicator_turns["I7"] and not indicator_turns["I8"]:
        option_score = min(option_score, 2)
    module_turns = indicator_turns["I8"] + indicator_turns["I10"] + indicator_turns["I11"] + indicator_turns["I13"]
    module_success = bool(module_turns) and (outcome.kind == "agreement" or disclosed > 0)
    modules_score = 8 if module_success else 4 if module_turns else 0

    quality_score = 0
    if outcome.kind == "agreement":
        quality_score = (8 if outcome.meets_batna else 0) + (6 if outcome.reservation_respected else 0)
        if indicator_turns["I7"] or indicator_turns["I8"]:
            quality_score += 1
    elif outcome.kind == "walk_away":
        quality_score = 10 if _first_turn(turns, tag=ActionTag.WALK_AWAY) else 6
        quality_score += 3 if criterion_turns else 0
        quality_score += 2 if indicator_turns["I4"] else 0
    elif outcome.kind == "impasse":
        quality_score = 4
    quality_score = min(15, quality_score)
    if outcome.kind == "agreement" and outcome.meets_batna is False:
        quality_score = min(4, quality_score)

    commitments = indicator_turns["I12"]
    concrete_commitment = [
        turn
        for turn in commitments
        if turn.action.issue_values
        and _contains(turn.text, r"ответствен", r"срок", r"контрольн", r"метрик", r"еженедель")
    ]
    commitment_score = 10 if concrete_commitment else 5 if commitments else 0

    negative_tone = indicator_turns["N1"] + indicator_turns["N2"]
    tone_score = 0 if negative_tone else 4 if turns else 0
    if indicator_turns["I3"]:
        tone_score += 4
    if indicator_turns["I4"] or indicator_turns["I11"]:
        tone_score += 2
    tone_score = min(10, tone_score)

    blocks = [
        _block(
            "preparation",
            "Подготовка и защита интересов",
            20,
            [
                _criterion("preparation.outcome", "Результат не хуже BATNA", outcome_points, 10, outcome_text, _unique_evidence(terminal) if outcome_points else []),
                _criterion(
                    "preparation.interests",
                    "Выявление и защита интересов",
                    preparation_interests,
                    10,
                    "Учтены вопросы об интересах, раскрытая информация и защита собственных приоритетов.",
                    _unique_evidence(_first_turn(turns, indicator="I1") or _first_turn(turns, indicator="I2") or _first_turn(turns, indicator="I3"), option_turns[0] if option_turns else None) if preparation_interests else [],
                ),
            ],
        ),
        _block(
            "process",
            "Качество процесса",
            25,
            [
                _criterion("process.questions", "Вопросы и активное слушание", questions_score, 12, "Оцениваются содержательные вопросы и влияние услышанного на следующие ходы.", _unique_evidence(_first_turn(turns, indicator="I1"), _first_turn(turns, indicator="I3")) if questions_score else []),
                _criterion("process.criteria", "Объективные критерии", criteria_score, 13, "Проверяется не только упоминание ориентира, но и его применение к предложению.", _unique_evidence(criterion_turns[0] if criterion_turns else None, criterion_turns[1] if len(criterion_turns) > 1 else None) if criteria_score else []),
            ],
        ),
        _block(
            "value",
            "Создание и обмен ценностью",
            20,
            [
                _criterion("value.options", "Варианты и взаимные обмены", option_score, 12, "Учитываются многофакторные варианты и встречные условия.", _unique_evidence(multi_issue[0] if multi_issue else option_turns[0] if option_turns else None, _first_turn(turns, indicator="I7")) if option_score else []),
                _criterion("value.modules", "Контекстные методы", modules_score, 8, "Начисляются только разрешённые сценарием и результативные техники.", _unique_evidence(module_turns[0] if module_turns else None, module_turns[1] if len(module_turns) > 1 else None) if modules_score else []),
            ],
        ),
        _block(
            "result",
            "Качество результата",
            25,
            [
                _criterion("result.quality", "Качество соглашения или выхода", quality_score, 15, "Итог сопоставлен с BATNA, собственной границей и жизнеспособностью пакета.", _unique_evidence(terminal) if quality_score else []),
                _criterion("result.commitments", "Реализуемость обязательств", commitment_score, 10, "Проверяются действие, срок, ответственные и измеримые параметры.", _unique_evidence(concrete_commitment[0] if concrete_commitment else commitments[0] if commitments else None) if commitment_score else []),
            ],
        ),
        _block(
            "relationship",
            "Отношения и деловой тон",
            10,
            [
                _criterion("relationship.tone", "Уважительный деловой тон", tone_score, 10, "Учитываются отсутствие личного давления, слушание и совместная рамка.", _unique_evidence(_first_turn(turns, indicator="I3") or _first_turn(turns, indicator="I4") or (turns[0] if turns else None)) if tone_score else []),
            ],
        ),
    ]
    return blocks


def _penalties(turns: list[_Turn]) -> list[PenaltyItem]:
    result: list[PenaltyItem] = []
    for indicator_id, (penalty_id, title, points) in _PENALTY_MAP.items():
        matches = [turn for turn in turns if indicator_id in turn.indicators]
        if not matches:
            continue
        result.append(
            PenaltyItem(
                id=penalty_id,
                title=title,
                points=points,
                occurrences=len(matches),
                explanation=_INDICATOR_EXPLANATIONS[indicator_id],
                evidence=[_evidence(turn) for turn in matches],
            )
        )
    return result


def _strengths(turns: list[_Turn]) -> list[Finding]:
    result: list[Finding] = []
    seen: set[str] = set()
    for turn in turns:
        for code in turn.indicators:
            if not code.startswith("I") or code in seen:
                continue
            result.append(
                Finding(
                    code=code,
                    title=_INDICATOR_TITLES[code],
                    explanation=_INDICATOR_EXPLANATIONS[code],
                    points=_INDICATOR_POINTS[code],
                    evidence=[_evidence(turn)],
                )
            )
            seen.add(code)
            if len(result) == 5:
                return result
    return result


def _improvements(scenario: ScenarioDefinition, turns: list[_Turn]) -> list[Improvement]:
    present = {code for turn in turns for code in turn.indicators}
    negative_turn = next((turn for turn in turns if any(code.startswith("N") for code in turn.indicators)), None)
    options: list[tuple[str, str, str, str, str | None]] = []
    if negative_turn is not None:
        options.append((
            "Снизить давление",
            "Отделите человека от проблемы и назовите предмет разногласия без оценки личности.",
            "Вижу, что наши ограничения различаются. Давайте уточним, какой риск для вас сейчас критичен.",
            "I3",
            negative_turn.text,
        ))
    if "I1" not in present:
        options.append((
            "Сначала исследовать интерес",
            "Открытый вопрос даст данные для обмена, а не только для торга по позиции.",
            "Какие ограничения и приоритеты для вас наиболее важны в этом решении?",
            "I1",
            turns[0].text if turns else None,
        ))
    if "I3" not in present:
        options.append((
            "Показать активное слушание",
            "Перефразирование проверяет понимание и снижает риск спорить не с той проблемой.",
            "Правильно ли я понимаю, что для вас критично снизить риск и сохранить управляемый график?",
            "I3",
            None,
        ))
    if "I4" not in present:
        options.append((
            "Сформулировать общую задачу",
            "Совместная рамка помогает обсуждать ограничения как одну деловую проблему, а не как борьбу позиций.",
            "Давайте решим общую задачу: как получить измеримый результат и одновременно защитить ваши критичные ограничения.",
            "I4",
            turns[0].text if turns else None,
        ))
    if "I5" not in present:
        criterion = scenario.objective_criteria[0]
        options.append((
            "Опирайтесь на объективный критерий",
            "Проверяемый ориентир делает числовое предложение легитимным.",
            f"Предлагаю сверить условия с ориентиром «{criterion.title}» и применить его ко всему пакету.",
            "I5",
            None,
        ))
    if "I8" not in present and MethodologyModule.MESO in scenario.methodology_modules:
        options.append((
            "Предложить два пакета",
            "MESO выявляет приоритеты второй стороны без односторонней уступки.",
            "Предлагаю сравнить два равноценных пакета с разным балансом сроков, цены и обязательств. Какой ближе вашим приоритетам?",
            "I8",
            None,
        ))
    if "I7" not in present and MethodologyModule.INTEGRATIVE in scenario.methodology_modules:
        options.append((
            "Связать уступку со встречным условием",
            "Явный условный обмен защищает ценность и показывает, почему пакет выгоден обеим сторонам.",
            "Если мы усиливаем важный для вас параметр, то фиксируем встречное улучшение по нашему приоритету.",
            "I7",
            turns[-1].text if turns else None,
        ))
    if "I12" not in present:
        options.append((
            "Зафиксировать обязательства",
            "Итог должен определять ответственных, действие, срок и метрику контроля.",
            "Зафиксируем стороны, конкретные действия, сроки и измеримый критерий выполнения.",
            "I12",
            turns[-1].text if turns else None,
        ))

    return [
        Improvement(
            priority=index,
            title=title,
            original_quote=(original[:500] if original else None),
            suggested_text=suggested,
            rationale=rationale,
            indicator_id=indicator,
        )
        for index, (title, rationale, suggested, indicator, original) in enumerate(options[:3], start=1)
    ]


def _score_level(score: int) -> tuple[str, str]:
    if score >= 85:
        return "strong", "Сильные доказательно обоснованные переговоры"
    if score >= 70:
        return "working", "Рабочий результат с отдельными зонами улучшения"
    if score >= 50:
        return "unstable", "Процесс или соглашение нестабильны"
    return "risk", "Высокий риск плохой сделки или эскалации"


def evaluate_session(scenario: ScenarioDefinition, session: NegotiationSession) -> ReportResponse:
    """Build a reproducible report without delegating scoring to an LLM."""

    turns, trajectory = _replay(scenario, session)
    outcome = _outcome_analysis(scenario, session)
    blocks = _score_blocks(scenario, session, turns, outcome)
    penalties = _penalties(turns)
    raw_score = sum(block.score for block in blocks)
    penalty_points = sum(item.points * item.occurrences for item in penalties)
    score = max(0, min(100, raw_score + penalty_points))
    score_cap = 59 if outcome.kind == "agreement" and outcome.meets_batna is False else None
    if score_cap is not None:
        score = min(score, score_cap)
    level, label = _score_level(score)

    if outcome.kind == "agreement":
        summary = f"Соглашение достигнуто. Итоговая оценка — {score} из 100; сильные стороны и зоны роста подтверждены цитатами."
    elif outcome.kind == "incomplete":
        summary = f"Сессия завершена до подтверждённого исхода. Процесс оценён в {score} из 100 по доступным репликам."
    else:
        summary = f"Сделка не заключена. Качество процесса и завершения оценено в {score} из 100."

    return ReportResponse(
        session_id=session.id,
        scenario_id=session.scenario_id,
        scenario_version_id=session.scenario_version_id,
        rubric_version=DEFAULT_RUBRIC_V01.version,
        evaluator_version=EVALUATOR_VERSION,
        status=session.status,
        score=score,
        level=level,
        label=label,
        summary=summary,
        outcome=outcome,
        blocks=blocks,
        penalties=penalties,
        strengths=_strengths(turns),
        improvements=_improvements(scenario, turns),
        task_checks=evaluate_task_checks(scenario, session),
        trajectory=trajectory,
        methodology=MethodologyInfo(
            rubric_version=DEFAULT_RUBRIC_V01.version,
            formula="Final = clamp(0, 100, P + C + V + R + T + penalties)",
            raw_score=raw_score,
            penalty_points=penalty_points,
            score_cap=score_cap,
            disclaimer="Рубрика 0.1 является методической гипотезой MVP и требует экспертной калибровки перед кадровым применением.",
        ),
        next_step=(
            "Повторите тот же сценарий и целенаправленно примените первую рекомендованную формулировку."
            if turns
            else "Проведите полноценную сессию, чтобы получить доказательный разбор."
        ),
    )
