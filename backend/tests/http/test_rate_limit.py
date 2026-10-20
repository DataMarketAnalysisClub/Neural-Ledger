"""G07 rate limiting (ADR-033): per caller and per IP, fixed one-minute windows, 429 with Retry-After."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from neural_ledger.adapters.inbound.http.app import create_app  # noqa: E402
from neural_ledger.adapters.inbound.http.rate_limit import DEFAULT_LIMITS, Limit  # noqa: E402
from neural_ledger.bootstrap.config import Settings  # noqa: E402
from tests.contract.test_contracts import validate  # noqa: E402

TIGHT = (Limit("chat", "/v1/chat", per_caller=2, per_ip=3, method="POST"), Limit("api", "/v1/", per_caller=5, per_ip=5))


class FakeTime:
    def __init__(self, at: float = 1_000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def _client(services, limits=TIGHT, now=None) -> TestClient:
    extra = {} if now is None else {"rate_clock": now}
    return TestClient(create_app(services, cors_origins=("http://localhost:3000",), rate_limits=limits, **extra))


def _chat(client, user="u1", **headers):
    return client.post("/v1/chat", json={"session_id": "rl", "message": "hola"}, headers={"X-User-Id": user, **headers})


def test_a_burst_over_the_callers_budget_is_429_with_retry_after(services):
    client = _client(services)
    assert [_chat(client).status_code for _ in range(2)] == [200, 200]
    limited = _chat(client)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == str(limited.json()["retry_after"])
    validate(limited.json(), "common/rate_limited.schema.json")


def test_the_window_reopens_when_the_minute_ends(services):
    clock = FakeTime(1_020.0)  # 40 s left in the window [1020 // 60 * 60, +60) = [1020, 1080)
    client = _client(services, now=clock)
    for _ in range(2):
        _chat(client)
    assert _chat(client).json()["retry_after"] == 60
    clock.at = 1_079.5
    assert _chat(client).json()["retry_after"] == 1
    clock.at = 1_080.0
    assert _chat(client).status_code == 200


def test_rotating_the_identity_header_does_not_escape_the_ip_budget(services):
    client = _client(services)
    codes = [_chat(client, user=f"u{i}").status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]


def test_callers_and_routes_have_separate_budgets(services):
    client = _client(services)
    for _ in range(2):
        _chat(client, user="a")
    assert _chat(client, user="a").status_code == 429
    assert client.get("/v1/state", headers={"X-User-Id": "a"}).status_code != 429  # the general budget is untouched


def test_the_session_cookie_is_the_caller_when_present(services):
    client = _client(services, limits=(Limit("api", "/v1/", per_caller=1, per_ip=10),))
    client.cookies.set("nl_session", "token-one")
    assert client.get("/v1/state").status_code == 200
    assert client.get("/v1/state").status_code == 429
    client.cookies.set("nl_session", "token-two")
    assert client.get("/v1/state").status_code == 200


def test_health_is_never_limited(services):
    client = _client(services, limits=(Limit("api", "/v1/", per_caller=0, per_ip=0),))
    assert all(client.get("/health").status_code == 200 for _ in range(20))
    assert client.get("/v1/state").status_code == 429


def test_a_429_carries_cors_headers_so_the_browser_can_read_it(services):
    client = _client(services)
    for _ in range(2):
        _chat(client, Origin="http://localhost:3000")
    limited = _chat(client, Origin="http://localhost:3000")
    assert limited.status_code == 429 and limited.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_an_upload_over_budget_is_refused_whatever_its_body(services):
    client = _client(services, limits=(Limit("statements", "/v1/statements", per_caller=0, per_ip=0, method="POST"),))
    assert client.post("/v1/statements", content=b"%PDF-1.7").status_code == 429
    assert client.get("/v1/statements").status_code == 200  # GET is not the upload rule


def test_defaults_cover_uploads_chat_and_sign_in():
    rules = {rule.name: rule for rule in DEFAULT_LIMITS}
    assert rules["statements"].per_caller <= 10 and rules["chat"].per_caller <= 20 and rules["auth"].per_ip <= 10
    assert all(rule.path_prefix.startswith("/v1/") for rule in DEFAULT_LIMITS)


def test_every_call_to_an_outside_service_has_its_own_budget():
    rules = {rule.name: rule for rule in DEFAULT_LIMITS}
    for path in ("/v1/connections", "/v1/connections/bank", "/v1/connections/conn_1/sync", "/v1/investments/sync"):
        rule = next(r for r in DEFAULT_LIMITS if r.matches("POST", path))
        assert rule.name != "api" and rule.per_caller <= 10, path
    assert next(r for r in DEFAULT_LIMITS if r.matches("GET", "/v1/connections")).name == "api"
    assert rules["connections"].per_ip <= 30


def test_rate_limit_can_be_turned_off_only_explicitly():
    assert Settings().rate_limit and Settings.from_env({}).rate_limit
    assert not Settings.from_env({"NL_RATE_LIMIT": "off"}).rate_limit
