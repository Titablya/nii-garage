"""Application service that keeps the LLM behind the deterministic engine."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Sequence

import httpx

from ..domain.scenario import ScenarioDefinition
from ..domain.scenario import PublicBriefing
from ..engine import DirectiveKind, OpponentDirective, extract_issue_values
from ..models import GenerationMetadata, Message
from .contracts import GenerationRequest, LLMProvider, LLMProviderError, LLMResponseError
from .prompting import build_opponent_prompt, validate_directive_alignment
from ..observability import log_event


logger = logging.getLogger("negotiation_arena.llm")


@dataclass(frozen=True, slots=True)
class OpponentGeneration:
    content: str
    metadata: GenerationMetadata


class OpponentGenerator:
    """Verbalize an engine directive or return the supplied safe fallback."""

    def __init__(self, provider: LLMProvider | None, *, model: str | None = None) -> None:
        self._provider = provider
        self._model = model

    async def generate(
        self,
        *,
        briefing: PublicBriefing,
        opponent_role: str,
        issue_guide: Mapping[str, str],
        messages: Sequence[Message],
        directive: OpponentDirective,
        fallback: str,
        tone: str = "businesslike",
        difficulty: str = "medium",
        participant_role: str | None = None,
        strategy: str = "analytical",
        interaction_mode: str = "meeting",
        phase: str = "opening",
        active_event: str | None = None,
        scenario: ScenarioDefinition | None = None,
    ) -> OpponentGeneration:
        if self._provider is None:
            return self._fallback(fallback, "not_configured")

        prompt = build_opponent_prompt(
            briefing,
            messages,
            directive,
            opponent_role,
            issue_guide,
            tone,
            difficulty,
            participant_role,
            strategy,
            interaction_mode,
            phase,
            active_event,
        )
        try:
            response = await self._provider.generate(GenerationRequest(prompt=prompt, max_output_tokens=500))
            reply = validate_directive_alignment(response.reply, directive.kind)
            if directive.kind is DirectiveKind.COUNTER and directive.offer is not None and scenario is not None:
                spoken = {
                    item.issue_id: item.value
                    for item in extract_issue_values(scenario, reply, prefer_last=True)
                }
                expected = {item.issue_id: item.value for item in directive.offer.values}
                if spoken.keys() != expected.keys() or any(
                    abs(spoken[issue_id] - value) > 1e-6
                    for issue_id, value in expected.items()
                ):
                    raise ValueError("Озвученные условия не совпадают с директивой движка")
        except (LLMResponseError, ValueError):
            log_event(
                logger,
                "llm.fallback",
                level=logging.WARNING,
                component="opponent",
                reason="invalid_response",
            )
            return self._fallback(fallback, "invalid_response")
        except LLMProviderError as error:
            cause = error.__cause__
            reason = "timeout" if isinstance(cause, httpx.TimeoutException) else "provider_error"
            log_event(
                logger,
                "llm.fallback",
                level=logging.WARNING,
                component="opponent",
                reason=reason,
            )
            return self._fallback(fallback, reason)

        return OpponentGeneration(
            content=reply,
            metadata=GenerationMetadata(
                provider="gemini",
                model=self._model,
                fallback=False,
                reason=None,
            ),
        )

    def _fallback(self, content: str, reason: str) -> OpponentGeneration:
        return OpponentGeneration(
            content=content,
            metadata=GenerationMetadata(
                provider="deterministic",
                model=self._model,
                fallback=True,
                reason=reason,
            ),
        )


__all__ = ["OpponentGeneration", "OpponentGenerator"]
