from __future__ import annotations

import asyncio
import json

from app.engine import initial_state, transition_turn
from app.llm import GenerationRequest, GenerationResponse, LLMProvider, ReportCoach
from app.models import Message, NegotiationSession, SessionConfiguration, SessionStatus
from app.reporting import evaluate_session
from app.scenario_catalog import DEFAULT_SCENARIOS_PATH, load_scenario_catalog


class FixedProvider(LLMProvider):
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return GenerationResponse(reply=self.reply)


def _case() -> tuple[object, object, NegotiationSession, str]:
    catalog = load_scenario_catalog(DEFAULT_SCENARIOS_PATH)
    definition = catalog.get_definition("equipment-supply")
    public = catalog.get("equipment-supply")
    assert definition is not None and public is not None
    text = "Нам нужна скидка. Предлагаю цену 9,8 млн рублей."
    state = transition_turn(definition, initial_state(definition), text).state
    session = NegotiationSession(
        scenario_id="equipment-supply",
        scenario_version_id=definition.metadata.version_id,
        configuration=SessionConfiguration(
            topic=public.title,
            context=public.context,
            participant_role=public.participant_role,
            opponent_role=public.opponent_role,
            objective=public.objective,
            max_turns=public.max_turns,
        ),
        engine_state=state,
        status=SessionStatus.COMPLETED,
        messages=[Message(role="participant", content=text)],
    )
    return definition, public, session, text


def test_gemini_coaching_uses_exact_dialogue_quotes_without_changing_score() -> None:
    definition, public, session, text = _case()
    report = evaluate_session(definition, session)  # type: ignore[arg-type]
    provider = FixedProvider(json.dumps({
        "summary": "Цена названа без исследования интересов поставщика.",
        "points": [{
            "turn": 1,
            "quote": text,
            "problem": "Позиционный торг начат слишком рано.",
            "better_approach": "Сначала выяснить причины ценового ограничения.",
            "suggested_text": "Какие затраты и риски определяют вашу минимальную цену?",
        }],
    }, ensure_ascii=False))

    enriched = asyncio.run(ReportCoach(provider, model="test-gemini").enrich(
        scenario=public, session=session, report=report  # type: ignore[arg-type]
    ))

    assert enriched.score == report.score
    assert enriched.coaching is not None
    assert enriched.coaching.provider == "gemini"
    assert enriched.coaching.points[0].quote == text
    assert len(provider.requests) == 1
    prompt = provider.requests[0].prompt.casefold()
    assert text.casefold() in prompt
    assert public.participant_role.casefold() in prompt
    assert public.opponent_role.casefold() in prompt
    assert "не давай советов от лица оппонента" in prompt
    assert "deterministic_improvements или block_gaps" in prompt
    assert not any(secret in prompt for secret in ("hidden_interests", "engine_state", "concession_budget"))


def test_inexact_gemini_quote_is_replaced_with_verified_dialogue_text() -> None:
    definition, public, session, text = _case()
    report = evaluate_session(definition, session)  # type: ignore[arg-type]
    provider = FixedProvider(json.dumps({
        "summary": "Разбор",
        "points": [{
            "turn": 1,
            "quote": "Цитата, которой не было",
            "problem": "Ошибка",
            "better_approach": "Другой подход",
            "suggested_text": "Улучшенная реплика",
        }],
    }, ensure_ascii=False))

    enriched = asyncio.run(ReportCoach(provider).enrich(
        scenario=public, session=session, report=report  # type: ignore[arg-type]
    ))

    assert enriched.coaching is not None
    assert enriched.coaching.provider == "gemini"
    assert enriched.coaching.fallback is False
    assert enriched.coaching.points[0].quote == text
