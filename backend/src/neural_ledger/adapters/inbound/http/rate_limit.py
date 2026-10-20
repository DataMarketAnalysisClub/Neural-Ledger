"""Rate limiting for the HTTP API (G07: OWASP API4:2023, LLM10).

Fixed one-minute windows, counted per caller and per client IP. The first rule whose method and path
prefix match a request is the only one applied, so uploads and chat (which run OCR, a classifier and a
language model) get their own, stricter budgets. A request over either budget gets 429 with Retry-After
and never reaches a use case. Rejected requests count too, so hammering does not reopen the window early.

The caller is the session cookie when there is one (accounts mode, a digest of it is kept, never the
token), else the X-User-Id header (demo mode). The header is the client's to choose, so in demo mode the
per-IP budget is the one that holds. The client IP is what uvicorn reports: behind a proxy, start it with
--proxy-headers and trust only that proxy (FORWARDED_ALLOW_IPS), or every caller shares the proxy's IP.

Counters live in this process's memory: a restart resets them, and several workers each keep their own.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SESSION_COOKIE = "nl_session"


@dataclass(frozen=True, slots=True)
class Limit:
    name: str
    path_prefix: str
    per_caller: int
    per_ip: int
    method: str | None = None  # None: any method
    window_seconds: int = 60

    def matches(self, method: str, path: str) -> bool:
        return (self.method is None or self.method == method) and path.startswith(self.path_prefix)


# Uploads run OCR (seconds to minutes) and chat calls a paid model: both get small budgets. Sign-in has no
# caller yet, so its budget is per IP. Everything else under /v1 gets a budget no person using the UI reaches.
DEFAULT_LIMITS: tuple[Limit, ...] = (
    Limit("statements", "/v1/statements", per_caller=10, per_ip=30, method="POST"),
    Limit("documents", "/v1/documents", per_caller=10, per_ip=30, method="POST"),
    Limit("chat", "/v1/chat", per_caller=20, per_ip=60, method="POST"),
    Limit("auth", "/v1/auth/", per_caller=10, per_ip=10, method="POST"),
    Limit("account", "/v1/account", per_caller=5, per_ip=10, method="DELETE"),  # checks a password: as strict as sign-in
    # Sends a password to the investment provider: as strict as sign-in, so the API is no oracle for its credentials.
    Limit("investment_link", "/v1/investments/link", per_caller=5, per_ip=10, method="POST"),
    Limit("investment_sync", "/v1/investments/sync", per_caller=10, per_ip=30, method="POST"),  # each one calls the provider
    Limit("api", "/v1/", per_caller=300, per_ip=900),
)


class FixedWindowCounter:
    """Counts hits per key in the current window and forgets earlier windows as soon as one ends."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._window: dict[int, int] = {}  # window_seconds -> index of the window being counted
        self._counts: dict[tuple[int, str], int] = {}  # (window_seconds, key) -> hits

    def hit(self, key: str, limit: int, window_seconds: int) -> int:
        """Counts one hit. Returns 0 if it is within the limit, else the seconds until the window ends."""
        now = self._now()
        index = int(now // window_seconds)
        if self._window.get(window_seconds) != index:
            self._window[window_seconds] = index
            self._counts = {k: v for k, v in self._counts.items() if k[0] != window_seconds}
        count = self._counts.get((window_seconds, key), 0) + 1
        self._counts[(window_seconds, key)] = count
        if count <= limit:
            return 0
        return max(1, math.ceil((index + 1) * window_seconds - now))


class RateLimitMiddleware:
    """Pure ASGI, so a streamed upload is refused before its body is read."""

    def __init__(self, app: ASGIApp, limits: tuple[Limit, ...] = DEFAULT_LIMITS, now: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self.limits = limits
        self.counter = FixedWindowCounter(now)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = next((rule for rule in self.limits if rule.matches(scope["method"], scope["path"])), None)
        if limit is not None:
            ip = scope["client"][0] if scope.get("client") else "unknown"
            retry_after = max(
                self.counter.hit(f"{limit.name}|caller|{_caller(scope)}", limit.per_caller, limit.window_seconds),
                self.counter.hit(f"{limit.name}|ip|{ip}", limit.per_ip, limit.window_seconds),
            )
            if retry_after:
                body = {"status": "RATE_LIMITED", "message": "too many requests", "retry_after": retry_after}
                await JSONResponse(body, status_code=429, headers={"Retry-After": str(retry_after)})(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _caller(scope: Scope) -> str:
    headers = dict(scope.get("headers") or ())
    for part in headers.get(b"cookie", b"").decode("latin-1").split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE and value:
            return "session:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    user = headers.get(b"x-user-id", b"").decode("latin-1")
    return "user:" + user if user else "anonymous"
