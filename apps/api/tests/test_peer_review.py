from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import InMemorySessionRepository


def client() -> TestClient:
    return TestClient(create_app(InMemorySessionRepository()))


def _valid_payload(assignment: dict, *, low: bool = False) -> dict:
    evidence_id = next(item["id"] for item in assignment["messages"] if item["role"] == "participant")
    return {
        "assignment_id": assignment["assignment_id"],
        "overall_comment": "Рецензия опирается на конкретные реплики и критерии рубрики.",
        "items": [
            {
                "criterion_id": item["id"],
                "score": 0 if low else item["max_score"],
                "message_id": evidence_id,
                "comment": "Реплика показывает наблюдаемое поведение по этому критерию.",
                "suggested_text": "Лучше назвать интерес и задать открытый вопрос." if low else None,
            }
            for item in assignment["criteria"]
        ],
    }


def test_assignment_is_anonymous_and_hides_automatic_evaluation() -> None:
    api = client()

    response = api.get("/api/v1/peer-reviews/next")

    assert response.status_code == 200
    payload = response.json()
    assert payload["anonymized"] is True
    assert payload["double_blind"] is True
    assert len(payload["criteria"]) == 5
    assert {message["author_label"] for message in payload["messages"]} <= {
        payload["participant_alias"], "Сторона B"
    }
    assert payload["reviewer_alias"].startswith("Рецензент R-")
    assert payload["sla"]["blocking"] is False
    assert "Конфликт интересов исключён" in payload["matching_reasons"] or payload["assignment_kind"] == "calibration"
    rendered = json.dumps(payload, ensure_ascii=False).casefold()
    assert not any(token in rendered for token in (
        "automatic_score", "official_score", "engine_state", "batna", "reservation"
    ))


def test_anonymous_draft_is_not_shared_with_another_browser() -> None:
    app = create_app(InMemorySessionRepository())
    first = TestClient(app).get("/api/v1/peer-reviews/next").json()
    second = TestClient(app).get("/api/v1/peer-reviews/next").json()
    assert first["assignment_id"] != second["assignment_id"]
    assert first["reviewer_alias"] != second["reviewer_alias"]


def test_submission_compares_scores_without_changing_official_score() -> None:
    api = client()
    assignment = api.get("/api/v1/peer-reviews/next").json()
    payload = _valid_payload(assignment)

    response = api.post("/api/v1/peer-reviews", json=payload)

    assert response.status_code == 201
    result = response.json()
    assert result["peer_score"] == 100
    assert result["difference"] == 100 - result["automatic_score"]
    assert result["absolute_difference"] == abs(result["difference"])
    assert result["official_score_unchanged"] is True
    assert len(result["comparison"]) == 5
    assert 0 <= result["reputation"]["points"] <= 100


def test_low_score_requires_improved_wording() -> None:
    api = client()
    assignment = api.get("/api/v1/peer-reviews/next").json()
    payload = _valid_payload(assignment)
    first = assignment["criteria"][0]
    payload["items"][0]["score"] = first["low_score_threshold"]

    response = api.post("/api/v1/peer-reviews", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "low_score_requires_suggested_text"


def test_every_criterion_and_valid_message_reference_are_required() -> None:
    api = client()
    assignment = api.get("/api/v1/peer-reviews/next").json()
    missing = _valid_payload(assignment)
    missing["items"].pop()
    assert api.post("/api/v1/peer-reviews", json=missing).status_code == 422

    invalid_reference = _valid_payload(assignment)
    invalid_reference["items"][0]["message_id"] = "00000000-0000-0000-0000-000000000000"
    response = api.post("/api/v1/peer-reviews", json=invalid_reference)
    assert response.status_code == 422
    assert response.json()["detail"] == "message_is_not_in_assignment"

    opponent_reference = _valid_payload(assignment)
    opponent_reference["items"][0]["message_id"] = next(
        item["id"] for item in assignment["messages"] if item["role"] == "opponent"
    )
    response = api.post("/api/v1/peer-reviews", json=opponent_reference)
    assert response.status_code == 422
    assert response.json()["detail"] == "evidence_must_reference_participant"


def test_assignment_cannot_be_submitted_twice() -> None:
    api = client()
    assignment = api.get("/api/v1/peer-reviews/next").json()
    payload = _valid_payload(assignment)

    assert api.post("/api/v1/peer-reviews", json=payload).status_code == 201
    assert api.post("/api/v1/peer-reviews", json=payload).status_code == 409


def test_completed_own_session_is_excluded_from_review_assignment() -> None:
    api = client()
    created = api.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()
    session_id = created["id"]
    api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Какие условия поставки для вас являются приоритетными?"},
    )
    api.post(f"/api/v1/sessions/{session_id}/complete")

    assignment = api.get(
        "/api/v1/peer-reviews/next", params={"exclude_session_id": session_id}
    )

    assert assignment.status_code == 200
    assert assignment.json()["assignment_id"]


def test_disputed_review_gets_blind_independent_second_round() -> None:
    app = create_app(InMemorySessionRepository())
    first = TestClient(app)
    created = first.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).json()
    first.post(
        f"/api/v1/sessions/{created['id']}/messages",
        json={"content": "Какие параметры цены, срока и сервиса для вас приоритетны?"},
    )
    first.post(f"/api/v1/sessions/{created['id']}/complete")
    assignment = first.get("/api/v1/peer-reviews/next").json()
    assert assignment["assignment_kind"] == "peer"
    result = first.post("/api/v1/peer-reviews", json=_valid_payload(assignment)).json()
    assert result["second_review_required"] is True
    assert result["review_status"] == "second_review_required"
    assert result["official_score_unchanged"] is True

    second = TestClient(app)
    second_auth = second.post(
        "/api/v1/auth/register",
        json={"email": "second-round@example.test", "display_name": "Второй", "password": "Strong-pass-42"},
    ).json()
    second_headers = {"X-CSRF-Token": second_auth["csrf_token"]}
    calibration = second.get("/api/v1/peer-reviews/next").json()
    second.post("/api/v1/peer-reviews", json=_valid_payload(calibration), headers=second_headers)
    follow_up = second.get("/api/v1/peer-reviews/next").json()
    assert follow_up["review_round"] == 2
    assert "Независимая повторная проверка" in follow_up["matching_reasons"]
    rendered = json.dumps(follow_up, ensure_ascii=False).casefold()
    assert "peer_score" not in rendered and "automatic_score" not in rendered
    resolved = second.post("/api/v1/peer-reviews", json=_valid_payload(follow_up), headers=second_headers).json()
    assert resolved["review_status"] == "resolved"
    assert resolved["reviews_received"] == 2


def test_registered_reviewer_starts_with_calibration_and_reputation_is_not_strictness() -> None:
    api = client()
    registered = api.post(
        "/api/v1/auth/register",
        json={"email": "calibration@example.test", "display_name": "Калибратор", "password": "Strong-pass-42"},
    ).json()
    assignment = api.get("/api/v1/peer-reviews/next").json()
    assert assignment["assignment_kind"] == "calibration"
    assert assignment["review_round"] == 1
    result = api.post(
        "/api/v1/peer-reviews",
        json=_valid_payload(assignment),
        headers={"X-CSRF-Token": registered["csrf_token"]},
    ).json()
    assert result["review_status"] == "calibrated"
    assert result["reputation"]["strictness_neutral"] is True
    assert {"accuracy", "evidence_quality", "helpfulness"} <= set(result["reputation"])


def test_matching_accepts_language_and_difficulty_filters() -> None:
    api = client()
    created = api.post(
        "/api/v1/sessions",
        json={
            "scenario_id": "project-resources",
            "configuration": {
                "topic": "Сложный ресурсный спор",
                "context": "Команды согласуют ограниченный бюджет и сроки запуска цифрового проекта.",
                "participant_role": "Руководитель проекта",
                "opponent_role": "Операционный директор",
                "objective": "Согласовать исполнимый пакет ресурсов",
                "difficulty": "hard",
                "tone": "firm",
                "max_turns": 12,
            },
        },
    ).json()
    api.post(f"/api/v1/sessions/{created['id']}/messages", json={"content": "Какие ограничения и критерии для вас приоритетны?"})
    api.post(f"/api/v1/sessions/{created['id']}/complete")
    assignment = api.get("/api/v1/peer-reviews/next", params={"language": "ru", "difficulty": "hard"}).json()
    assert assignment["language"] == "ru"
    assert assignment["difficulty"] == "hard"


def test_matching_does_not_mislabel_russian_dialogue_as_english() -> None:
    api = client()
    created = api.post(
        "/api/v1/sessions",
        json={
            "scenario_id": "project-resources",
            "configuration": {
                "topic": "Project resource allocation",
                "context": "Two teams negotiate a limited budget and an implementation deadline.",
                "participant_role": "Project manager",
                "opponent_role": "Operations director",
                "objective": "Agree on an executable resource package",
                "difficulty": "medium",
                "tone": "businesslike",
                "max_turns": 12,
            },
        },
    ).json()
    api.post(
        f"/api/v1/sessions/{created['id']}/messages",
        json={"content": "Which constraints and success criteria matter most to your team?"},
    )
    api.post(f"/api/v1/sessions/{created['id']}/complete")
    assignment = api.get("/api/v1/peer-reviews/next", params={"language": "en"}).json()
    assert assignment["language"] == "en"
    assert assignment["scenario_title"] == "Project resource allocation"


def test_owner_can_appeal_and_second_independent_review_resolves_dispute() -> None:
    app = create_app(InMemorySessionRepository())
    owner = TestClient(app)
    owner_auth = owner.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.test", "display_name": "Участник", "password": "Strong-pass-42"},
    ).json()
    owner_headers = {"X-CSRF-Token": owner_auth["csrf_token"]}
    session = owner.post(
        "/api/v1/sessions",
        json={"scenario_id": "equipment-supply"},
        headers=owner_headers,
    ).json()
    owner.post(
        f"/api/v1/sessions/{session['id']}/messages",
        json={"content": "Предлагаю обсудить цену, срок и сервис как единый пакет."},
        headers=owner_headers,
    )
    owner.post(f"/api/v1/sessions/{session['id']}/complete", headers=owner_headers)

    reviewer_one = TestClient(app)
    reviewer_one_auth = reviewer_one.post(
        "/api/v1/auth/register",
        json={"email": "reviewer-one@example.test", "display_name": "Рецензент 1", "password": "Strong-pass-42"},
    ).json()
    reviewer_one_headers = {"X-CSRF-Token": reviewer_one_auth["csrf_token"]}
    calibration = reviewer_one.get("/api/v1/peer-reviews/next").json()
    reviewer_one.post(
        "/api/v1/peer-reviews",
        json=_valid_payload(calibration),
        headers=reviewer_one_headers,
    )
    first_review = reviewer_one.get("/api/v1/peer-reviews/next").json()
    assert first_review["assignment_kind"] == "peer"
    reviewer_one.post(
        "/api/v1/peer-reviews",
        json=_valid_payload(first_review),
        headers=reviewer_one_headers,
    )

    status_before = owner.get(f"/api/v1/sessions/{session['id']}/peer-review-status").json()
    assert status_before["can_appeal"] is True
    assert status_before["official_score_unchanged"] is True
    appeal = owner.post(
        f"/api/v1/peer-reviews/{first_review['assignment_id']}/appeal",
        json={"reason": "Оценка не учитывает пакетное предложение и выбранную доказательную реплику."},
        headers=owner_headers,
    )
    assert appeal.status_code == 200
    assert appeal.json()["appeal_status"] == "pending"
    assert appeal.json()["peer_review_blocking"] is False

    reviewer_two = TestClient(app)
    reviewer_two_auth = reviewer_two.post(
        "/api/v1/auth/register",
        json={"email": "reviewer-two@example.test", "display_name": "Рецензент 2", "password": "Strong-pass-42"},
    ).json()
    reviewer_two_headers = {"X-CSRF-Token": reviewer_two_auth["csrf_token"]}
    calibration_two = reviewer_two.get("/api/v1/peer-reviews/next").json()
    reviewer_two.post(
        "/api/v1/peer-reviews",
        json=_valid_payload(calibration_two),
        headers=reviewer_two_headers,
    )
    second_review = reviewer_two.get("/api/v1/peer-reviews/next").json()
    assert second_review["assignment_id"] != first_review["assignment_id"]
    assert second_review["review_round"] == 2
    reviewer_two.post(
        "/api/v1/peer-reviews",
        json=_valid_payload(second_review),
        headers=reviewer_two_headers,
    )

    status_after = owner.get(f"/api/v1/sessions/{session['id']}/peer-review-status").json()
    assert status_after["status"] == "resolved"
    assert status_after["reviews_received"] == 2
    assert status_after["can_appeal"] is False
    assert status_after["peer_review_blocking"] is False
    assert status_after["official_score_unchanged"] is True
    assert status_after["reviews"][0]["appeal_status"] == "resolved"
