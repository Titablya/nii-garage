from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.scenario import ScenarioDefinition
from app.engine import DirectiveKind, OpponentDirective, ReasonCode
from app.engine.contracts import IssueValue, NegotiationOffer
from app.llm.prompting import (
    build_opponent_prompt,
    serialize_provider_request,
    validate_directive_alignment,
    validate_opponent_reply,
)
from app.models import Message


SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "scenarios"


def _scenario() -> ScenarioDefinition:
    return ScenarioDefinition.model_validate_json(
        (SCENARIOS_PATH / "equipment-supply.v1.json").read_text(encoding="utf-8")
    )


def _directive(kind: DirectiveKind = DirectiveKind.CLARIFY, offer=None) -> OpponentDirective:
    return OpponentDirective(
        kind=kind,
        template_key="opponent.counter",
        offer=offer,
        public_facts=("Публичный факт",),
        reason_codes=(ReasonCode.TURN_PROCESSED,),
    )


def test_prompt_allow_list_and_history_is_bounded() -> None:
    scenario = _scenario()
    messages = [
        Message(role="participant", content=f"реплика {index}", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        for index in range(8)
    ]
    prompt = build_opponent_prompt(scenario.public_briefing, messages, _directive())

    assert "реплика 0" not in prompt
    assert all(f"реплика {index}" in prompt for index in range(2, 8))
    assert '"template_key"' not in prompt
    assert '"reason_codes"' not in prompt
    assert '"counter_offer"' not in prompt
    assert '"roles"' not in prompt
    assert "reservation" not in prompt.casefold()
    assert "batna" not in prompt.casefold()
    assert "hidden_" not in prompt.casefold()
    assert "engine_state" not in prompt
    assert "threshold" not in prompt.casefold()


def test_only_explicit_counter_directive_exposes_offer() -> None:
    scenario = _scenario()
    offer = NegotiationOffer(
        proposer_role_id="supplier",
        values=(IssueValue(issue_id="delivery_days", value=40.0),),
        source_turn=1,
    )
    prompt = build_opponent_prompt(
        scenario.public_briefing,
        [],
        _directive(DirectiveKind.COUNTER, offer),
        issue_guide={"delivery_days": "Срок поставки. Единица измерения: дней."},
    )
    assert '"counter_offer"' in prompt
    assert '"delivery_days"' in prompt
    assert "Единица измерения: дней" in prompt

    # An offer attached to any other kind is not public counter-offer data.
    assert '"counter_offer"' not in build_opponent_prompt(
        scenario.public_briefing, [], _directive(DirectiveKind.CLARIFY, offer)
    )


def test_provider_serialization_is_deterministic_and_safe() -> None:
    scenario = _scenario()
    args = (scenario.public_briefing, [], _directive())
    assert serialize_provider_request(*args) == serialize_provider_request(*args)
    assert "prompt" in serialize_provider_request(*args)


@pytest.mark.parametrize(
    "reply",
    ["", "   ", '{"kind":"accept"}', "```text\nответ\n```", "# ответ", "Как ИИ, я отвечу."],
)
def test_reply_validator_rejects_empty_structured_markdown_meta_and_long_replies(reply: str) -> None:
    with pytest.raises(ValueError):
        validate_opponent_reply(reply)


def test_reply_validator_accepts_plain_text_and_bounds_length() -> None:
    assert validate_opponent_reply("Готов обсудить срок поставки и критерии качества.") == (
        "Готов обсудить срок поставки и критерии качества."
    )
    with pytest.raises(ValueError):
        validate_opponent_reply("А" * 2001)


def test_models_reject_extra_fields_at_input_boundary() -> None:
    with pytest.raises(ValidationError):
        OpponentDirective.model_validate({
            "kind": "clarify",
            "template_key": "opponent.clarify",
            "public_facts": ["ok"],
            "reason_codes": ["turn.processed"],
            "batna": "secret",
        })


@pytest.mark.parametrize(
    ("kind", "reply"),
    [
        (DirectiveKind.ACCEPT, "Согласен. Зафиксируем достигнутые договорённости."),
        (DirectiveKind.COUNTER, "Не готов принять пакет; предлагаю цену 9,75 млн рублей."),
        (DirectiveKind.COUNTER, "Готовы согласовать структуру, но предлагаем срок 40 дней."),
        (DirectiveKind.COUNTER, "По бюджету 6 млн согласны, но команду предлагаем в три человека."),
        (DirectiveKind.CLARIFY, "Какие сроки для вас являются критичными?"),
        (DirectiveKind.IMPASSE, "Мы пришли к тупику и завершаем переговоры без соглашения."),
        (DirectiveKind.WALK_AWAY, "Вынужден завершить переговоры и выйти без соглашения."),
    ],
)
def test_reply_alignment_accepts_matching_directive(kind: DirectiveKind, reply: str) -> None:
    assert validate_directive_alignment(reply, kind) == reply


@pytest.mark.parametrize(
    ("kind", "reply"),
    [
        (DirectiveKind.ACCEPT, "Цена слишком низкая. Если вы согласитесь на 9,75 млн, продолжим."),
        (DirectiveKind.COUNTER, "Согласен, принимаю ваше предложение."),
        (DirectiveKind.COUNTER, "Оба варианта требуют доработки; уточните приоритеты?"),
        (DirectiveKind.CLARIFY, "Я рассмотрел ваше сообщение."),
        (DirectiveKind.IMPASSE, "Давайте обсудим ещё один вариант."),
        (DirectiveKind.WALK_AWAY, "Уточните размер предоплаты?"),
        (DirectiveKind.ACCEPT, "Согласен, условия зафиксированы. Перейдём к следующему вопросу."),
    ],
)
def test_reply_alignment_rejects_contradicting_directive(kind: DirectiveKind, reply: str) -> None:
    with pytest.raises(ValueError):
        validate_directive_alignment(reply, kind)
