"""Safe, provider-agnostic contracts for LLM text generation.

This boundary deliberately carries only an already-sanitized prompt.  Scenario
secrets and other hidden facts must never cross it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping


MAX_PROMPT_CHARS = 80_000


class LLMProviderError(RuntimeError):
    """Base exception for errors that are safe to expose to application code."""


class LLMConfigurationError(LLMProviderError):
    """The provider cannot be used because its local configuration is invalid."""


class LLMTransportError(LLMProviderError):
    """The provider could not obtain a successful response from its API."""


class LLMResponseError(LLMProviderError):
    """The provider returned a response outside the agreed output contract."""


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """An already-safe prompt for a single opponent response.

    Callers are responsible for constructing this prompt from public data only.
    """

    prompt: str
    response_json_schema: Mapping[str, Any] | None = None
    max_output_tokens: int = 2048

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if len(self.prompt) > MAX_PROMPT_CHARS:
            raise ValueError("prompt exceeds the safe provider boundary")
        if self.response_json_schema is not None and not isinstance(
            self.response_json_schema, Mapping
        ):
            raise ValueError("response_json_schema must be a mapping")
        if not 32 <= self.max_output_tokens <= 2048:
            raise ValueError("max_output_tokens must be between 32 and 2048")


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    """Structured response returned by an LLM provider."""

    reply: str

    def __post_init__(self) -> None:
        if not isinstance(self.reply, str) or not self.reply.strip():
            raise ValueError("reply must be a non-empty string")


class LLMProvider(ABC):
    """Async transport contract used by application services."""

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Generate one structured response or raise an ``LLMProviderError``."""


__all__ = [
    "GenerationRequest",
    "GenerationResponse",
    "LLMConfigurationError",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponseError",
    "LLMTransportError",
    "MAX_PROMPT_CHARS",
]
