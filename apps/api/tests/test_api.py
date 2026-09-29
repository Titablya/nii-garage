import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.llm import GenerationRequest, GenerationResponse, LLMProvider, LLMTransportError
from app.repository import InMemorySessionRepository
from app.scenario_catalog import DEFAULT_SCENARIOS_PATH, ScenarioConfigurationError, load_scenario_catalog
from app.engine import DirectiveKind, IssueValue, OpponentDirective, ReasonCode, make_offer
from app.services import mock_opponent_reply


def client() -> TestClient:
    return TestClient(create_app(InMemorySessionRepository()))


class RecordingProvider(LLMProvider):
    def __init__(self, reply: str = "Готов обсудить условия. Какие параметры для вас приоритетны?") -> None:
        self.reply = reply
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return GenerationResponse(reply=self.reply)


class FailingProvider(LLMProvider):
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise LLMTransportError("provider unavailable")


class SequenceProvider(LLMProvider):
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return GenerationResponse(reply=self.replies[len(self.requests) - 1])


def test_counter_fallback_uses_natural_numeric_units() -> None:
    directive = OpponentDirective(
        kind=DirectiveKind.COUNTER,
        template_key="opponent.counter",
        offer=make_offer(
            "division_director",
            (
                IssueValue(issue_id="budget", value=6.0),
                IssueValue(issue_id="reporting_hours", value=4.0),
                IssueValue(issue_id="specialists", value=3.0),
            ),
            4,
        ),
        reason_codes=(ReasonCode.COUNTER_OFFER_CREATED,),
    )
    reply = mock_opponent_reply(directive, {
        "budget": ("Бюджет проекта", "миллионов рублей"),
        "specialists": ("Команда", "человек"),
        "reporting_hours": ("Отчётность", "часов в неделю"),
    })
    assert "6 млн рублей" in reply
    assert "4 часа в неделю" in reply
    assert "3 человека" in reply
    assert reply.index("Бюджет проекта") < reply.index("Команда") < reply.index("Отчётность")


def test_gemini_counter_with_changed_terms_falls_back_to_engine_offer() -> None:
    provider = RecordingProvider(
        "Наш пакет: бюджет 6 млн рублей, 2 специалиста, старт через 25 дней "
        "и отчётность 4 часа в неделю."
    )
    api = TestClient(create_app(InMemorySessionRepository(), llm_provider=provider))
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "project-resources"}).json()["id"]
    result = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Предлагаю бюджет 6 млн рублей."},
    ).json()
    assert result["generation"]["fallback"] is True
    assert result["generation"]["reason"] == "invalid_response"
    assert "Бюджет проекта — 4 млн рублей" in result["opponent_message"]["content"]


def test_gemini_counter_with_exact_terms_remains_natural() -> None:
    reply = (
        "Наш пакет: бюджет 4 млн рублей, 2 специалиста, старт через 25 дней "
        "и отчётность 4 часа в неделю."
    )
    api = TestClient(create_app(InMemorySessionRepository(), llm_provider=RecordingProvider(reply)))
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "project-resources"}).json()["id"]
    result = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Предлагаю бюджет 6 млн рублей."},
    ).json()
    assert result["generation"]["fallback"] is False
    assert result["opponent_message"]["content"] == reply


def test_health_and_scenarios() -> None:
    response = client().get("/health", headers={"X-Request-ID": "test-request"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}
    assert response.headers["X-Request-ID"] == "test-request"

    readiness = client().get("/health/ready")
    assert readiness.status_code == 200
    assert readiness.json()["checks"] == {"api": "ok", "database": "ok"}

    scenarios = client().get("/api/v1/scenarios")
    assert scenarios.status_code == 200
    scenario = scenarios.json()[0]
    assert scenario["id"] == "equipment-supply"
    assert scenario["version"]
    assert scenario["language"] == "ru-RU"
    assert scenario["methods"]
    tasks = {item["id"]: item["title"] for item in scenario["tasks"]}
    assert "10 млн рублей" in tasks["issue.price"]
    assert "8,5 млн" not in json.dumps(scenario, ensure_ascii=False)
    assert "hidden_interests" not in scenario
    assert "batna" not in scenario


def test_both_public_briefings_match_engine_boundaries() -> None:
    scenarios = {
        item["id"]: item for item in client().get("/api/v1/scenarios").json()
    }
    equipment = {item["id"]: item["title"] for item in scenarios["equipment-supply"]["tasks"]}
    resources = {item["id"]: item["title"] for item in scenarios["project-resources"]["tasks"]}

    assert equipment["issue.price"] == "Цена контракта: не более 10 млн рублей"
    assert equipment["issue.delivery_days"] == "Срок поставки: не более 45 дней"
    assert resources["issue.budget"] == "Бюджет проекта: не менее 5,5 млн рублей"
    assert resources["issue.specialists"] == "Выделенные специалисты: не менее 3 человек"
    assert resources["issue.start_days"] == "Срок начала: не более 30 дней"


def test_random_scenario_is_safe_varied_and_can_start_a_session() -> None:
    api = client()
    standard_ids = {item["id"] for item in api.get("/api/v1/scenarios").json()}
    assert standard_ids == {"equipment-supply", "project-resources"}

    first = api.get("/api/v1/scenarios/random")
    assert first.status_code == 200
    scenario = first.json()
    assert scenario["id"].startswith("random-")
    assert scenario["id"] not in standard_ids
    assert scenario["tasks"]
    serialized = json.dumps(scenario, ensure_ascii=False)
    assert "hidden_interests" not in serialized
    assert "batna" not in serialized.casefold()
    assert "zopa" not in serialized.casefold()

    second = api.get(
        "/api/v1/scenarios/random", params={"exclude_id": scenario["id"]}
    )
    assert second.status_code == 200
    assert second.json()["id"] != scenario["id"]

    direct = api.get(f"/api/v1/scenarios/{scenario['id']}")
    assert direct.status_code == 200
    assert direct.json() == scenario

    created = api.post("/api/v1/sessions", json={"scenario_id": scenario["id"]})
    assert created.status_code == 201
    assert created.json()["scenario_id"] == scenario["id"]


def test_full_mock_negotiation_flow() -> None:
    api = client()
    created = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"})
    assert created.status_code == 201
    session_id = created.json()["id"]
    assert created.json()["status"] == "active"

    before_complete = api.get(f"/api/v1/sessions/{session_id}/report")
    assert before_complete.status_code == 409

    exchange = api.post(f"/api/v1/sessions/{session_id}/messages", json={"content": "Нам важен срок поставки."})
    assert exchange.status_code == 200
    assert exchange.json()["participant_message"]["role"] == "participant"
    assert exchange.json()["opponent_message"]["role"] == "opponent"
    assert len(exchange.json()["session"]["messages"]) == 2
    assert exchange.json()["generation"] == {
        "provider": "deterministic",
        "model": None,
        "fallback": True,
        "reason": "not_configured",
    }

    completed = api.post(f"/api/v1/sessions/{session_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    report = api.get(f"/api/v1/sessions/{session_id}/report")
    assert report.status_code == 200
    payload = report.json()
    assert payload["session_id"] == session_id
    assert payload["evaluator_version"] == "1.2"
    assert [block["id"] for block in payload["blocks"]] == [
        "preparation", "process", "value", "result", "relationship"
    ]
    raw_score = sum(block["score"] for block in payload["blocks"])
    penalties = sum(item["points"] * item["occurrences"] for item in payload["penalties"])
    assert payload["methodology"]["raw_score"] == raw_score
    assert payload["methodology"]["penalty_points"] == penalties
    assert payload["score"] == max(0, min(100, raw_score + penalties))
    assert len(payload["improvements"]) <= 3
    assert payload["task_checks"]
    assert payload["coaching"]["provider"] == "deterministic"
    assert payload["coaching"]["fallback"] is True

    after_complete = api.post(f"/api/v1/sessions/{session_id}/messages", json={"content": "Ещё одна реплика"})
    assert after_complete.status_code == 409


def test_unknown_resources_return_not_found() -> None:
    api = client()
    assert api.get("/api/v1/scenarios/missing").status_code == 404
    assert api.post("/api/v1/sessions", json={"scenario_id": "missing"}).status_code == 404


def test_blank_message_is_rejected() -> None:
    api = client()
    created = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"})
    session_id = created.json()["id"]

    response = api.post(f"/api/v1/sessions/{session_id}/messages", json={"content": "   "})

    assert response.status_code == 422


def test_configured_llm_verbalizes_directive_and_reports_source() -> None:
    provider = RecordingProvider()
    api = TestClient(
        create_app(
            InMemorySessionRepository(),
            llm_provider=provider,
            llm_model="gemini-3.5-flash-lite",
        )
    )
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()["id"]

    response = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Какие условия для вас наиболее важны?"},
    )

    assert response.status_code == 200
    assert response.json()["opponent_message"]["content"] == provider.reply
    assert response.json()["generation"] == {
        "provider": "gemini",
        "model": "gemini-3.5-flash-lite",
        "fallback": False,
        "reason": None,
    }
    assert len(provider.requests) == 1
    rendered_prompt = provider.requests[0].prompt.casefold()
    assert "какие условия" in rendered_prompt
    assert "10,8 млн рублей" in rendered_prompt
    assert "поставка за 50 дней" in rendered_prompt
    assert not any(secret in rendered_prompt for secret in ("batna", "reservation", "hidden_", "engine_state"))


def test_provider_failure_keeps_engine_flow_available() -> None:
    api = TestClient(
        create_app(
            InMemorySessionRepository(),
            llm_provider=FailingProvider(),
            llm_model="gemini-3.5-flash-lite",
        )
    )
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "project-resources"}).json()["id"]

    response = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Давайте сначала уточним приоритеты сторон."},
    )

    assert response.status_code == 200
    assert response.json()["opponent_message"]["content"]
    assert response.json()["generation"] == {
        "provider": "deterministic",
        "model": "gemini-3.5-flash-lite",
        "fallback": True,
        "reason": "provider_error",
    }


def test_report_uses_gemini_coaching_once_and_caches_verified_result() -> None:
    participant_text = "Какие ограничения для вас критичны?"
    provider = SequenceProvider([
        "Какие сроки и параметры оплаты для вас наиболее важны?",
        json.dumps({
            "summary": "Нужно связать вопрос с последующим пакетным предложением.",
            "points": [{
                "turn": 1,
                "quote": participant_text,
                "problem": "Вопрос пока не переведён в измеримый обмен.",
                "better_approach": "После ответа предложить несколько связанных условий.",
                "suggested_text": "Если срок для вас критичен, давайте свяжем его с оплатой и гарантией.",
            }],
        }, ensure_ascii=False),
    ])
    api = TestClient(create_app(
        InMemorySessionRepository(), llm_provider=provider, llm_model="test-gemini"
    ))
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()["id"]
    assert api.post(
        f"/api/v1/sessions/{session_id}/messages", json={"content": participant_text}
    ).status_code == 200
    assert api.post(f"/api/v1/sessions/{session_id}/complete").status_code == 200
    assert len(provider.requests) == 2

    first = api.get(f"/api/v1/sessions/{session_id}/report")
    second = api.get(f"/api/v1/sessions/{session_id}/report")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["coaching"]["provider"] == "gemini"
    assert first.json()["coaching"]["points"][0]["quote"] == participant_text
    assert len(provider.requests) == 2


def test_engine_flow_is_deterministic_and_public_for_both_scenarios() -> None:
    sequence = [
        "Какие ограничения для вас критичны?",
        "Предлагаю обсудить вариант по плану ресурсов и объективным критериям.",
    ]
    public_keys = {"status", "outcome", "turn", "trust", "tension", "progress", "relationship", "explanation"}
    forbidden = ("batna", "hidden", "reservation", "concession_budget", "interest_id")

    for scenario_id in ("equipment-supply", "project-resources"):
        first, second = client(), client()
        first_id = first.post("/api/v1/sessions", json={"scenario_id": scenario_id}).json()["id"]
        second_id = second.post("/api/v1/sessions", json={"scenario_id": scenario_id}).json()["id"]
        states = []
        for text in sequence:
            left = first.post(f"/api/v1/sessions/{first_id}/messages", json={"content": text})
            right = second.post(f"/api/v1/sessions/{second_id}/messages", json={"content": text})
            assert left.status_code == right.status_code == 200
            left_state, right_state = left.json()["session"], right.json()["session"]
            assert {key: left_state[key] for key in public_keys} == {key: right_state[key] for key in public_keys}
            states.append(left_state)
        rendered = json.dumps(states, ensure_ascii=False).casefold()
        assert not any(token in rendered for token in forbidden)


def test_terminal_engine_outcome_blocks_messages_and_complete_is_idempotent() -> None:
    api = client()
    session_id = api.post("/api/v1/sessions", json={"scenario_id": "project-resources"}).json()["id"]
    terminal = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Я выхожу из переговоров: сделки не будет."},
    )
    assert terminal.status_code == 200
    assert terminal.json()["session"]["status"] == "completed"
    assert terminal.json()["session"]["outcome"] == "walk_away"
    assert api.post(f"/api/v1/sessions/{session_id}/messages", json={"content": "Продолжим"}).status_code == 409
    first_complete = api.post(f"/api/v1/sessions/{session_id}/complete")
    second_complete = api.post(f"/api/v1/sessions/{session_id}/complete")
    assert first_complete.status_code == second_complete.status_code == 200
    assert first_complete.json() == second_complete.json()


def test_catalog_loads_only_published_scenarios_and_never_projects_hidden_data(tmp_path: Path) -> None:
    published_source = next(DEFAULT_SCENARIOS_PATH.glob("*.json"))
    published = json.loads(published_source.read_text(encoding="utf-8"))
    draft = json.loads(json.dumps(published))
    draft["metadata"].update({"id": "draft-scenario", "version_id": "draft-scenario:v1", "status": "draft", "published_at": None})
    (tmp_path / "published.json").write_text(json.dumps(published), encoding="utf-8")
    (tmp_path / "draft.json").write_text(json.dumps(draft), encoding="utf-8")

    catalog = load_scenario_catalog(tmp_path)

    assert len(catalog.list()) == 1
    response = catalog.list()[0].model_dump()
    assert response["version"]
    assert response["configurable"] is True
    assert 6 <= response["max_turns"] <= 20
    assert "hidden_interests" not in response
    assert "batna" not in response
    assert catalog.get("missing") is None


def test_new_published_scenario_is_discovered_without_engine_changes(tmp_path: Path) -> None:
    source = next(DEFAULT_SCENARIOS_PATH.glob("*.json"))
    original = json.loads(source.read_text(encoding="utf-8"))
    added = json.loads(json.dumps(original))
    added["metadata"].update({"id": "new-training-case", "version_id": "new-training-case:v1"})
    added["public_briefing"]["title"] = "Новый учебный кейс"
    (tmp_path / "original.json").write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "new-training-case.v1.json").write_text(json.dumps(added, ensure_ascii=False), encoding="utf-8")

    catalog = load_scenario_catalog(tmp_path)

    assert {scenario.id for scenario in catalog.list()} == {original["metadata"]["id"], "new-training-case"}
    assert catalog.get("new-training-case").title == "Новый учебный кейс"  # type: ignore[union-attr]


def test_catalog_rejects_missing_or_invalid_configuration(tmp_path: Path) -> None:
    with pytest.raises(ScenarioConfigurationError, match="No scenario JSON files"):
        load_scenario_catalog(tmp_path)

    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ScenarioConfigurationError, match="Invalid JSON"):
        load_scenario_catalog(tmp_path)
