"""LLM provider contracts and transport implementations."""

from .contracts import (
    GenerationRequest,
    GenerationResponse,
    LLMConfigurationError,
    LLMProvider,
    LLMProviderError,
    LLMResponseError,
    LLMTransportError,
)
from .gemini import GeminiProvider, GeminiSettings
from .coach import ReportCoach
from .opponent import OpponentGeneration, OpponentGenerator

__all__ = [
    "GenerationRequest",
    "GenerationResponse",
    "GeminiProvider",
    "GeminiSettings",
    "LLMConfigurationError",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponseError",
    "LLMTransportError",
    "OpponentGeneration",
    "OpponentGenerator",
    "ReportCoach",
]
