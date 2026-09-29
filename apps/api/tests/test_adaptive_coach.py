from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.llm import GenerationResponse, LLMProvider
from app.main import create_app
from app.repository import InMemorySessionRepository


class CoachProvider(LLMProvider):
    def __init__(self, *, leak: bool = False) -> None:
        self.requests = []
        self.leak = leak

    async def generate(self, request):
        self.requests.append(request)
        schema = request.response_json_schema or {}
        properties = schema.get("properties", {})
        if "question" in properties:
            question = (
                "Как использовать скрытую ZOPA и BATNA оппонента?"
                if self.leak
                else "Какой интерес собеседника вы ещё не проверили открытым вопросом?"
            )
            return GenerationResponse(reply=json.dumps({"question": question}, ensure_ascii=False))
        if "possible_reply" in properties:
            return GenerationResponse(
                reply=json.dumps(
                    {
                        "possible_reply": "Это можно обсуждать. Какой взаимный пакет вы предлагаете?",
                        "analysis": "Вопрос создаёт пространство для уточнения интересов.",
                    },
                    ensure_ascii=False,
                )
            )
        return GenerationResponse(reply="Уточните ваши приоритеты и предложите взаимный пакет условий.")


def _register(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Тренер", "password": "Strong-pass-42"},
    )
    assert response.status_code == 201
    return response.json()["csrf_token"]


def _session(client: TestClient, csrf: str) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"scenario_id": "equipment-supply"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _worksheet() -> dict:
    return {
        "focus_skill": "questions",
        "goal": "Согласовать полный взаимовыгодный пакет поставки.",
        "interests": ["Надёжность запуска", "Управляемый риск"],
        "participant_batna": "Перенести закупку и запросить предложения у других поставщиков.",
        "participant_reservation": "Не принимать пакет, который нельзя исполнить без критического риска.",
        "planned_questions": ["Какие условия для вас важнее всего и почему?"],
    }


def test_private_prebrief_is_owned_and_never_leaks_into_session_response() -> None:
    app = create_app(InMemorySessionRepository())
    owner = TestClient(app)
    outsider = TestClient(app)
    with owner, outsider:
        csrf = _register(owner, "coach-owner@example.test")
        _register(outsider, "coach-outsider@example.test")
        session_id = _session(owner, csrf)

        seeded = owner.get(f"/api/v1/sessions/{session_id}/coach/prebrief")
        assert seeded.status_code == 200
        assert seeded.json()["saved"] is False

        saved = owner.post(
            f"/api/v1/sessions/{session_id}/coach/prebrief",
            json=_worksheet(),
            headers={"X-CSRF-Token": csrf},
        )
        assert saved.status_code == 200
        assert saved.json()["saved"] is True
        assert saved.json()["participant_batna"].startswith("Перенести закупку")
        assert outsider.get(f"/api/v1/sessions/{session_id}/coach/prebrief").status_code == 404

        public_session = json.dumps(owner.get(f"/api/v1/sessions/{session_id}").json(), ensure_ascii=False)
        assert "Перенести закупку" not in public_session
        assert "participant_reservation" not in public_session


def test_socratic_hint_is_opt_in_cached_budgeted_and_public_only() -> None:
    provider = CoachProvider()
    repository = InMemorySessionRepository()
    app = create_app(repository, llm_provider=provider, llm_model="test-coach")
    with TestClient(app) as client:
        csrf = _register(client, "coach-hint@example.test")
        session_id = _session(client, csrf)
        client.post(
            f"/api/v1/sessions/{session_id}/coach/prebrief",
            json=_worksheet(),
            headers={"X-CSRF-Token": csrf},
        )
        assert provider.requests == []
        before = repository.get(__import__("uuid").UUID(session_id)).model_dump(mode="json")

        first = client.post(
            f"/api/v1/sessions/{session_id}/coach/hint",
            json={"draft": "Хочу уточнить ваши приоритеты", "mode": "socratic"},
            headers={"X-CSRF-Token": csrf},
        )
        second = client.post(
            f"/api/v1/sessions/{session_id}/coach/hint",
            json={"draft": "Хочу уточнить ваши приоритеты", "mode": "socratic"},
            headers={"X-CSRF-Token": csrf},
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["mode"] == "socratic"
        assert first.json()["question"].endswith("?")
        assert first.json()["official_outcome_unchanged"] is True
        assert second.json()["cached"] is True
        assert len(provider.requests) == 1
        prompt = provider.requests[0].prompt.casefold()
        for forbidden in ("party_ranges", "hidden_interests", "engine_state", "opponent_batna"):
            assert forbidden not in prompt
        after = repository.get(__import__("uuid").UUID(session_id)).model_dump(mode="json")
        assert after == before


def test_hidden_economics_or_role_misalignment_falls_back_deterministically() -> None:
    provider = CoachProvider(leak=True)
    app = create_app(InMemorySessionRepository(), llm_provider=provider)
    with TestClient(app) as client:
        csrf = _register(client, "coach-safe@example.test")
        session_id = _session(client, csrf)
        response = client.post(
            f"/api/v1/sessions/{session_id}/coach/hint",
            json={"draft": "", "skill_id": "batna", "mode": "socratic"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "deterministic"
        assert response.json()["fallback"] is True
        serialized = json.dumps(response.json(), ensure_ascii=False).casefold()
        assert "zopa" not in serialized
        assert "batna оппонента" not in serialized


def test_rewrite_is_an_unofficial_branch_and_never_mutates_transcript() -> None:
    repository = InMemorySessionRepository()
    app = create_app(repository)
    with TestClient(app) as client:
        csrf = _register(client, "coach-rewrite@example.test")
        session_id = _session(client, csrf)
        exchange = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "Нам нужен лучший срок."},
            headers={"X-CSRF-Token": csrf},
        )
        assert exchange.status_code == 200
        message_id = exchange.json()["participant_message"]["id"]
        before = client.get(f"/api/v1/sessions/{session_id}").json()

        response = client.post(
            f"/api/v1/sessions/{session_id}/coach/rewrite",
            json={
                "message_id": message_id,
                "revised_text": "Правильно ли я понимаю, что для вас критичен срок? Если ускоряем поставку, то обсудим встречное условие по оплате.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["official_transcript_changed"] is False
        assert payload["official_outcome_unchanged"] is True
        assert any(item["effect"] == "improved" for item in payload["impacts"])
        after = client.get(f"/api/v1/sessions/{session_id}").json()
        assert after["messages"] == before["messages"]
        assert after["turn"] == before["turn"]


def test_real_error_drill_and_summary_are_tied_to_the_completed_attempt() -> None:
    app = create_app(InMemorySessionRepository())
    with TestClient(app) as client:
        csrf = _register(client, "coach-drill@example.test")
        session_id = _session(client, csrf)
        worksheet = _worksheet()
        worksheet["focus_skill"] = "active_listening"
        assert client.post(
            f"/api/v1/sessions/{session_id}/coach/prebrief",
            json=worksheet,
            headers={"X-CSRF-Token": csrf},
        ).status_code == 200
        client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "Предлагаю обсудить условия."},
            headers={"X-CSRF-Token": csrf},
        )
        assert client.post(
            f"/api/v1/sessions/{session_id}/complete",
            headers={"X-CSRF-Token": csrf},
        ).status_code == 200

        drill = client.get(f"/api/v1/sessions/{session_id}/coach/drill")
        assert drill.status_code == 200
        assert drill.json()["skill_id"] == "active_listening"
        assert drill.json()["official_outcome_unchanged"] is True
        feedback = client.post(
            f"/api/v1/sessions/{session_id}/coach/drill/complete",
            json={"answer": "Правильно ли я понимаю, что для вас критично снизить риск? Тогда уточню, какие условия помогут это обеспечить?"},
            headers={"X-CSRF-Token": csrf},
        )
        assert feedback.status_code == 200
        assert feedback.json()["score"] >= 67
        summary = client.get(f"/api/v1/sessions/{session_id}/coach/summary")
        assert summary.status_code == 200
        assert summary.json()["focus_skill"] == "active_listening"
        assert summary.json()["drill_completed"] is True
        assert summary.json()["current_skill_score"] is not None
