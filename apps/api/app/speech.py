"""Natural, ephemeral speech for committed opponent turns."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Protocol
from uuid import uuid4

import httpx


_MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
_MAX_AUDIO_BYTES = 4 * 1024 * 1024

_OPENING_LINES = {
    "equipment-supply": "Добрый день. Наша стартовая позиция — 10,8 млн рублей и поставка за 50 дней. Если вам нужен другой срок или цена, давайте обсудим встречные условия по всему пакету.",
    "project-resources": "Добрый день. На пилот сейчас могу предложить 4 млн рублей и двух специалистов. Чтобы выделить больше, нужно договориться, как не сорвать текущие программы.",
}


def opening_line_for(scenario_id: str, negotiation_type: str | None = None) -> str:
    """Return the fixed public opener; the speech route never accepts arbitrary text."""
    if scenario_id in _OPENING_LINES:
        return _OPENING_LINES[scenario_id]
    if negotiation_type == "internal_resources":
        return "Добрый день. Бюджет и команда у нас ограничены текущими обязательствами. Обсудим, какие условия позволят выделить ресурсы на вашу инициативу."
    return "Добрый день. По стоимости и срокам у нас пока жёсткая стартовая позиция. Давайте посмотрим, где возможен взаимный обмен условиями."


class SpeechUnavailable(RuntimeError):
    """The voice provider cannot produce a usable response right now."""


@dataclass(frozen=True, slots=True)
class SpeechAudio:
    data: bytes
    mime_type: str


class OpponentSpeechService(Protocol):
    async def synthesize(self, text: str, *, tone: str, speaker_id: str | None) -> SpeechAudio: ...


class GeminiSpeechService:
    """Speak only the already committed public opponent text.

    The API key stays on the server. Private turns are streamed without
    persistence; only the fixed public opener may be cached for reuse.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-3.8-flash-lite-tts",
        timeout_seconds: float = 25.0,
        transport: httpx.AsyncBaseTransport | None = None,
        opening_cache_dir: str | None = None,
    ) -> None:
        if not api_key.strip() or not _MODEL_NAME.fullmatch(model) or timeout_seconds <= 0:
            raise ValueError("Invalid Gemini speech configuration")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport
        self._semaphore = asyncio.Semaphore(3)
        self._opening_cache_dir = Path(opening_cache_dir) if opening_cache_dir else None
        self._opening_lock = asyncio.Lock()
        self._quota_pause_until: dict[str, float] = {}

    @classmethod
    def from_env(cls) -> "GeminiSpeechService | None":
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        try:
            return cls(
                key,
                model=os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts").strip(),
                timeout_seconds=float(os.getenv("GEMINI_TTS_TIMEOUT_SECONDS", "25")),
                opening_cache_dir=os.getenv("SPEECH_OPENING_CACHE_DIR") or None,
            )
        except (TypeError, ValueError):
            return None

    async def synthesize(self, text: str, *, tone: str, speaker_id: str | None) -> SpeechAudio:
        if not text.strip() or len(text) > 1500:
            raise SpeechUnavailable("Opponent turn is outside the speech length limit")
        voice = self._voice_for(tone, speaker_id)
        style = {
            "cooperative": "Тёплая, естественная русская речь. Спокойный темп, уважительный деловой тон.",
            "businesslike": "Естественная русская речь, уверенно и по-деловому, с короткими смысловыми паузами.",
            "firm": "Естественная русская речь, твёрдо и сдержанно, без театральности.",
        }.get(tone, "Естественная русская речь, спокойно и по-деловому.")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": text, "speech_metadata": {"style": style}}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"voice": voice}},
            },
        }
        try:
            async with self._semaphore:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._timeout, connect=5.0),
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        f"{_API_BASE_URL}/{self._model}:generateContent",
                        headers={"x-goog-api-key": self._api_key},
                        json=payload,
                    )
        except httpx.HTTPError as error:
            raise SpeechUnavailable("Gemini speech request failed") from error
        if response.status_code != 200:
            raise SpeechUnavailable(f"Gemini speech returned HTTP {response.status_code}")
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            audio_parts = [part["inlineData"] for part in parts if "inlineData" in part]
            if len(audio_parts) != 1:
                raise ValueError("expected exactly one audio part")
            mime_type = audio_parts[0]["mimeType"].split(";", 1)[0].lower()
            if mime_type not in {"audio/wav", "audio/x-wav"}:
                raise ValueError("unsupported audio format")
            data = base64.b64decode(audio_parts[0]["data"], validate=True)
            if not 44 <= len(data) <= _MAX_AUDIO_BYTES or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                raise ValueError("invalid WAV payload")
            return SpeechAudio(data=data, mime_type="audio/wav")
        except (KeyError, IndexError, TypeError, ValueError, binascii.Error) as error:
            raise SpeechUnavailable("Gemini speech response was invalid") from error

    async def stream_synthesize(
        self, text: str, *, tone: str, speaker_id: str | None
    ) -> AsyncIterator[bytes]:
        """Yield exact-text 24 kHz mono PCM as soon as Gemini produces it.

        This path is used by the interruptible call UI. The one-shot WAV path
        remains available for the older voice mode and fallback.
        """
        if not text.strip() or len(text) > 1500:
            raise SpeechUnavailable("Opponent turn is outside the speech length limit")
        model_order = [self._model]
        if self._model == "gemini-3.8-flash-lite-tts":
            model_order.append("gemini-3.8-flash-tts")
        available = [model for model in model_order if self._quota_pause_until.get(model, 0) <= time.monotonic()]
        if not available:
            available = model_order[-1:]
        for index, model in enumerate(available):
            emitted = False
            try:
                async for chunk in self._stream_synthesize_model(model, text, tone=tone, speaker_id=speaker_id):
                    emitted = True
                    yield chunk
                return
            except SpeechUnavailable:
                if emitted or index == len(available) - 1:
                    raise

    async def stream_opening(self, text: str, *, tone: str, speaker_id: str | None) -> AsyncIterator[bytes]:
        """Cache only fixed public opening lines; never cache private dialogue."""
        cache_dir = self._opening_cache_dir
        if cache_dir is None:
            async for chunk in self.stream_synthesize(text, tone=tone, speaker_id=speaker_id):
                yield chunk
            return
        key = hashlib.sha256(f"{self._model}\0{tone}\0{speaker_id}\0{text}".encode()).hexdigest()
        path = cache_dir / f"{key}.pcm"
        async with self._opening_lock:
            try:
                size = path.stat().st_size
                if 0 < size <= _MAX_AUDIO_BYTES and size % 2 == 0:
                    data = path.read_bytes()
                    for offset in range(0, len(data), 16 * 1024):
                        yield data[offset:offset + 16 * 1024]
                    return
            except OSError:
                pass
            audio = bytearray()
            async for chunk in self.stream_synthesize(text, tone=tone, speaker_id=speaker_id):
                audio.extend(chunk)
                yield chunk
            if audio:
                try:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    temporary = cache_dir / f"{key}.{uuid4().hex}.tmp"
                    temporary.write_bytes(audio)
                    temporary.replace(path)
                except OSError:
                    pass

    async def _stream_synthesize_model(
        self, model: str, text: str, *, tone: str, speaker_id: str | None
    ) -> AsyncIterator[bytes]:
        style = {
            "cooperative": "Тёплая, естественная русская речь. Спокойный темп, уважительный деловой тон.",
            "businesslike": "Естественная русская речь, уверенно и по-деловому, с короткими смысловыми паузами.",
            "firm": "Естественная русская речь, твёрдо и сдержанно, без театральности.",
        }.get(tone, "Естественная русская речь, спокойно и по-деловому.")
        payload = {
            "model": model,
            "input": [{
                "type": "user_input",
                "content": [{
                    "type": "text",
                    "text": text,
                    "annotations": [{"type": "speech_metadata", "style": style}],
                }],
            }],
            "response_format": {"type": "audio", "mime_type": "audio/l16", "sample_rate": 24000},
            "generation_config": {"speech_config": [{"voice": self._voice_for(tone, speaker_id)}]},
            "stream": True,
        }
        total_bytes = 0
        try:
            async with self._semaphore:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._timeout, connect=5.0),
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    async with client.stream(
                        "POST",
                        _INTERACTIONS_URL,
                        headers={"x-goog-api-key": self._api_key},
                        json=payload,
                    ) as response:
                        if response.status_code == 429:
                            self._quota_pause_until[model] = time.monotonic() + 900
                        if response.status_code != 200 or "text/event-stream" not in response.headers.get("content-type", ""):
                            raise SpeechUnavailable("Gemini streaming speech request failed")
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            if line[6:].strip() == "[DONE]":
                                break
                            try:
                                event = json.loads(line[6:])
                                if not isinstance(event, dict):
                                    raise ValueError("invalid streaming event")
                                if event.get("event_type") == "error":
                                    error = event.get("error") or {}
                                    if isinstance(error, dict) and error.get("code") == "rate_limit_exceeded":
                                        self._quota_pause_until[model] = time.monotonic() + 900
                                    raise SpeechUnavailable("Gemini streaming speech failed")
                                if event.get("event_type") != "step.delta":
                                    continue
                                delta = event.get("delta") or {}
                                if not isinstance(delta, dict):
                                    raise ValueError("invalid audio delta")
                                if delta.get("type") != "audio":
                                    continue
                                chunk = base64.b64decode(delta["data"], validate=True)
                                if len(chunk) % 2:
                                    raise ValueError("invalid PCM chunk")
                                if not chunk:
                                    continue
                                total_bytes += len(chunk)
                                if total_bytes > _MAX_AUDIO_BYTES:
                                    raise ValueError("streaming audio is too large")
                            except (KeyError, TypeError, ValueError, binascii.Error) as error:
                                raise SpeechUnavailable("Gemini streaming speech response was invalid") from error
                            yield chunk
        except httpx.HTTPError as error:
            raise SpeechUnavailable("Gemini streaming speech request failed") from error
        if total_bytes == 0:
            raise SpeechUnavailable("Gemini streaming speech returned no audio")

    @staticmethod
    def _voice_for(tone: str, speaker_id: str | None) -> str:
        if speaker_id:
            return ("Orus", "Sulafat", "Charon")[sum(speaker_id.encode("utf-8")) % 3]
        return {"cooperative": "Sulafat", "firm": "Kore"}.get(tone, "Orus")
