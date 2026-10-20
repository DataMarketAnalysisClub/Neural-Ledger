"""The Fintual adapter (ADR-044) against a fake opener: the documented requests, exact amounts, and errors that never
carry a credential. No network."""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

import pytest

from neural_ledger.adapters.outbound.investments.fintual import MAX_RESPONSE_BYTES, FintualInvestmentProvider, _NoRedirects
from neural_ledger.application.ports import InvestmentAccessRejected, InvestmentProviderUnavailable
from neural_ledger.domain.investments.model import ReportedGoal

EMAIL = "ana@example.invalid"
PASSWORD = "synthetic-password-for-tests"
TOKEN = "synthetic-token-value"
GOALS = {
    "data": [
        {"id": "24", "type": "goal", "attributes": {"name": "Mi Casita", "nav": 1264350.4, "deposited": 1200000, "profit": 64350.4}},
        {"id": 25, "type": "goal", "attributes": {"name": "Viaje", "nav": 666.0}},
    ]
}


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeOpener:
    """Answers each request in turn with (status, body) or raises the given exception; records every request."""

    def __init__(self, *answers: tuple[int, bytes] | BaseException) -> None:
        self.answers = list(answers)
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float | None = None) -> _Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        status, body = answer
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(body))
        return _Response(body)


def _json(value: object) -> bytes:
    return json.dumps(value).encode("utf-8")


def _provider(*answers) -> tuple[FintualInvestmentProvider, FakeOpener]:
    opener = FakeOpener(*answers)
    return FintualInvestmentProvider(opener=opener), opener


def test_sign_in_posts_the_documented_body_and_returns_the_token():
    provider, opener = _provider((201, _json({"data": {"id": "1", "type": "access_token", "attributes": {"token": TOKEN}}})))
    assert provider.authenticate(EMAIL, PASSWORD) == TOKEN
    request = opener.requests[0]
    assert request.full_url == "https://fintual.cl/api/access_tokens" and request.get_method() == "POST"
    assert json.loads(request.data) == {"user": {"email": EMAIL, "password": PASSWORD}}
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["content-type"] == "application/json" and headers["accept"] == "application/json"
    assert "x-user-token" not in headers


def test_goals_send_the_credentials_both_ways_and_keep_amounts_exact():
    provider, opener = _provider((200, _json(GOALS)))
    goals = provider.goals(EMAIL, TOKEN)
    assert goals == (
        ReportedGoal("24", "Mi Casita", Decimal("1264350.4"), Decimal("1200000")),
        ReportedGoal("25", "Viaje", Decimal("666.0"), None),
    )
    request = opener.requests[0]
    headers = {k.lower(): v for k, v in request.header_items()}
    url = urllib.parse.urlsplit(request.full_url)
    assert (url.scheme, url.netloc, url.path) == ("https", "fintual.cl", "/api/goals") and request.get_method() == "GET" and request.data is None
    # The spec's headers, and the query parameters Fintual's guide and clients use (a live sign-in needed them).
    assert headers["x-user-email"] == EMAIL and headers["x-user-token"] == TOKEN
    assert urllib.parse.parse_qs(url.query) == {"user_email": [EMAIL], "user_token": [TOKEN]}


@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_refused_credentials_are_access_rejected(status):
    provider, _ = _provider((status, _json({"errors": f"bad credentials for {EMAIL}"})))
    with pytest.raises(InvestmentAccessRejected) as error:
        provider.authenticate(EMAIL, PASSWORD)
    _no_secret_in(error.value)


def test_an_expired_token_is_access_rejected():
    provider, _ = _provider((401, b'{"errors":"invalid token"}'))
    with pytest.raises(InvestmentAccessRejected) as error:
        provider.goals(EMAIL, TOKEN)
    _no_secret_in(error.value)


@pytest.mark.parametrize(
    "answer",
    [
        (500, b"oops"),
        (404, b"{}"),
        urllib.error.URLError("no route to host"),
        TimeoutError("timed out"),
        (200, b"<html>not json</html>"),
        (200, b"\xff\xfe"),
        (200, b"x" * (MAX_RESPONSE_BYTES + 1)),
        (201, _json({"data": {"attributes": {}}})),
        (201, _json({"data": {"attributes": {"token": ""}}})),
        (201, _json({"data": {"attributes": {"token": "a\nb"}}})),
        (201, _json({"data": {"attributes": {"token": "t" * 513}}})),
    ],
)
def test_sign_in_failures_are_unavailable_and_say_nothing_secret(answer):
    provider, _ = _provider(answer)
    with pytest.raises(InvestmentProviderUnavailable) as error:
        provider.authenticate(EMAIL, PASSWORD)
    _no_secret_in(error.value)


@pytest.mark.parametrize(
    "body",
    [
        {"data": {"id": "1"}},
        {"data": [{"id": "1", "attributes": {"name": "x"}}]},
        {"data": [{"id": "1", "attributes": {"name": "x", "nav": "1000"}}]},
        {"data": [{"id": "1", "attributes": {"name": "x", "nav": True}}]},
        {"data": [{"id": "1", "attributes": {"name": "x", "nav": 1, "deposited": "5"}}]},
        {"nodata": []},
    ],
)
def test_goals_in_an_unexpected_shape_are_unavailable(body):
    provider, _ = _provider((200, _json(body)))
    with pytest.raises(InvestmentProviderUnavailable) as error:
        provider.goals(EMAIL, TOKEN)
    _no_secret_in(error.value)


def test_failures_are_logged_with_the_status_and_field_names_never_a_credential(caplog):
    caplog.set_level(logging.WARNING, logger="neural_ledger.adapters.outbound.investments.fintual")
    answers = (
        (401, _json({"errors": f"bad credentials for {EMAIL}"})),
        (201, _json({"message": f"code sent to {EMAIL}", "data": {"attributes": {"otp_required": True}}})),
        urllib.error.URLError("no route to host"),
    )
    for answer in answers:
        provider, _ = _provider(answer)
        with pytest.raises((InvestmentAccessRejected, InvestmentProviderUnavailable)):
            provider.authenticate(EMAIL, PASSWORD)
    provider, _ = _provider((200, _json({"data": {"unexpected": TOKEN}})))
    with pytest.raises(InvestmentProviderUnavailable):
        provider.goals(EMAIL, TOKEN)
    logged = [record.getMessage() for record in caplog.records]
    assert logged == [
        "Fintual answered HTTP 401 to POST /access_tokens",
        "Fintual answered the sign-in without a token; fields: ['data', 'message'] data: ['attributes'] data.attributes: ['otp_required']",
        "Fintual could not be reached for POST /access_tokens (URLError)",
        "Fintual answered the goals with an unexpected shape; fields: ['data'] data: ['unexpected']",
    ]
    assert not any(secret in line for line in logged for secret in (EMAIL, PASSWORD, TOKEN))


def test_without_diagnosis_a_refused_read_is_one_request():
    provider, opener = _provider((401, b"{}"))
    with pytest.raises(InvestmentAccessRejected):
        provider.goals(EMAIL, TOKEN)
    assert len(opener.requests) == 1


def test_diagnosis_tries_the_other_token_styles_and_uses_the_first_that_answers(caplog):
    caplog.set_level(logging.WARNING, logger="neural_ledger.adapters.outbound.investments.fintual")
    opener = FakeOpener((401, b"{}"), (401, b"{}"), (401, b"{}"), (200, _json(GOALS)), (401, b"{}"))
    provider = FintualInvestmentProvider(opener=opener, diagnose=True)
    assert [goal.goal_id for goal in provider.goals(EMAIL, TOKEN)] == ["24", "25"]
    assert [request.get_header("Authorization") for request in opener.requests] == [None, None, None, f"Bearer {TOKEN}", f'Token token="{TOKEN}", email="{EMAIL}"']
    logged = [record.getMessage() for record in caplog.records]
    assert "Fintual diagnosis: GET /goals with Authorization: Bearer answered 200" in logged
    assert not any(secret in line for line in logged for secret in (EMAIL, PASSWORD, TOKEN))


def test_diagnosis_refused_everywhere_is_still_access_rejected_and_logs_the_sign_in_shape(caplog):
    caplog.set_level(logging.WARNING, logger="neural_ledger.adapters.outbound.investments.fintual")
    sign_in = (201, _json({"data": {"id": "9", "type": "access_token", "attributes": {"token": TOKEN, "email": EMAIL}}}))
    opener = FakeOpener(sign_in, *([(401, b"{}")] * 5))
    provider = FintualInvestmentProvider(opener=opener, diagnose=True)
    token = provider.authenticate(EMAIL, PASSWORD)
    with pytest.raises(InvestmentAccessRejected):
        provider.goals(EMAIL, token)
    logged = [record.getMessage() for record in caplog.records]
    assert logged[0] == "Fintual diagnosis: the sign-in answered data.type 'access_token'; fields: ['data'] data: ['attributes', 'id', 'type'] data.attributes: ['email', 'token']"
    assert not any(secret in line for line in logged for secret in (EMAIL, PASSWORD, TOKEN))


def test_only_https_is_accepted():
    with pytest.raises(ValueError):
        FintualInvestmentProvider("http://fintual.cl/api")


def test_redirects_are_refused_so_the_token_header_never_travels_elsewhere():
    request = urllib.request.Request("https://fintual.cl/api/goals", headers={"X-User-Token": TOKEN})
    with pytest.raises(urllib.error.HTTPError):
        _NoRedirects().redirect_request(request, io.BytesIO(b""), 302, "Found", {}, "https://elsewhere.invalid/steal")
    opener = FintualInvestmentProvider()._opener
    assert any(isinstance(h, _NoRedirects) for h in opener.handlers)
    assert not any(type(h) is urllib.request.HTTPRedirectHandler for h in opener.handlers)


def _no_secret_in(error: BaseException) -> None:
    text = str(error)
    assert EMAIL not in text and PASSWORD not in text and TOKEN not in text
    # No chained traceback leads back to the request (raised `from None`, or outside any handler).
    assert error.__cause__ is None and (error.__context__ is None or error.__suppress_context__)
