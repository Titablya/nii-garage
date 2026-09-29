import base64
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import InMemorySessionRepository
from app.voice_repository import InMemoryVoiceRecordingRepository, new_voice_recording


def start_exchange(api: TestClient, text: str = "Предлагаю сначала согласовать критерии и срок поставки.") -> tuple[str, str, str]:
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()["id"]
    response = api.post(f"/api/v1/sessions/{session_id}/messages", json={"content": text})
    assert response.status_code == 200
    payload = response.json()
    return session_id, payload["participant_message"]["id"], payload["opponent_message"]["id"]


def voice_payload(message_id: str, transcript: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "message_id": message_id,
        "audio_base64": base64.b64encode(b"sample-webm-audio").decode(),
        "mime_type": "audio/webm;codecs=opus",
        "duration_ms": 4300,
        "transcript": transcript,
        "retention_policy": "24_hours",
        "consent": True,
        "consent_version": "voice-v1",
        "observations": {
            "pause_count": 2,
            "longest_pause_ms": 940,
            "speaking_rate_wpm": 118,
            "interruption_count": 1,
        },
    }
    payload.update(overrides)
    return payload


def test_voice_recording_is_linked_downloadable_and_deletable_without_losing_message() -> None:
    api = TestClient(create_app(InMemorySessionRepository()))
    transcript = "Предлагаю сначала согласовать критерии и срок поставки."
    session_id, message_id, _ = start_exchange(api, transcript)

    created = api.post(
        f"/api/v1/sessions/{session_id}/voice-recordings",
        json=voice_payload(message_id, transcript),
    )
    assert created.status_code == 201
    recording = created.json()
    assert recording["message_id"] == message_id
    assert recording["transcript"] == transcript
    assert recording["observations"]["pause_count"] == 2
    assert recording["audio_url"].endswith(f"/{recording['id']}/audio")

    listed = api.get(f"/api/v1/sessions/{session_id}/voice-recordings")
    assert [item["id"] for item in listed.json()["recordings"]] == [recording["id"]]

    audio = api.get(recording["audio_url"])
    assert audio.status_code == 200
    assert audio.content == b"sample-webm-audio"
    assert "private" in audio.headers["cache-control"]
    assert "no-store" in audio.headers["cache-control"]

    deleted = api.delete(f"/api/v1/sessions/{session_id}/voice-recordings/{recording['id']}")
    assert deleted.status_code == 204
    assert api.get(recording["audio_url"]).status_code == 404
    session = api.get(f"/api/v1/sessions/{session_id}").json()
    assert any(item["id"] == message_id and item["content"] == transcript for item in session["messages"])


def test_voice_requires_consent_exact_transcript_and_participant_message() -> None:
    api = TestClient(create_app(InMemorySessionRepository()))
    transcript = "Предлагаю сначала согласовать критерии и срок поставки."
    session_id, participant_id, opponent_id = start_exchange(api, transcript)

    no_consent = voice_payload(participant_id, transcript, consent=False)
    assert api.post(f"/api/v1/sessions/{session_id}/voice-recordings", json=no_consent).status_code == 422
    wrong_transcript = voice_payload(participant_id, "Текст был подменён")
    assert api.post(f"/api/v1/sessions/{session_id}/voice-recordings", json=wrong_transcript).status_code == 422
    opponent_audio = voice_payload(opponent_id, transcript)
    assert api.post(f"/api/v1/sessions/{session_id}/voice-recordings", json=opponent_audio).status_code == 422
    assert api.get(f"/api/v1/sessions/{session_id}").status_code == 200


def test_voice_rejects_invalid_audio_and_duplicate_link_without_damaging_session() -> None:
    api = TestClient(create_app(InMemorySessionRepository()))
    transcript = "Предлагаю сначала согласовать критерии и срок поставки."
    session_id, message_id, _ = start_exchange(api, transcript)

    invalid = voice_payload(message_id, transcript, audio_base64="***")
    assert api.post(f"/api/v1/sessions/{session_id}/voice-recordings", json=invalid).status_code == 422
    valid = voice_payload(message_id, transcript)
    assert api.post(f"/api/v1/sessions/{session_id}/voice-recordings", json=valid).status_code == 201
    assert api.post(f"/api/v1/sessions/{session_id}/voice-recordings", json=valid).status_code == 409
    assert len(api.get(f"/api/v1/sessions/{session_id}").json()["messages"]) == 2


def test_expired_voice_recordings_are_purged() -> None:
    repository = InMemoryVoiceRecordingRepository()
    now = datetime.now(timezone.utc)
    record = new_voice_recording(
        session_id=uuid4(), message_id=uuid4(), owner_user_id=None, mime_type="audio/webm",
        audio_data=b"audio", duration_ms=1000, transcript="Тест", pause_count=0,
        longest_pause_ms=0, speaking_rate_wpm=60, interruption_count=0,
        retention_policy="24_hours", consent_version="voice-v1", expires_at=now - timedelta(seconds=1),
    )
    repository.create(record)
    assert repository.purge_expired(now) == 1
    assert repository.get(record.id) is None
