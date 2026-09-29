from __future__ import annotations

import json
import logging
from io import StringIO

from fastapi.testclient import TestClient

from app.main import create_app
from app.observability import StructuredRedactingFormatter
from app.repository import InMemorySessionRepository


def _client() -> TestClient:
    return TestClient(create_app(InMemorySessionRepository()))


def test_invalid_request_id_is_replaced_and_api_is_not_cached() -> None:
    response = _client().get(
        "/api/v1/scenarios",
        headers={"X-Request-ID": "bad request id with spaces"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad request id with spaces"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_request_body_limit_rejects_before_validation(monkeypatch) -> None:
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "4096")
    response = _client().post(
        "/api/v1/sessions",
        content=b"x" * 4097,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large"


def test_expensive_endpoint_is_rate_limited(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_EXPENSIVE", "2")
    api = _client()
    path = "/api/v1/sessions/00000000-0000-0000-0000-000000000000/messages"

    assert api.post(path, json={"content": "test"}).status_code == 404
    assert api.post(path, json={"content": "test"}).status_code == 404
    limited = api.post(path, json={"content": "test"})

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_unknown_host_is_rejected() -> None:
    response = _client().get("/health", headers={"Host": "attacker.invalid"})
    assert response.status_code == 400


def test_production_disables_interactive_api_docs(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    assert _client().get("/docs").status_code == 404
    assert _client().get("/openapi.json").status_code == 404


def test_structured_formatter_redacts_known_secrets(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "very-secret-test-value")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredRedactingFormatter())
    test_logger = logging.getLogger("redaction-test")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    test_logger.setLevel(logging.INFO)

    test_logger.info(
        "provider failed",
        extra={
            "event": "provider.failure",
            "context": {"detail": "api_key=very-secret-test-value"},
        },
    )

    rendered = stream.getvalue()
    assert "very-secret-test-value" not in rendered
    assert "[REDACTED]" in rendered
    assert json.loads(rendered)["event"] == "provider.failure"
