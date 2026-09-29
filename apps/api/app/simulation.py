"""Deterministic simulation runtime around the authoritative engine."""

from __future__ import annotations

import hashlib
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from .engine import DirectiveKind, NegotiationStatus
from .models import (
    CheckSimulationHypothesisRequest,
    CheckSimulationHypothesisResponse,
    InteractionMode,
    Message,
    NegotiationPhase,
    NegotiationSession,
    OpponentStrategy,
    PublicSimulationOpponent,
    ReportResponse,
    SimulationAssessment,
    SimulationDisclosure,
    SimulationEvent,
    SimulationHypothesis,
    SimulationOpponent,
    SimulationSnapshot,
    SimulationState,
    utc_now,
)
from .repository import SessionRepository


_EVENT_LIBRARY: dict[str, tuple[str, str]] = {
    "budget": (
        "Бюджет отправлен на повторное согласование",
        "Финансовый контур запросил дополнительное обоснование расходов. Экономические границы кейса не изменились, но решение теперь требует ясного критерия ценности.",
    ),
    "deadline": (
        "Окно решения сократилось",
        "Внутренний календарь ускорился: сторонам нужно быстрее зафиксировать следующий проверяемый шаг. Допустимая область сделки сохранена.",
    ),
    "authority": (
        "Появилось ограничение полномочий",
        "Представителю второй стороны потребуется отдельно подтвердить нестандартное условие у руководителя. ZOPA и reservation points не менялись.",
    ),
    "resource": (
        "Ключевой ресурс стал менее доступен",
        "Команда исполнения сообщила о конкурирующей нагрузке. Нужны приоритеты и реалистичная фиксация обязательств без изменения скрытой экономики кейса.",
    ),
}

_STYLE_LABELS = {
    OpponentStrategy.ANALYTICAL: "Аналитический",
    OpponentStrategy.COLLABORATIVE: "Партнёрский",
    OpponentStrategy.COMPETITIVE: "Конкурентный",
    OpponentStrategy.CAUTIOUS: "Осторожный",
}


def initialize_simulation(
    session: NegotiationSession,
    *,
    seed_override: int | None = None,
) -> SimulationState:
    settings = session.configuration.simulation
    if not settings.enabled:
        return SimulationState()
    seed = seed_override if seed_override is not None else settings.seed
    if seed is None:
        seed = secrets.randbelow(2_147_483_648)
    rng = random.Random(seed)

    opponent_specs = [
        ("opponent_1", session.configuration.opponent_role, session.configuration.opponent_role, settings.opponent_strategy),
        ("opponent_2", "Финансовый контролёр", "Проверяет экономическую обоснованность и критерии", OpponentStrategy.ANALYTICAL),
        ("opponent_3", "Руководитель исполнения", "Отвечает за сроки, ресурсы и исполнимость", OpponentStrategy.CAUTIOUS),
    ]
    opponents = [
        SimulationOpponent(id=item[0], label=item[1], role=item[2], strategy=item[3])
        for item in opponent_specs[: settings.ai_participants]
    ]

    possible_turns = list(range(2, max(3, session.configuration.max_turns)))
    rng.shuffle(possible_turns)
    kinds = list(_EVENT_LIBRARY)
    rng.shuffle(kinds)
    schedule: list[SimulationEvent] = []
    for index in range(min(settings.event_intensity, len(possible_turns))):
        kind = kinds[index % len(kinds)]
        title, description = _EVENT_LIBRARY[kind]
        schedule.append(
            SimulationEvent(
                id=f"{kind}-{index + 1}-{seed % 997}",
                kind=kind,  # type: ignore[arg-type]
                title=title,
                description=description,
                trigger_turn=possible_turns[index],
                severity=1 + rng.randrange(3),
            )
        )
    schedule.sort(key=lambda item: item.trigger_turn)
    now = utc_now()
    return SimulationState(
        enabled=True,
        seed=seed,
        mode=settings.mode,
        decision_time_seconds=settings.decision_time_seconds,
        server_time=now,
        # The first opening is not a response to an opponent, so its timer is
        # armed only after the first opponent turn. This also keeps prebrief
        # time outside the negotiation clock.
        deadline_at=None,
        event_schedule=schedule,
        opponents=opponents,
    )


def public_simulation(state: SimulationState) -> SimulationSnapshot:
    return SimulationSnapshot(
        enabled=state.enabled,
        seed=state.seed,
        mode=state.mode,
        phase=state.phase,
        decision_time_seconds=state.decision_time_seconds,
        deadline_at=state.deadline_at,
        server_time=state.server_time,
        timed_out_decisions=state.timed_out_decisions,
        pressure_score=state.pressure_score,
        events=state.events,
        disclosures=state.disclosures,
        hypotheses=state.hypotheses,
        opponents=[
            PublicSimulationOpponent(
                id=item.id,
                label=item.label,
                role=item.role,
                strategy=item.strategy,
            )
            for item in state.opponents
        ],
    )


def _phase_for(session: NegotiationSession) -> NegotiationPhase:
    turn = session.engine_state.turn_count
    maximum = session.configuration.max_turns
    if turn <= 0:
        return NegotiationPhase.PREPARATION
    if turn == 1:
        return NegotiationPhase.OPENING
    if turn <= max(2, round(maximum * 0.35)):
        return NegotiationPhase.EXPLORATION
    if session.engine_state.progress >= 70 or turn >= maximum - 2:
        return NegotiationPhase.COMMITMENT
    return NegotiationPhase.EXCHANGE


def before_participant_turn(session: NegotiationSession) -> Message | None:
    state = session.simulation_state
    if not state.enabled or state.deadline_at is None or utc_now() <= state.deadline_at:
        return None
    state.timed_out_decisions += 1
    state.pressure_score = min(100, state.pressure_score + 8)
    state.deadline_at = None
    return Message(
        role="system",
        content="Время на решение истекло. Реплика будет принята, но в отчёте отмечено дополнительное давление среды.",
        speaker_id="simulation_clock",
        speaker_label="Таймер решения",
        message_kind="timeout",
    )


def after_engine_turn(
    session: NegotiationSession,
    *,
    public_facts: tuple[str, ...],
) -> list[Message]:
    state = session.simulation_state
    if not state.enabled:
        return []
    state.phase = _phase_for(session)

    existing_fact_texts = {item.text for item in state.disclosures}
    for fact in public_facts:
        if fact in existing_fact_texts:
            continue
        digest = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:12]
        state.disclosures.append(
            SimulationDisclosure(
                id=f"fact-{digest}",
                text=fact,
                source_turn=max(1, session.engine_state.turn_count),
            )
        )
        existing_fact_texts.add(fact)

    triggered = [
        item
        for item in state.event_schedule
        if item.trigger_turn == session.engine_state.turn_count
        and all(current.id != item.id for current in state.events)
    ]
    messages: list[Message] = []
    for event in triggered:
        state.events.append(event)
        state.pressure_score = min(100, state.pressure_score + event.severity * 10)
        messages.append(
            Message(
                role="system",
                content=f"{event.title}. {event.description}",
                speaker_id=event.id,
                speaker_label="Неожиданное событие",
                message_kind="event",
            )
        )
    return messages


def start_next_decision_window(session: NegotiationSession) -> None:
    """Arm the next timer only after every opponent has finished replying."""
    state = session.simulation_state
    if not state.enabled:
        return
    now = utc_now()
    state.server_time = now
    if session.engine_state.status is NegotiationStatus.ACTIVE and state.decision_time_seconds:
        state.deadline_at = now + timedelta(seconds=state.decision_time_seconds)
    else:
        state.deadline_at = None


def _terminal_secondary(kind: DirectiveKind) -> str | None:
    return {
        DirectiveKind.ACCEPT: "Со своей стороны подтверждаю согласованный пакет и готовность перейти к фиксации.",
        DirectiveKind.IMPASSE: "Фиксирую, что общего решения сейчас нет; новые обязательства не принимаю.",
        DirectiveKind.WALK_AWAY: "Подтверждаю корректное завершение переговоров без соглашения.",
    }.get(kind)


def additional_opponent_messages(
    session: NegotiationSession,
    *,
    participant_text: str,
    directive_kind: DirectiveKind,
) -> list[Message]:
    state = session.simulation_state
    if not state.enabled or len(state.opponents) <= 1:
        return []
    terminal = _terminal_secondary(directive_kind)
    active_event = state.events[-1].title if state.events else None
    messages: list[Message] = []
    for opponent in state.opponents[1:]:
        if terminal:
            content = terminal
        elif opponent.strategy is OpponentStrategy.ANALYTICAL:
            content = "На каком проверяемом критерии основано это предложение и как вы предлагаете измерить результат?"
        elif opponent.strategy is OpponentStrategy.COLLABORATIVE:
            content = "Вижу пространство для общего решения. Какие два варианта пакета вы готовы сравнить?"
        elif opponent.strategy is OpponentStrategy.COMPETITIVE:
            content = "Нам нужен более сильный встречный пакет; одностороннего движения с нашей стороны не будет."
        else:
            content = "Прежде чем двигаться дальше, уточните риски исполнения, ответственного и контрольную дату."
        if active_event:
            content = f"С учётом события «{active_event}» {content[0].lower()}{content[1:]}"
        opponent.memory = [*opponent.memory[-6:], participant_text[:240], content[:240]]
        messages.append(
            Message(
                role="opponent",
                content=content,
                speaker_id=opponent.id,
                speaker_label=opponent.label,
            )
        )
    return messages


def remember_primary(session: NegotiationSession, participant_text: str, reply: str) -> None:
    if not session.simulation_state.enabled or not session.simulation_state.opponents:
        return
    primary = session.simulation_state.opponents[0]
    primary.memory = [*primary.memory[-6:], participant_text[:240], reply[:240]]


_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.IGNORECASE)


def check_hypothesis(
    repository: SessionRepository,
    session: NegotiationSession,
    payload: CheckSimulationHypothesisRequest,
) -> CheckSimulationHypothesisResponse:
    state = session.simulation_state
    if not state.enabled:
        raise ValueError("simulation_disabled")
    if len(state.hypotheses) >= 20:
        raise ValueError("hypothesis_limit")
    words = set(_WORD_RE.findall(payload.text.casefold()))
    evidence = None
    best_overlap = 0
    for fact in state.disclosures:
        overlap = len(words & set(_WORD_RE.findall(fact.text.casefold())))
        if overlap > best_overlap:
            evidence, best_overlap = fact, overlap
    negative = bool(re.search(r"\b(?:не|нет|никогда|отсутств)\w*\b", payload.text.casefold()))
    if evidence is None or best_overlap < 2:
        status = "insufficient"
        explanation = "В открытой части диалога пока недостаточно фактов. Задайте уточняющий вопрос и проверьте гипотезу наблюдаемыми данными."
        evidence_id = None
    elif negative:
        status = "refuted"
        explanation = f"Гипотеза противоречит уже раскрытому факту: «{evidence.text}»"
        evidence_id = evidence.id
    else:
        status = "confirmed"
        explanation = f"Гипотеза поддерживается раскрытым фактом: «{evidence.text}»"
        evidence_id = evidence.id
    hypothesis = SimulationHypothesis(
        text=payload.text,
        status=status,  # type: ignore[arg-type]
        explanation=explanation,
        evidence_fact_id=evidence_id,
    )
    state.hypotheses.append(hypothesis)
    repository.save(session)
    return CheckSimulationHypothesisResponse(
        hypothesis=hypothesis,
        simulation=public_simulation(state),
    )


def simulation_assessment(session: NegotiationSession, report: ReportResponse) -> SimulationAssessment | None:
    state = session.simulation_state
    if not state.enabled:
        return None
    participant_count = max(1, len(state.opponents))
    mode_pressure = {
        InteractionMode.MEETING: 4,
        InteractionMode.CORRESPONDENCE: 8,
        InteractionMode.ESCALATION: 18,
    }[state.mode]
    pressure = min(
        100,
        state.pressure_score
        + state.timed_out_decisions * 8
        + (participant_count - 1) * 12
        + mode_pressure,
    )
    return SimulationAssessment(
        participant_skill_score=report.score,
        environment_pressure_score=pressure,
        event_count=len(state.events),
        timed_out_decisions=state.timed_out_decisions,
        ai_participants=participant_count,
        phase_reached=state.phase,
        mode=state.mode,
        interpretation=(
            "Навык участника рассчитан по единой рубрике. Давление среды показано отдельно и не добавляет скрытых бонусов или штрафов к официальному баллу."
        ),
    )


def strategy_label(strategy: OpponentStrategy) -> str:
    return _STYLE_LABELS[strategy]


__all__ = [
    "additional_opponent_messages",
    "after_engine_turn",
    "before_participant_turn",
    "check_hypothesis",
    "initialize_simulation",
    "public_simulation",
    "start_next_decision_window",
    "remember_primary",
    "simulation_assessment",
    "strategy_label",
]
