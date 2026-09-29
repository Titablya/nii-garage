import asyncio
import base64
import json
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import InMemorySessionRepository
from app.speech import GeminiSpeechService, SpeechAudio, SpeechUnavailable, opening_line_for


WAV = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + bytes(36)


class FakeSpeech:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def synthesize(self, text: str, *, tone: str, speaker_id: str | None) -> SpeechAudio:
        self.calls.append((text, tone, speaker_id))
        return SpeechAudio(WAV, "audio/wav")

    async def stream_synthesize(self, text: str, *, tone: str, speaker_id: str | None):
        self.calls.append((text, tone, speaker_id))
        yield b"\x01\x00\x02\x00"
        yield b"\x03\x00\x04\x00"


def test_only_committed_opponent_turn_can_be_spoken() -> None:
    fake = FakeSpeech()
    api = TestClient(create_app(InMemorySessionRepository(), speech_service=fake))
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()["id"]
    exchange = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Какие условия поставки для вас наиболее важны?"},
    ).json()
    opponent = exchange["opponent_message"]
    route = f"/api/v1/sessions/{session_id}/opponent-audio"

    assert api.post(route, json={"message_id": exchange["participant_message"]["id"]}).status_code == 404
    assert api.post(route, json={"message_id": str(uuid4())}).status_code == 404
    assert api.post(route, json={"message_id": opponent["id"], "text": "Подменённый ответ"}).status_code == 422
    response = api.post(route, json={"message_id": opponent["id"]})
    assert response.status_code == 200
    assert response.content == WAV
    assert response.headers["content-type"] == "audio/wav"
    assert "no-store" in response.headers["cache-control"]
    assert fake.calls == [(opponent["content"], "businesslike", opponent["speaker_id"])]


def test_natural_speech_unavailable_keeps_negotiation_intact() -> None:
    api = TestClient(create_app(InMemorySessionRepository()))
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()["id"]
    exchange = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Давайте обсудим объективные критерии."},
    ).json()
    response = api.post(
        f"/api/v1/sessions/{session_id}/opponent-audio",
        json={"message_id": exchange["opponent_message"]["id"]},
    )
    assert response.status_code == 503
    assert len(api.get(f"/api/v1/sessions/{session_id}").json()["messages"]) == 2


def test_streaming_speech_uses_only_committed_opponent_text() -> None:
    fake = FakeSpeech()
    api = TestClient(create_app(InMemorySessionRepository(), speech_service=fake))
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()["id"]
    exchange = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Какие условия поставки для вас важны?"},
    ).json()
    route = f"/api/v1/sessions/{session_id}/opponent-audio-stream"
    assert api.post(route, json={"message_id": exchange["participant_message"]["id"]}).status_code == 404
    assert api.post(route, json={"message_id": str(uuid4())}).status_code == 404
    assert api.post(route, json={"message_id": exchange["opponent_message"]["id"], "text": "Подмена"}).status_code == 422
    response = api.post(route, json={"message_id": exchange["opponent_message"]["id"]})
    assert response.status_code == 200
    assert response.headers["content-type"].lower().startswith("audio/l16")
    assert response.headers["x-audio-sample-rate"] == "24000"
    assert "no-store" in response.headers["cache-control"]
    assert response.content == b"\x01\x00\x02\x00\x03\x00\x04\x00"
    assert fake.calls == [(exchange["opponent_message"]["content"], "businesslike", exchange["opponent_message"]["speaker_id"])]


def test_opening_uses_same_natural_voice_without_accepting_client_text() -> None:
    fake = FakeSpeech()
    api = TestClient(create_app(InMemorySessionRepository(), speech_service=fake))
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()["id"]
    route = f"/api/v1/sessions/{session_id}/opening-audio-stream"
    response = api.post(route, json={"text": "Произвольный текст клиента"})
    assert response.status_code == 200
    assert response.content == b"\x01\x00\x02\x00\x03\x00\x04\x00"
    assert response.headers["content-type"].lower().startswith("audio/l16")
    assert fake.calls == [(opening_line_for("equipment-supply"), "businesslike", "opponent_1")]
    assert api.get(f"/api/v1/sessions/{session_id}").json()["messages"] == []


def test_openings_name_real_initial_disagreements() -> None:
    assert "10,8 млн" in opening_line_for("equipment-supply")
    assert "50 дней" in opening_line_for("equipment-supply")
    assert "4 млн" in opening_line_for("project-resources")
    assert "двух специалистов" in opening_line_for("project-resources")
    assert "Бюджет и команда" in opening_line_for("random-internal", "internal_resources")


def test_gemini_speech_uses_verbatim_committed_text_and_rejects_invalid_audio() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(WAV).decode()}}]}}]})

    service = GeminiSpeechService("test-key", transport=httpx.MockTransport(handler))
    result = asyncio.run(service.synthesize("Давайте обсудим срок.", tone="firm", speaker_id=None))
    assert result.data == WAV
    assert seen[0]["contents"][0]["parts"][0]["text"] == "Давайте обсудим срок."
    assert seen[0]["generationConfig"]["speechConfig"]["voiceConfig"]["voice"] == "Kore"

    def invalid(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "wrong"}]}}]})

    broken = GeminiSpeechService("test-key", transport=httpx.MockTransport(invalid))
    try:
        asyncio.run(broken.synthesize("Тест", tone="businesslike", speaker_id=None))
    except SpeechUnavailable:
        pass
    else:
        raise AssertionError("Invalid provider audio must not be returned to the browser")


def test_gemini_streaming_speech_parses_pcm_events() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        events = [
            {"event_type": "interaction.created"},
            {"event_type": "step.delta", "delta": {"type": "audio", "data": base64.b64encode(b"\x01\x00\x02\x00").decode()}},
            {"event_type": "step.delta", "delta": {"type": "audio", "data": base64.b64encode(b"\x03\x00").decode()}},
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def collect(service: GeminiSpeechService) -> bytes:
        return b"".join([part async for part in service.stream_synthesize("Обсудим срок.", tone="firm", speaker_id=None)])

    service = GeminiSpeechService("test-key", transport=httpx.MockTransport(handler))
    assert asyncio.run(collect(service)) == b"\x01\x00\x02\x00\x03\x00"
    assert seen[0]["input"][0]["content"][0]["text"] == "Обсудим срок."
    assert seen[0]["generation_config"]["speech_config"][0]["voice"] == "Kore"
    assert seen[0]["stream"] is True


def test_streaming_speech_falls_back_after_quota_and_accepts_done_marker() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "gemini-3.8-flash-lite-tts":
            events = [{'event_type': 'error', 'error': {'code': 'rate_limit_exceeded'}}]
        else:
            events = [{'event_type': 'step.delta', 'delta': {'type': 'audio', 'data': base64.b64encode(b'\x01\x00\x02\x00').decode()}}]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in service.stream_synthesize("Тест", tone="businesslike", speaker_id="opponent_1")])

    service = GeminiSpeechService("test-key", transport=httpx.MockTransport(handler))
    assert asyncio.run(collect()) == b"\x01\x00\x02\x00"
    assert seen == ["gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts"]


def test_public_opening_is_cached_without_caching_dialogue(tmp_path) -> None:
    seen = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        event = {'event_type': 'step.delta', 'delta': {'type': 'audio', 'data': base64.b64encode(b'\x01\x00\x02\x00').decode()}}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    service = GeminiSpeechService("test-key", transport=httpx.MockTransport(handler), opening_cache_dir=str(tmp_path))

    async def collect_twice() -> tuple[bytes, bytes]:
        first = b"".join([part async for part in service.stream_opening("Добрый день.", tone="businesslike", speaker_id="opponent_1")])
        second = b"".join([part async for part in service.stream_opening("Добрый день.", tone="businesslike", speaker_id="opponent_1")])
        return first, second

    assert asyncio.run(collect_twice()) == (b"\x01\x00\x02\x00", b"\x01\x00\x02\x00")
    assert seen == 1


def test_gemini_streaming_speech_rejects_empty_or_malformed_audio() -> None:
    async def collect(service: GeminiSpeechService) -> bytes:
        return b"".join([part async for part in service.stream_synthesize("Тест", tone="businesslike", speaker_id=None)])

    for body in (
        'data: {"event_type":"interaction.created"}\n\n',
        'data: {"event_type":"step.delta","delta":{"type":"audio","data":"AQ=="}}\n\n',
    ):
        service = GeminiSpeechService(
            "test-key",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})),
        )
        try:
            asyncio.run(collect(service))
        except SpeechUnavailable:
            pass
        else:
            raise AssertionError("Malformed streaming audio must not be returned")
