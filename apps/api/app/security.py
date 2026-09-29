"""Request limits, correlation IDs and safe failure handling."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .observability import log_event


logger = logging.getLogger("negotiation_arena.security")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class RequestBodyTooLarge(RuntimeError):
    """Raised before a request body can exceed the configured bound."""


def _positive_int(name: str, default: int, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ReliabilitySettings:
    max_request_body_bytes: int = 65_536
    max_voice_request_body_bytes: int = 7_200_000
    rate_limit_window_seconds: int = 60
    default_requests_per_window: int = 180
    expensive_requests_per_window: int = 30
    auth_requests_per_window: int = 12
    trust_proxy_headers: bool = False

    @classmethod
    def from_env(cls) -> "ReliabilitySettings":
        return cls(
            max_request_body_bytes=_positive_int(
                "MAX_REQUEST_BODY_BYTES", 65_536, minimum=4_096, maximum=2_000_000
            ),
            max_voice_request_body_bytes=_positive_int(
                "MAX_VOICE_REQUEST_BODY_BYTES", 7_200_000, minimum=1_000_000, maximum=8_000_000
            ),
            rate_limit_window_seconds=_positive_int(
                "RATE_LIMIT_WINDOW_SECONDS", 60, minimum=10, maximum=3_600
            ),
            default_requests_per_window=_positive_int(
                "RATE_LIMIT_DEFAULT", 180, minimum=10, maximum=10_000
            ),
            expensive_requests_per_window=_positive_int(
                "RATE_LIMIT_EXPENSIVE", 30, minimum=2, maximum=1_000
            ),
            auth_requests_per_window=_positive_int(
                "RATE_LIMIT_AUTH", 12, minimum=2, maximum=1_000
            ),
            trust_proxy_headers=_boolean("TRUST_PROXY_HEADERS", False),
        )


class SlidingWindowLimiter:
    """Small in-process limiter suitable for the single-worker API container."""

    def __init__(self, window_seconds: int) -> None:
        self._window = float(window_seconds)
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, bucket: str, limit: int, *, now: float | None = None) -> float | None:
        current = time.monotonic() if now is None else now
        threshold = current - self._window
        event_key = (key, bucket)
        with self._lock:
            events = self._events[event_key]
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= limit:
                return max(1.0, self._window - (current - events[0]))
            events.append(current)
            if len(self._events) > 8_192:
                stale = [item for item, values in self._events.items() if not values or values[-1] <= threshold]
                for item in stale[:2_048]:
                    self._events.pop(item, None)
        return None


def normalize_request_id(raw: str | None) -> str:
    if raw and _REQUEST_ID.fullmatch(raw.strip()):
        return raw.strip()
    return str(uuid4())


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _client_key(scope: Scope, headers: dict[str, str], trust_proxy_headers: bool) -> str:
    client = scope.get("client")
    address = client[0] if client else "unknown"
    if trust_proxy_headers:
        forwarded = headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded and len(forwarded) <= 128:
            address = forwarded
    return hashlib.sha256(address.encode("utf-8", "replace")).hexdigest()[:24]


def _rate_bucket(method: str, path: str) -> str:
    if path in {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/recover"} and method == "POST":
        return "auth"
    if path.endswith("/messages") and method == "POST":
        return "llm_message"
    if path.endswith("/report") and method == "GET":
        return "llm_report"
    if (path.endswith("/opponent-audio") or path.endswith("/opponent-audio-stream") or path.endswith("/opening-audio-stream")) and method == "POST":
        return "llm_speech"
    return "default"


class ReliabilityMiddleware:
    """Bound request resources, add diagnostics and never leak server errors."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: ReliabilitySettings | None = None,
    ) -> None:
        self.app = app
        self.settings = settings or ReliabilitySettings.from_env()
        self._limiter = SlidingWindowLimiter(self.settings.rate_limit_window_seconds)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        request_id = normalize_request_id(headers.get("x-request-id"))
        scope.setdefault("state", {})["request_id"] = request_id
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        request_body_limit = (
            self.settings.max_voice_request_body_bytes
            if method == "POST" and path.endswith("/voice-recordings")
            else self.settings.max_request_body_bytes
        )
        started = time.perf_counter()
        status_code = 500
        response_started = False
        response_complete = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code, response_started, response_complete
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                response_headers.append((b"x-content-type-options", b"nosniff"))
                if path.startswith("/api/") or path.startswith("/health"):
                    response_headers.append((b"cache-control", b"no-store"))
                message["headers"] = response_headers
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True
            await send(message)

        async def finish_early(code: int, detail: str, *, extra_headers: dict[str, str] | None = None) -> None:
            nonlocal status_code
            status_code = code
            response = JSONResponse(
                {"detail": detail, "request_id": request_id},
                status_code=code,
                headers=extra_headers,
            )
            await response(scope, receive, send_with_headers)

        try:
            content_length = headers.get("content-length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    await finish_early(400, "Invalid Content-Length header")
                    return
                if declared_length < 0:
                    await finish_early(400, "Invalid Content-Length header")
                    return
                if declared_length > request_body_limit:
                    await finish_early(413, "Request body is too large")
                    return

            if path.startswith("/api/v1"):
                bucket = _rate_bucket(method, path)
                limit = self.settings.default_requests_per_window
                if bucket in {"llm_message", "llm_report", "llm_speech"}:
                    limit = self.settings.expensive_requests_per_window
                elif bucket == "auth":
                    limit = self.settings.auth_requests_per_window
                retry_after = self._limiter.check(
                    _client_key(scope, headers, self.settings.trust_proxy_headers), bucket, limit
                )
                if retry_after is not None:
                    await finish_early(
                        429,
                        "Too many requests. Please retry later.",
                        extra_headers={"Retry-After": str(math.ceil(retry_after))},
                    )
                    return

            received = 0

            async def limited_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > request_body_limit:
                        raise RequestBodyTooLarge
                return message

            try:
                await self.app(scope, limited_receive, send_with_headers)
            except RequestBodyTooLarge:
                if response_started:
                    raise
                await finish_early(413, "Request body is too large")
            except Exception:
                log_event(
                    logger,
                    "request.unhandled_error",
                    level=logging.ERROR,
                    exc_info=True,
                    request_id=request_id,
                    method=method,
                    path=path,
                )
                if response_started:
                    raise
                await finish_early(500, "Internal server error")
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log_event(
                logger,
                "request.completed" if response_complete else "request.terminated",
                level=logging.INFO if status_code < 500 else logging.ERROR,
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )


__all__ = [
    "ReliabilityMiddleware",
    "ReliabilitySettings",
    "SlidingWindowLimiter",
    "normalize_request_id",
]
