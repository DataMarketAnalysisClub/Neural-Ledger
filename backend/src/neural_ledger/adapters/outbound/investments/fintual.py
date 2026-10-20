"""Fintual adapter (ADR-044): the provider's documented REST API, read-only.

API: https://fintual.cl/api-docs/index.html (Swagger 2.0; the spec is /api-docs/v1/swagger.json), base
https://fintual.cl/api.
- POST /access_tokens with {"user": {"email", "password"}} answers 201 with the user's token in
  data.attributes.token. 400, 401, 403 and 422 mean the credentials were refused.
- GET /goals answers {"data": [{"id", "type": "goal", "attributes": {"name", "nav", ...}}]}; 401 means the token
  is not accepted. The spec names the headers X-User-Email and X-User-Token, but Fintual's own guide and its client
  libraries send user_email and user_token as query parameters, and a live sign-in (2026-10-19) got 401 with the
  headers alone. The request carries both, with the same values, so either server configuration reads them. `nav` is
  the goal's current value in pesos. `deposited`, when the response carries it, is the net amount deposited: it is
  not in the published spec, so it is optional, and a goal without it reports no gain.

Security:
- HTTPS only, and no redirect is followed: a redirect would carry the token to whatever host it names. The query
  string travels encrypted like the headers; nothing here ever logs a URL, only the path.
- Amounts are parsed as exact decimals (json parse_float=Decimal), never floats.
- No error carries the email, the password, the token or the provider's response body, which can echo what was
  sent. Errors are raised `from None`, so no traceback chains back to the request. Responses are capped at 2 MB.
- A failure is logged for the operator with the HTTP status, the path and, for an unexpected answer, the names of
  its fields (never a value), so a change on Fintual's side (a second factor, a renamed field) can be diagnosed.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

from ....application.ports import InvestmentAccessRejected, InvestmentProviderUnavailable
from ....domain.investments.model import ReportedGoal

FINTUAL_BASE_URL = "https://fintual.cl/api"
USER_AGENT = "neural-ledger/0.1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOKEN_LENGTH = 512
_REFUSED = frozenset({400, 401, 403, 422})


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201 - urllib's hook
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


class FintualInvestmentProvider:
    name = "fintual"
    provider = "fintual"
    synthetic = False

    def __init__(
        self, base_url: str = FINTUAL_BASE_URL, timeout_s: float = 10.0, opener: urllib.request.OpenerDirector | None = None,
        *, diagnose: bool = False,
    ) -> None:
        """`diagnose` (NL_FINTUAL_DIAGNOSTICS, local use): log the sign-in answer's type and field names, and when the
        goals are refused, try the other known ways of presenting the token, logging each one's HTTP status only."""
        if not base_url.startswith("https://"):
            raise ValueError("the Fintual API is reached over HTTPS only (NL_FINTUAL_BASE_URL)")
        self._base = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._opener = opener or urllib.request.build_opener(_NoRedirects())
        self._diagnose = diagnose

    def authenticate(self, email: str, password: str) -> str:
        body = json.dumps({"user": {"email": email, "password": password}}).encode("utf-8")
        data = self._call("POST", "/access_tokens", body=body)
        if self._diagnose:
            logger.warning("Fintual diagnosis: the sign-in answered data.type %s; fields: %s", _kind(data), _shape(data))
        try:
            token = data["data"]["attributes"]["token"]
        except (KeyError, TypeError):
            logger.warning("Fintual answered the sign-in without a token; fields: %s", _shape(data))
            raise InvestmentProviderUnavailable("Fintual answered the sign-in without a token") from None
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH or not token.isprintable():
            logger.warning("Fintual answered the sign-in with a token of an unexpected form")
            raise InvestmentProviderUnavailable("Fintual answered the sign-in with an unexpected token")
        return token

    def goals(self, email: str, token: str) -> tuple[ReportedGoal, ...]:
        credentials = {"user_email": email, "user_token": token}
        try:
            data = self._call("GET", "/goals", query=credentials, headers={"X-User-Email": email, "X-User-Token": token})
        except InvestmentAccessRejected:
            if not self._diagnose:
                raise
            data = self._probe(email, token)
        try:
            items = data["data"]
            if not isinstance(items, list):
                raise TypeError("data is not a list")
            return tuple(_goal(item) for item in items)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            logger.warning("Fintual answered the goals with an unexpected shape; fields: %s", _shape(data))
            raise InvestmentProviderUnavailable("Fintual answered the goals with an unexpected shape") from None

    def _probe(self, email: str, token: str) -> Any:
        """Diagnosis only: each other known way of presenting the token, one request each to the same HTTPS host.
        Logs which answered; the first that did is used. Refused by all of them: InvestmentAccessRejected."""
        variants: tuple[tuple[str, dict[str, str], dict[str, str] | None], ...] = (
            ("the X-User headers only", {"X-User-Email": email, "X-User-Token": token}, None),
            ("the user_email and user_token query only", {}, {"user_email": email, "user_token": token}),
            ("Authorization: Bearer", {"Authorization": f"Bearer {token}"}, None),
            ("Authorization: Token", {"Authorization": f'Token token="{token}", email="{email}"'}, None),
        )
        found: Any = None
        for label, headers, query in variants:
            logger.warning("Fintual diagnosis: trying GET /goals with %s", label)
            try:
                answer = self._call("GET", "/goals", headers=headers, query=query)
            except (InvestmentAccessRejected, InvestmentProviderUnavailable):
                continue  # _call logged its status
            logger.warning("Fintual diagnosis: GET /goals with %s answered 200", label)
            found = answer if found is None else found
        if found is None:
            raise InvestmentAccessRejected("Fintual refused every known way of presenting the token")
        return found

    def _call(
        self, method: str, path: str, *, body: bytes | None = None, headers: dict[str, str] | None = None, query: dict[str, str] | None = None
    ) -> Any:
        """`path` is what the logs name: never the URL, whose query string can carry a credential."""
        sent = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
        if body is not None:
            sent["Content-Type"] = "application/json"
        url = self._base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        request = urllib.request.Request(url, data=body, headers=sent, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            logger.warning("Fintual answered HTTP %s to %s %s", code, method, path)
            if code in _REFUSED:
                raise InvestmentAccessRejected(f"Fintual refused the request (HTTP {code})") from None
            raise InvestmentProviderUnavailable(f"Fintual returned HTTP {code}") from None
        except OSError as exc:  # URLError, timeouts and TLS errors
            logger.warning("Fintual could not be reached for %s %s (%s)", method, path, type(exc).__name__)
            raise InvestmentProviderUnavailable(f"Fintual could not be reached ({type(exc).__name__})") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            logger.warning("Fintual answered %s %s with more than %s bytes", method, path, MAX_RESPONSE_BYTES)
            raise InvestmentProviderUnavailable("Fintual answered with more data than expected")
        try:
            return json.loads(raw.decode("utf-8"), parse_float=Decimal)
        except (UnicodeDecodeError, ValueError, RecursionError):
            logger.warning("Fintual answered %s %s with something that is not JSON", method, path)
            raise InvestmentProviderUnavailable("Fintual answered with something that is not JSON") from None


def _kind(data: Any) -> str:
    """The answer's data.type when it is a short identifier (e.g. "access_token"): a kind, never a credential."""
    kind = data.get("data", {}).get("type") if isinstance(data, dict) and isinstance(data.get("data"), dict) else None
    return repr(kind) if isinstance(kind, str) and len(kind) <= 40 and kind.replace("_", "").isalnum() else "(none)"


def _shape(data: Any) -> str:
    """The field names of an answer, two levels down, and never a value: enough to see what changed, nothing to leak."""
    if not isinstance(data, dict):
        return type(data).__name__
    inner = data.get("data")
    nested = ""
    if isinstance(inner, dict):
        nested = f" data: {sorted(map(str, inner))}"
        if isinstance(inner.get("attributes"), dict):
            nested += f" data.attributes: {sorted(map(str, inner['attributes']))}"
    elif isinstance(inner, list):
        nested = f" data: list of {len(inner)}"
    return f"{sorted(map(str, data))}{nested}"


def _goal(item: Any) -> ReportedGoal:
    attributes = item["attributes"]
    goal_id = item["id"]
    if isinstance(goal_id, int) and not isinstance(goal_id, bool):
        goal_id = str(goal_id)
    deposited = attributes.get("deposited")
    return ReportedGoal(goal_id, attributes["name"], _decimal(attributes["nav"]), None if deposited is None else _decimal(deposited))


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise TypeError("an amount is a number")
    return Decimal(value)
