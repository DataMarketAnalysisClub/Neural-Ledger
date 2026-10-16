"""Who is calling, in accounts mode (NL_AUTH=accounts; D2, D6, D7). Demo mode never installs this guard.

IdentityGuard is a pure ASGI middleware inside CORS. Before any route runs or any body is read
(so streamed statement uploads keep working), it checks in this order:

1. An X-User-Id header on any request but GET /health: 400 IDENTITY_HEADER_REJECTED, even with a valid cookie.
2. An unsafe method (POST, PUT, PATCH, DELETE): an Origin must be one of the app origins (a foreign or
   "null" Origin is 403 ORIGIN_REJECTED); without an Origin the body must be declared JSON, which a
   cross-site form cannot send.
3. Except on the public routes, a valid nl_session cookie: otherwise 401 UNAUTHENTICATED.

The resolved Session is the only source of the user id. The cookie holds the token; the store keeps
its digest; no response body, audit record or log line ever contains it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import cookie_parser

from ....domain.user.account import Session

COOKIE = "nl_session"
SESSION_KEY = "neural_ledger.session"  # where the guard leaves the resolved Session in the ASGI scope
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
HEADER_EXEMPT = frozenset({("GET", "/health")})
PUBLIC_ROUTES = frozenset({
    ("GET", "/health"),
    ("GET", "/v1/audit/verify"),
    ("POST", "/v1/auth/signup"),
    ("POST", "/v1/auth/signin"),
    ("POST", "/v1/auth/demo-session"),
})

# contracts/auth/error.schema.json x-http-status
AUTH_HTTP_STATUS = {
    "IDENTITY_HEADER_REJECTED": 400,
    "UNAUTHENTICATED": 401,
    "INVALID_CREDENTIALS": 401,
    "ORIGIN_REJECTED": 403,
    "PROFILE_READ_ONLY": 403,
    "NOT_FOUND": 404,
    "EMAIL_TAKEN": 409,
    "INVALID_INPUT": 422,
}
_GUARD_MESSAGES = {
    "IDENTITY_HEADER_REJECTED": "identity headers are not accepted; sign in instead",
    "ORIGIN_REJECTED": "request origin not allowed",
    "UNAUTHENTICATED": "sign in required",
}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def auth_error_body(status: str, message: str, field: str | None = None) -> dict[str, str]:
    """An AuthError: generic message, never an echo of a supplied email, password, token or value."""
    body = {"status": status, "message": message}
    if field is not None:
        body["field"] = field
    return body


def _values(headers: list[tuple[bytes, bytes]], name: bytes) -> list[str]:
    return [value.decode("latin-1") for key, value in headers if key.lower() == name]


def session_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    cookies = "; ".join(_values(headers, b"cookie"))
    token = cookie_parser(cookies).get(COOKIE) if cookies else None
    return token or None


def _is_json(content_type: list[str]) -> bool:
    return len(content_type) == 1 and content_type[0].split(";", 1)[0].strip().lower() == "application/json"


def _cookie(value: str, expires: datetime, max_age: int, secure: bool) -> str:
    parts = [
        f"{COOKIE}={value}",
        f"Expires={format_datetime(expires.astimezone(UTC), usegmt=True)}",
        f"Max-Age={max(max_age, 0)}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def session_cookie(token: str, expires_at: datetime, now: datetime, secure: bool) -> str:
    """Absolute expiry: Expires is the session's, and Max-Age counts down to it on the API clock."""
    return _cookie(token, expires_at, int((expires_at - now).total_seconds()), secure)


def cleared_cookie(secure: bool) -> str:
    return _cookie("", _EPOCH, 0, secure)


def secure_cookie(setting: str, scheme: str, forwarded_proto: str | None) -> bool:
    """true | false, or auto: Secure when the request reached us (or the proxy in front) over https."""
    if setting in ("true", "false"):
        return setting == "true"
    proto = (forwarded_proto or "").split(",", 1)[0].strip().lower()
    return scheme == "https" or proto == "https"


class IdentityGuard:
    def __init__(self, app: Any, *, resolve: Callable[[str], Session | None], origins: tuple[str, ...]) -> None:
        self._app = app
        self._resolve = resolve
        self._origins = frozenset(origins)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        method, path = scope["method"].upper(), scope["path"]
        headers = scope.get("headers") or []
        if _values(headers, b"x-user-id") and (method, path) not in HEADER_EXEMPT:
            await _reject(send, "IDENTITY_HEADER_REJECTED")
            return
        if method in UNSAFE_METHODS:
            origins = _values(headers, b"origin")
            if origins:
                allowed = len(origins) == 1 and origins[0] in self._origins
            else:
                allowed = _is_json(_values(headers, b"content-type"))
            if not allowed:
                await _reject(send, "ORIGIN_REJECTED")
                return
        if (method, path) not in PUBLIC_ROUTES:
            token = session_token(headers)
            session = await run_in_threadpool(self._resolve, token) if token else None
            if session is None:
                await _reject(send, "UNAUTHENTICATED")
                return
            scope[SESSION_KEY] = session
        await self._app(scope, receive, send)


async def _reject(send: Any, status: str) -> None:
    body = json.dumps(auth_error_body(status, _GUARD_MESSAGES[status])).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": AUTH_HTTP_STATUS[status],
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
    })
    await send({"type": "http.response.body", "body": body})
