from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import InMemorySessionRepository


def _register(client: TestClient, email: str, *, claim_session_id: str | None = None):
    payload = {
        "email": email,
        "display_name": email.split("@", 1)[0].title(),
        "password": "Strong-pass-42",
    }
    if claim_session_id:
        payload["claim_session_id"] = claim_session_id
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    return response.json()


def test_account_claim_isolation_history_logout_and_cross_device_login() -> None:
    app = create_app(InMemorySessionRepository())
    anonymous = TestClient(app)
    first_session = anonymous.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"})
    assert first_session.status_code == 201
    session_id = first_session.json()["id"]

    first = TestClient(app)
    auth = _register(first, "first@example.test", claim_session_id=session_id)
    assert auth["account"]["roles"] == ["participant", "reviewer"]
    assert auth["recovery_code"]
    csrf = auth["csrf_token"]

    history = first.get("/api/v1/me/history")
    assert history.status_code == 200
    assert [item["session_id"] for item in history.json()["negotiations"]] == [session_id]

    second = TestClient(app)
    second_auth = _register(second, "second@example.test")
    assert second.get(f"/api/v1/sessions/{session_id}").status_code == 404
    owned = second.post(
        "/api/v1/sessions",
        json={"scenario_id": "project-resources"},
        headers={"X-CSRF-Token": second_auth["csrf_token"]},
    )
    assert owned.status_code == 201
    assert first.get(f"/api/v1/sessions/{owned.json()['id']}").status_code == 404

    assert first.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert first.get("/api/v1/auth/me").status_code == 401

    another_device = TestClient(app)
    login = another_device.post(
        "/api/v1/auth/login",
        json={"email": "first@example.test", "password": "Strong-pass-42"},
    )
    assert login.status_code == 200
    assert another_device.get("/api/v1/me/history").json()["negotiations"][0]["session_id"] == session_id


def test_recovery_rotates_code_and_revokes_sessions() -> None:
    app = create_app(InMemorySessionRepository())
    client = TestClient(app)
    registered = _register(client, "recover@example.test")
    old_code = registered["recovery_code"]

    recovered = client.post(
        "/api/v1/auth/recover",
        json={
            "email": "recover@example.test",
            "recovery_code": old_code,
            "new_password": "Replacement-84",
        },
    )
    assert recovered.status_code == 200
    assert recovered.json()["recovery_code"] != old_code
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "recover@example.test", "password": "Strong-pass-42"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "recover@example.test", "password": "Replacement-84"}).status_code == 200


def test_csrf_peer_history_and_delete_account() -> None:
    app = create_app(InMemorySessionRepository())
    client = TestClient(app)
    registered = _register(client, "delete@example.test")
    csrf = registered["csrf_token"]

    assert client.post("/api/v1/sessions", json={"scenario_id": "equipment-supply"}).status_code == 403
    created = client.post(
        "/api/v1/sessions",
        json={"scenario_id": "equipment-supply"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201

    assignment = client.get("/api/v1/peer-reviews/next").json()
    message_id = assignment["messages"][0]["id"]
    items = [
        {
            "criterion_id": criterion["id"],
            "score": criterion["max_score"],
            "message_id": message_id,
            "comment": "Оценка подтверждена конкретной репликой участника.",
            "suggested_text": None,
        }
        for criterion in assignment["criteria"]
    ]
    submitted = client.post(
        "/api/v1/peer-reviews",
        json={"assignment_id": assignment["assignment_id"], "items": items, "overall_comment": "Аргументированная и полная проверка диалога."},
        headers={"X-CSRF-Token": csrf},
    )
    assert submitted.status_code == 201
    assert len(client.get("/api/v1/me/history").json()["peer_reviews"]) == 1

    deleted = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={"password": "Strong-pass-42"},
        headers={"X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "delete@example.test", "password": "Strong-pass-42"}).status_code == 401
