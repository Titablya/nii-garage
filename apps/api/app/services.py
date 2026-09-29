from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import secrets
from uuid import UUID

from .domain.scenario import Difficulty, ScenarioDefinition, Tone, TurnLimits
from .engine import (
    DirectiveKind,
    NegotiationStatus,
    OpponentDirective,
    initial_state,
    transition_turn,
)
from .models import (
    GenerationMetadata,
    InteractionMode,
    Message,
    NegotiationSession,
    ReportResponse,
    Scenario,
    SessionConfiguration,
    SessionDifficulty,
    SessionTone,
    SessionStatus,
)
from .llm.opponent import OpponentGenerator
from .reporting import evaluate_session
from .repository import SessionRepository
from .scenario_catalog import ScenarioCatalog
from .random_scenarios import is_random_scenario_id
from .speech import opening_line_for
from .simulation import (
    additional_opponent_messages,
    after_engine_turn,
    before_participant_turn,
    initialize_simulation,
    remember_primary,
    simulation_assessment,
    start_next_decision_window,
)


def list_scenarios(catalog: ScenarioCatalog) -> tuple[Scenario, ...]:
    return tuple(
        item for item in catalog.list()
        if not is_random_scenario_id(item.id) and item.source != "custom"
    )


def list_catalog_scenarios(
    catalog: ScenarioCatalog,
    *,
    industry: str | None = None,
    role: str | None = None,
    difficulty: str | None = None,
    method: str | None = None,
    max_minutes: int | None = None,
) -> tuple[Scenario, ...]:
    items = tuple(item for item in catalog.list() if item.source == "curated")
    if industry:
        items = tuple(item for item in items if item.industry.casefold() == industry.casefold())
    if role:
        needle = role.casefold()
        items = tuple(item for item in items if any(needle in tag.casefold() for tag in item.role_tags))
    if difficulty:
        items = tuple(item for item in items if item.difficulty == difficulty)
    if method:
        items = tuple(item for item in items if method in item.methods)
    if max_minutes is not None:
        items = tuple(item for item in items if item.estimated_minutes <= max_minutes)
    return tuple(sorted(items, key=lambda item: (item.theme, item.title)))


def get_random_scenario(
    catalog: ScenarioCatalog, exclude_id: str | None = None
) -> Scenario | None:
    candidates = tuple(
        item
        for item in catalog.list()
        if is_random_scenario_id(item.id) and item.id != exclude_id
    )
    return secrets.choice(candidates) if candidates else None


def get_scenario(catalog: ScenarioCatalog, scenario_id: str) -> Scenario | None:
    return catalog.get(scenario_id)


_DIFFICULTY_TO_DOMAIN = {
    SessionDifficulty.EASY: Difficulty.BEGINNER,
    SessionDifficulty.MEDIUM: Difficulty.INTERMEDIATE,
    SessionDifficulty.HARD: Difficulty.ADVANCED,
}
_TONE_TO_DOMAIN = {
    SessionTone.COOPERATIVE: Tone.COOPERATIVE,
    SessionTone.BUSINESSLIKE: Tone.BUSINESSLIKE,
    SessionTone.FIRM: Tone.ASSERTIVE,
}


def default_session_configuration(
    public_scenario: Scenario, definition: ScenarioDefinition
) -> SessionConfiguration:
    difficulty = {
        Difficulty.BEGINNER: SessionDifficulty.EASY,
        Difficulty.INTERMEDIATE: SessionDifficulty.MEDIUM,
        Difficulty.ADVANCED: SessionDifficulty.HARD,
    }[definition.difficulty]
    tone = {
        Tone.COOPERATIVE: SessionTone.COOPERATIVE,
        Tone.BUSINESSLIKE: SessionTone.BUSINESSLIKE,
        Tone.ASSERTIVE: SessionTone.FIRM,
        Tone.TENSE: SessionTone.FIRM,
    }[definition.tone]
    return SessionConfiguration(
        topic=public_scenario.title,
        context=public_scenario.context,
        participant_role=public_scenario.participant_role,
        opponent_role=public_scenario.opponent_role,
        objective=public_scenario.objective,
        difficulty=difficulty,
        tone=tone,
        max_turns=definition.turn_limits.maximum,
    )


def materialize_session_definition(
    definition: ScenarioDefinition, configuration: SessionConfiguration
) -> ScenarioDefinition:
    """Create a safe per-session definition without changing hidden boundaries."""

    base_limits = definition.turn_limits
    maximum = configuration.max_turns
    minimum = min(base_limits.minimum, maximum - 1)
    warning_at = max(minimum, min(base_limits.warning_at, maximum - 1))

    # Difficulty only changes conversational starting signals.  Ranges,
    # BATNA, reservation points, ZOPA and rubric remain from the base case.
    difficulty_deltas = {
        SessionDifficulty.EASY: (8, -8, 8),
        SessionDifficulty.MEDIUM: (0, 0, 0),
        SessionDifficulty.HARD: (-8, 8, -8),
    }
    trust_delta, tension_delta, relationship_delta = difficulty_deltas[configuration.difficulty]
    mode_deltas = {
        InteractionMode.MEETING: (0, 0, 0),
        InteractionMode.CORRESPONDENCE: (-2, 3, -2),
        InteractionMode.ESCALATION: (-8, 12, -8),
    }
    mode_trust, mode_tension, mode_relationship = mode_deltas[configuration.simulation.mode]
    base_state = definition.initial_state
    initial_state = base_state.model_copy(
        update={
            "trust": max(0, min(100, base_state.trust + trust_delta + mode_trust)),
            "tension": max(0, min(100, base_state.tension + tension_delta + mode_tension)),
            "relationship": max(0, min(100, base_state.relationship + relationship_delta + mode_relationship)),
        }
    )
    briefing = definition.public_briefing.model_copy(
        update={
            "title": configuration.topic,
            "summary": configuration.context,
            "situation": configuration.context,
            "objective": configuration.objective,
        }
    )
    return definition.model_copy(
        deep=True,
        update={
            "public_briefing": briefing,
            "initial_state": initial_state,
            "difficulty": _DIFFICULTY_TO_DOMAIN[configuration.difficulty],
            "tone": _TONE_TO_DOMAIN[configuration.tone],
            "turn_limits": TurnLimits(
                minimum=minimum,
                warning_at=warning_at,
                maximum=maximum,
            ),
        },
    )


def materialize_public_scenario(
    public_scenario: Scenario, configuration: SessionConfiguration
) -> Scenario:
    return public_scenario.model_copy(
        update={
            "title": configuration.topic,
            "summary": configuration.context,
            "context": configuration.context,
            "participant_role": configuration.participant_role,
            "opponent_role": configuration.opponent_role,
            "objective": configuration.objective,
            "difficulty": configuration.difficulty.value,
            "tone": configuration.tone.value,
        }
    )


def create_session(
    repository: SessionRepository,
    catalog: ScenarioCatalog,
    scenario_id: str,
    configuration: SessionConfiguration | None = None,
    participant_user_id: UUID | None = None,
    session_id: UUID | None = None,
) -> NegotiationSession:
    definition = catalog.get_definition(scenario_id)
    if definition is None:
        raise KeyError("scenario_not_found")
    public_scenario = catalog.get(scenario_id)
    if public_scenario is None:
        raise KeyError("scenario_not_found")
    session_configuration = configuration or default_session_configuration(public_scenario, definition)
    materialized = materialize_session_definition(definition, session_configuration)
    state = initial_state(materialized)
    session = NegotiationSession(
            **({"id": session_id} if session_id is not None else {}),
            scenario_id=scenario_id,
            participant_user_id=participant_user_id,
            scenario_version_id=definition.metadata.version_id,
            configuration=session_configuration,
            engine_state=state,
        )
    session.simulation_state = initialize_simulation(session)
    return repository.create(session)


def retry_session(
    repository: SessionRepository, catalog: ScenarioCatalog, session_id: UUID
) -> NegotiationSession:
    previous = repository.get(session_id)
    if previous is None:
        raise KeyError("session_not_found")
    if previous.status != SessionStatus.COMPLETED:
        raise ValueError("session_not_completed")
    definition = catalog.get_definition(previous.scenario_id)
    if definition is None or definition.metadata.version_id != previous.scenario_version_id:
        raise ValueError("scenario_version_unavailable")
    attempt_number = max(
        (item.attempt_number for item in repository.list_series(previous.series_id)),
        default=previous.attempt_number,
    ) + 1
    materialized = materialize_session_definition(definition, previous.configuration)
    session = NegotiationSession(
            series_id=previous.series_id,
            previous_session_id=previous.id,
            attempt_number=attempt_number,
            participant_user_id=previous.participant_user_id,
            scenario_id=previous.scenario_id,
            scenario_version_id=previous.scenario_version_id,
            configuration=previous.configuration,
            engine_state=initial_state(materialized),
        )
    session.simulation_state = initialize_simulation(
        session,
        seed_override=previous.simulation_state.seed if previous.simulation_state.enabled else None,
    )
    return repository.create(session)


async def add_participant_message(
    repository: SessionRepository,
    catalog: ScenarioCatalog,
    opponent_generator: OpponentGenerator,
    session_id: UUID,
    content: str,
) -> tuple[NegotiationSession, Message, list[Message], list[Message], GenerationMetadata]:
    session = repository.get(session_id)
    if session is None:
        raise KeyError("session_not_found")
    if (
        session.status == SessionStatus.COMPLETED
        or session.engine_state.status is NegotiationStatus.COMPLETED
    ):
        raise ValueError("session_completed")

    definition = catalog.get_definition(session.scenario_id)
    if definition is None:
        raise KeyError("scenario_not_found")
    public_scenario = catalog.get(session.scenario_id)
    if public_scenario is None:
        raise KeyError("scenario_not_found")
    definition = materialize_session_definition(definition, session.configuration)
    public_scenario = materialize_public_scenario(public_scenario, session.configuration)

    timeout_message = before_participant_turn(session)
    participant = Message(
        role="participant",
        content=content.strip(),
        speaker_id="participant",
        speaker_label=session.configuration.participant_role,
    )
    transition = transition_turn(definition, session.engine_state, participant.content)
    session.engine_state = transition.state
    session.reason_events.extend(transition.events)
    if transition.state.status is NegotiationStatus.COMPLETED:
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc)
    event_messages = after_engine_turn(
        session,
        public_facts=transition.directive.public_facts,
    )
    issue_labels = {
        issue.id: (issue.title, issue.unit)
        for issue in definition.issues
    }
    fallback = mock_opponent_reply(transition.directive, issue_labels)
    # The visible/voiced opener is client-side and is not persisted as a turn.
    # Include that public line in the first model context so the next reply
    # does not contradict the opponent's stated starting position.
    prompt_messages = (*session.messages, participant)
    if transition.from_turn == 0:
        prompt_messages = (
            Message(
                role="opponent",
                content=opening_line_for(session.scenario_id, public_scenario.negotiation_type),
                speaker_label=public_scenario.opponent_role,
            ),
            *prompt_messages,
        )
    generation = await opponent_generator.generate(
        briefing=definition.public_briefing,
        opponent_role=public_scenario.opponent_role,
        issue_guide={
            issue.id: f"{issue.title}. {issue.description} Единица измерения: {issue.unit}."
            for issue in definition.issues
        },
        messages=prompt_messages,
        directive=transition.directive,
        fallback=fallback,
        tone=session.configuration.tone.value,
        difficulty=session.configuration.difficulty.value,
        participant_role=session.configuration.participant_role,
        strategy=session.configuration.simulation.opponent_strategy.value,
        interaction_mode=session.configuration.simulation.mode.value,
        phase=session.simulation_state.phase.value,
        active_event=(session.simulation_state.events[-1].title if session.simulation_state.events else None),
        scenario=definition,
    )
    primary = session.simulation_state.opponents[0] if session.simulation_state.opponents else None
    opponent = Message(
        role="opponent",
        content=generation.content,
        speaker_id=primary.id if primary else "opponent_1",
        speaker_label=primary.label if primary else session.configuration.opponent_role,
    )
    remember_primary(session, participant.content, opponent.content)
    opponents = [
        opponent,
        *additional_opponent_messages(
            session,
            participant_text=participant.content,
            directive_kind=transition.directive.kind,
        ),
    ]
    start_next_decision_window(session)
    turn_messages = [participant]
    if timeout_message is not None:
        turn_messages.append(timeout_message)
    turn_messages.extend(event_messages)
    turn_messages.extend(opponents)
    session.messages.extend(turn_messages)
    repository.save(session)
    simulation_messages = ([timeout_message] if timeout_message is not None else []) + event_messages
    return session, participant, opponents, simulation_messages, generation.metadata


def complete_session(repository: SessionRepository, session_id: UUID) -> NegotiationSession:
    session = repository.get(session_id)
    if session is None:
        raise KeyError("session_not_found")
    if session.status == SessionStatus.ACTIVE:
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc)
        repository.save(session)
    return session


def build_report(catalog: ScenarioCatalog, session: NegotiationSession) -> ReportResponse:
    definition = catalog.get_definition(session.scenario_id)
    if definition is None or definition.metadata.version_id != session.scenario_version_id:
        raise ValueError("scenario_version_mismatch")
    report = evaluate_session(
        materialize_session_definition(definition, session.configuration),
        session,
    )
    return report.model_copy(update={"simulation": simulation_assessment(session, report)})


def public_explanation(session: NegotiationSession) -> str:
    """A safe summary. Never serialize engine events or state internals to clients."""
    if session.engine_state.outcome is not None:
        return {
            "agreement": "Соглашение достигнуто; условия зафиксированы в ходе диалога.",
            "impasse": "Переговоры завершены без соглашения: позиции больше не продвигаются.",
            "walk_away": "Переговоры корректно завершены без жизнеспособной сделки.",
        }[session.engine_state.outcome.value]
    if session.engine_state.turn_count == 0:
        return "Переговоры ещё не начались. Начните с вопроса о приоритетах и ограничениях."
    return "Последняя реплика обработана детерминированным переговорным движком."


def _display_number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:.6f}".rstrip("0").rstrip(".").replace(".", ",")


def _counted_unit(value: float, one: str, few: str, many: str) -> str:
    if not value.is_integer():
        return few
    count = abs(int(value))
    if 11 <= count % 100 <= 14:
        return many
    if count % 10 == 1:
        return one
    if 2 <= count % 10 <= 4:
        return few
    return many


def _display_issue_value(value: float, unit: str) -> str:
    if unit == "рублей" and abs(value) >= 1_000_000:
        return f"{_display_number(value / 1_000_000)} млн рублей"
    if unit == "миллионов рублей":
        return f"{_display_number(value)} млн рублей"
    forms = {
        "человек": ("человек", "человека", "человек"),
        "дней": ("день", "дня", "дней"),
        "месяцев": ("месяц", "месяца", "месяцев"),
        "часов в неделю": ("час в неделю", "часа в неделю", "часов в неделю"),
        "процентов": ("процент", "процента", "процентов"),
        "процентов в день": ("процент в день", "процента в день", "процентов в день"),
    }
    if unit in forms:
        return f"{_display_number(value)} {_counted_unit(value, *forms[unit])}"
    return f"{_display_number(value)} {unit}"


def mock_opponent_reply(
    directive: OpponentDirective,
    issue_labels: Mapping[str, tuple[str, str]] | None = None,
) -> str:
    """Render only public directive data; do not inspect scenario secrets or engine state."""
    fact = f" {directive.public_facts[0]}" if directive.public_facts else ""
    counter = "Я подготовил встречный вариант по обсуждаемым вопросам."
    if directive.kind is DirectiveKind.COUNTER and directive.offer is not None and issue_labels:
        terms = []
        agenda_order = {issue_id: index for index, issue_id in enumerate(issue_labels)}
        for item in sorted(
            directive.offer.values,
            key=lambda value: agenda_order.get(value.issue_id, len(agenda_order)),
        ):
            label = issue_labels.get(item.issue_id)
            if label is None:
                continue
            title, unit = label
            terms.append(f"{title} — {_display_issue_value(item.value, unit)}")
        if terms:
            counter = "Понимаю ваш запрос. Пока могу предложить такой пакет: " + "; ".join(terms) + "."
    templates = {
        DirectiveKind.ACCEPT: "Согласен. Зафиксируем достигнутые договорённости.",
        DirectiveKind.COUNTER: counter,
        DirectiveKind.CLARIFY: "Понимаю. Уточните, пожалуйста, приоритеты и условия предложения.",
        DirectiveKind.IMPASSE: "Похоже, сейчас мы зашли в тупик. Предлагаю зафиксировать отсутствие соглашения.",
        DirectiveKind.WALK_AWAY: "В текущих условиях не можем продолжать к соглашению; корректно завершим переговоры.",
    }
    return templates[directive.kind] + fact
