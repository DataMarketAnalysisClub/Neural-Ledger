"""HTTP adapter (FastAPI). With identity.py, the ONLY modules that import FastAPI or Starlette.

Thin by design: parse the request, call one use case, serialize with to_primitive. No money
math and no permission logic here. Who the user is depends on NL_AUTH (docs/SECURITY.md):
demo reads the X-User-Id header (or the default persona) and keeps profiles read-only;
accounts reads only the nl_session cookie, through the guard in identity.py.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from ....application.facade import ApplicationServices
from ....application.use_cases.accounts import SANDBOX_NOTICE, AccountOutcome, AccountStatus, IssuedSession
from ....application.use_cases.actions import ActorContext
from ....application.use_cases.statements import MAX_STATEMENT_BYTES
from ....domain.audit.events import Actor
from ....domain.shared.serialization import to_primitive
from ....domain.user.account import Session
from ....domain.user.profile import QuestionnaireAnswer
from .identity import (
    AUTH_HTTP_STATUS,
    SESSION_KEY,
    IdentityGuard,
    auth_error_body,
    cleared_cookie,
    secure_cookie,
    session_cookie,
    session_token,
)
from .rate_limit import DEFAULT_LIMITS, Limit, RateLimitMiddleware

_STATUS_CODES = {"OK": 200, "INVALID_INPUT": 422, "INSUFFICIENT_DATA": 409}
_ACTION_CODES = {"PROPOSED": 201, "CONFIRMED": 201, "EXECUTED": 200, "FAILED": 502, "BLOCKED": 403, "INVALID_INPUT": 422, "INSUFFICIENT_DATA": 409}
_LINK_CODES = {
    "LINKED": 201, "SYNCED": 200, "UNLINKED": 200, "NOT_LINKED": 404, "INVALID_INPUT": 422, "ACCESS_REJECTED": 422,
    "READ_REFUSED": 502, "RELINK_REQUIRED": 409, "CONFLICT": 409, "PROVIDER_UNAVAILABLE": 503,
}
MAX_JSON_BYTES = 16 * 1024  # auth and profile-write bodies are parsed by hand, so they are bounded by hand
MAX_ANSWERS = 32


def _envelope_response(envelope: Any) -> JSONResponse:
    payload = to_primitive(envelope)
    return JSONResponse(payload, status_code=_STATUS_CODES.get(payload.get("status"), 200))


def _found_response(envelope: Any, what: str) -> JSONResponse:
    """404 when the one thing the route names is not the caller's or does not exist; both answer alike (C04)."""
    payload = to_primitive(envelope)
    if payload.get("status") == "INSUFFICIENT_DATA" and payload.get("missing") == [what]:
        return JSONResponse(payload, status_code=404)
    return _envelope_response(envelope)


def _action_response(outcome: Any) -> JSONResponse:
    payload = to_primitive(outcome)
    payload["facts"] = to_primitive(outcome.facts())
    return JSONResponse(payload, status_code=_ACTION_CODES.get(outcome.status, 200))


def _link_response(outcome: Any, *, created: bool = True) -> JSONResponse:
    """contracts/investments/link_outcome: never the token, and the email masked (the use case's LinkView)."""
    payload = to_primitive(outcome)
    status_code = _LINK_CODES.get(payload["status"], 200)
    return JSONResponse(payload, status_code=200 if status_code == 201 and not created else status_code)


class SecurityHeadersMiddleware:
    """G09: every response says nosniff and no-store (the API serves financial data). Pure ASGI so streaming bodies are untouched."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"x-content-type-options", b"cache-control")]
                headers += [(b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store")]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _auth_error(status: str, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse(auth_error_body(status, message, field), status_code=AUTH_HTTP_STATUS[status])


def _invalid(field: str) -> JSONResponse:
    return _auth_error("INVALID_INPUT", "invalid input", field)


class _NoSession(Exception):
    """A route that needs the caller's session ran without one (the guard should have stopped it)."""


class _BadBody(Exception):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field  # a contract field name or "body"; never a value or a key the client sent


async def _json_object(request: Request) -> dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_JSON_BYTES:
            raise _BadBody("body")
    try:
        body = json.loads(bytes(raw)) if raw else None
    except (ValueError, RecursionError):
        raise _BadBody("body") from None
    if not isinstance(body, dict):
        raise _BadBody("body")
    return body


def _only(body: dict[str, Any], required: tuple[str, ...], optional: tuple[str, ...] = ()) -> None:
    if not set(body) <= set(required) | set(optional):
        raise _BadBody("body")
    for name in required:
        if name not in body:
            raise _BadBody(name)


def _text(body: dict[str, Any], name: str) -> str | None:
    if name not in body:
        return None
    value = body[name]
    if not isinstance(value, str):
        raise _BadBody(name)
    return value


def _session_body(issued: IssuedSession) -> dict[str, str]:
    """Field by field: the token goes only into Set-Cookie, never into JSON."""
    return {"user_id": issued.user_id, "expires_at": issued.expires_at.isoformat()}


def create_app(
    services: ApplicationServices,
    *,
    cors_origins: tuple[str, ...] = (),
    rate_limits: tuple[Limit, ...] = DEFAULT_LIMITS,
    rate_clock: Callable[[], float] = time.monotonic,  # not the services' clock: a fixed demo clock would never reopen a window
) -> FastAPI:
    app = FastAPI(title="Neural Ledger API", version="0.1.0", description="Contracts: see /contracts in the repository.")
    auth = services.auth
    accounts = services.accounts
    if auth.accounts:
        if accounts is None:
            raise ValueError("accounts mode needs AccountUseCases")
        app.add_middleware(IdentityGuard, resolve=accounts.resolve, origins=auth.app_origins)
    # Inside CORS, so a browser can read a 429 and its Retry-After; outside the guard, so it counts before any session lookup.
    if rate_limits:
        app.add_middleware(RateLimitMiddleware, limits=rate_limits, now=rate_clock)
    # Outside the guard: preflights are answered and guard rejections still carry CORS headers.
    # No credentials: the web UI reaches the API on its own origin (nginx /api), never cross-site with cookies.
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(SecurityHeadersMiddleware)  # G09: added after CORS, so it wraps CORS, the guard and every response

    @app.exception_handler(_NoSession)
    async def no_session(request: Request, exc: _NoSession) -> JSONResponse:
        return _auth_error("UNAUTHENTICATED", "sign in required")

    @app.exception_handler(_BadBody)
    async def bad_body(request: Request, exc: _BadBody) -> JSONResponse:
        return _invalid(exc.field)

    def session(request: Request) -> Session:
        current = request.scope.get(SESSION_KEY)
        if not isinstance(current, Session):
            raise _NoSession()
        return current

    def user(request: Request) -> str:
        if auth.accounts:
            return session(request).user_id  # the session only: never a header, never default_user
        return request.headers.get("x-user-id") or services.default_user

    def actor(session_id: str, request: Request) -> ActorContext:
        return ActorContext(session_id=session_id, user_id=user(request), actor=Actor.USER)

    def secure(request: Request) -> bool:
        return secure_cookie(auth.cookie_secure, request.url.scheme, request.headers.get("x-forwarded-proto"))

    def issued(outcome: AccountOutcome, request: Request, status_code: int) -> JSONResponse:
        if outcome.ok and outcome.session is not None:
            response = JSONResponse(_session_body(outcome.session), status_code=status_code)
            now = services.clock.now() if services.clock else outcome.session.expires_at
            response.headers.append("set-cookie", session_cookie(outcome.session.token, outcome.session.expires_at, now, secure(request)))
            return response
        if outcome.status is AccountStatus.EMAIL_TAKEN:
            return _auth_error("EMAIL_TAKEN", "email already registered", "email")
        if outcome.status is AccountStatus.INVALID_INPUT:
            return _auth_error("INVALID_INPUT", outcome.message or "invalid input", outcome.field or "body")
        return _auth_error("INVALID_CREDENTIALS", "invalid credentials")

    def not_found() -> JSONResponse:
        return _auth_error("NOT_FOUND", "not found")

    def read_only() -> JSONResponse:
        return _auth_error("PROFILE_READ_ONLY", "this profile is read-only")

    @app.get("/health")
    def health() -> dict[str, Any]:
        check = services.audit.verify()
        return {
            "status": "ok",
            "mode": services.mode,
            "auth": auth.mode,
            "demo_personas": list(auth.demo_personas),
            "language_model": services.language_model,
            "decision_chain": list(services.decision_chain),
            "pii_detector": services.pii_detector,
            "classifier": services.classifier,
            "investments": services.investments.adapter,
            "connectors": services.connections.mode if services.connections else "off",
            "params_version": services.financial.params.version,
            "audit_chain_ok": check.ok,
            "tools": list(services.registry.names),
            # The API's own clock (fixed in recorded demos), so UI countdowns use the same time as expires_at.
            "server_time": services.clock.now().isoformat() if services.clock else None,
        }

    # ---- accounts: sign-up, sign-in, sessions (accounts mode only; HTTP only, no agent tool) -------

    @app.post("/v1/auth/signup")
    async def signup(request: Request):
        if accounts is None:
            return not_found()
        body = await _json_object(request)
        _only(body, ("email", "password", "display_name", "sandbox_acknowledged"), ("language",))
        if body["sandbox_acknowledged"] is not True:  # the sandbox notice, ticked in the form; checked here, not only in the UI
            raise _BadBody("sandbox_acknowledged")
        email, password, display_name = _text(body, "email"), _text(body, "password"), _text(body, "display_name")
        language = _text(body, "language")
        if language is None:
            language = "en"
        outcome = await run_in_threadpool(accounts.signup, email, password, display_name, language, sandbox_notice=SANDBOX_NOTICE)
        return issued(outcome, request, 201)

    @app.post("/v1/auth/signin")
    async def signin(request: Request):
        if accounts is None:
            return not_found()
        body = await _json_object(request)
        _only(body, ("email", "password"))
        outcome = await run_in_threadpool(accounts.signin, _text(body, "email"), _text(body, "password"))
        return issued(outcome, request, 200)

    @app.post("/v1/auth/demo-session")
    async def demo_session(request: Request):
        if accounts is None or not accounts.demo_personas:
            return not_found()
        body = await _json_object(request)
        _only(body, ("persona",))
        persona = body["persona"]
        outcome = await run_in_threadpool(accounts.start_demo_session, persona if isinstance(persona, str) else "")
        return issued(outcome, request, 200)

    @app.post("/v1/auth/signout")
    async def signout(request: Request):
        if accounts is None:
            return not_found()
        session(request)
        token = session_token(request.scope.get("headers") or [])
        closed = await run_in_threadpool(accounts.signout, token or "")
        response = Response(status_code=204) if closed else _auth_error("UNAUTHENTICATED", "sign in required")
        response.headers.append("set-cookie", cleared_cookie(secure(request)))
        return response

    @app.delete("/v1/account")
    async def delete_account(request: Request):
        """G03 (Ley 21.719 art. 7): the signed-in account and everything it owns, or a demo persona's reset.
        An account sends its password and confirm=DELETE (or its email); a persona sends confirm=RESET."""
        if accounts is None:
            return not_found()
        current = session(request)
        body = await _json_object(request)
        _only(body, ("confirm",), ("password",))
        outcome = await run_in_threadpool(accounts.delete_account, current, _text(body, "password"), _text(body, "confirm"))
        if outcome.status in (AccountStatus.DELETED, AccountStatus.RESET) and outcome.erased is not None:
            response = JSONResponse({
                "status": outcome.status.value, "erased": dict(outcome.erased.counts), "audit_events_erased": outcome.erased.erased_events,
            })
            if outcome.status is AccountStatus.DELETED:
                response.headers.append("set-cookie", cleared_cookie(secure(request)))  # its session row is gone too
            return response
        if outcome.status is AccountStatus.INVALID_INPUT:
            return _auth_error("INVALID_INPUT", outcome.message or "invalid input", outcome.field or "body")
        if outcome.status is AccountStatus.INVALID_CREDENTIALS:
            return _auth_error("INVALID_CREDENTIALS", "invalid credentials")
        return not_found()

    @app.get("/v1/me")
    def me(request: Request):
        if accounts is None:
            return not_found()
        current = session(request)
        return JSONResponse({
            "user_id": current.user_id,
            "data_source": accounts.data_source(current.user_id),
            "expires_at": current.expires_at.isoformat(),
        })

    @app.get("/v1/me/export")
    def export_data(request: Request):
        """G02 (Ley 21.719 arts. 5 and 9): a copy of everything stored about the signed-in user, as a JSON download."""
        if accounts is None or services.data_export is None:
            return not_found()
        current = session(request)
        body = services.data_export.export(current.user_id, current.session_ref)
        name = f"neural-ledger-data-{body['exported_at'][:10]}.json"
        return JSONResponse(body, headers={"content-disposition": f'attachment; filename="{name}"'})

    # ---- financial reads (T0/T1) --------------------------------------------------------------

    @app.get("/v1/state")
    def state(request: Request):
        return _envelope_response(services.financial.financial_state(user(request)))

    @app.get("/v1/commitments")
    def commitments(request: Request, horizon_months: int = Query(6)):
        return _envelope_response(services.financial.commitments(user(request), horizon_months))

    @app.get("/v1/forecast")
    def forecast(
        request: Request,
        horizon_months: int = Query(6),
        scenario: str = Query("conservative"),
        include_plan: str = Query("none"),
    ):
        return _envelope_response(services.financial.forecast(user(request), horizon_months, scenario, include_plan))

    @app.post("/v1/simulate-purchase")
    def simulate(request: Request, body: dict[str, Any] = Body(...)):
        return _envelope_response(
            services.financial.simulate_purchase(
                user(request),
                body.get("amount"),
                body.get("installments"),
                body.get("first_installment_month"),
                body.get("monthly_rate"),
                body.get("include_plan", "none"),
            )
        )

    @app.get("/v1/protected-surplus")
    def surplus(request: Request, horizon_months: int = Query(6), include_plan: str = Query("none")):
        return _envelope_response(services.financial.protected_surplus(user(request), horizon_months, include_plan))

    @app.get("/v1/capacity")
    def capacity(request: Request):
        return _envelope_response(services.financial.capacity(user(request)))

    @app.get("/v1/profile")
    def profile(request: Request):
        return _envelope_response(services.profiles.user_profile(user(request)))

    @app.get("/v1/profile/questionnaire")
    def questionnaire():
        return _envelope_response(services.profiles.questionnaire())

    # ---- profile writes: the user only, own writable record only, atomic with the audit ---------

    def writable(request: Request) -> Session | None:
        """The caller's session when its profile can be written: an account, never a persona or demo mode."""
        if accounts is None or services.profile_editing is None:
            return None
        current = session(request)
        return current if accounts.data_source(current.user_id) != "persona" else None

    @app.put("/v1/profile")
    async def update_profile(request: Request):
        current = await run_in_threadpool(writable, request)
        if current is None or services.profile_editing is None:
            return read_only()
        body = await _json_object(request)
        _only(body, (), ("display_name", "language"))
        if not body:
            raise _BadBody("body")
        display_name, language = _text(body, "display_name"), _text(body, "language")
        result = await run_in_threadpool(
            services.profile_editing.update_profile, current.user_id, current.session_ref, display_name=display_name, language=language
        )
        return _envelope_response(result)

    @app.post("/v1/profile/questionnaire")
    async def submit_questionnaire(request: Request):
        current = await run_in_threadpool(writable, request)
        if current is None or services.profile_editing is None:
            return read_only()
        body = await _json_object(request)
        _only(body, ("version", "answers"))
        version, answers = _text(body, "version"), body["answers"]
        if not isinstance(answers, list) or len(answers) > MAX_ANSWERS:
            raise _BadBody("answers")
        parsed = []
        for answer in answers:
            if not isinstance(answer, dict) or set(answer) != {"question_id", "option_id"}:
                raise _BadBody("answers")
            if not isinstance(answer["question_id"], str) or not isinstance(answer["option_id"], str):
                raise _BadBody("answers")
            parsed.append(QuestionnaireAnswer(answer["question_id"], answer["option_id"]))
        result = await run_in_threadpool(
            services.profile_editing.submit_questionnaire, current.user_id, current.session_ref, version, tuple(parsed)
        )
        return _envelope_response(result)

    @app.post("/v1/permitted-profile")
    def permitted(request: Request, body: dict[str, Any] = Body(...)):
        return _envelope_response(services.financial.permitted_profile(user(request), str(body.get("tolerance", ""))))

    @app.post("/v1/savings-plan")
    def savings_plan(request: Request, body: dict[str, Any] = Body(default={})):
        return _envelope_response(services.financial.savings_plan(user(request), body.get("permitted_profile")))

    # ---- chat ---------------------------------------------------------------------------------

    @app.post("/v1/chat")
    def chat(request: Request, body: dict[str, Any] = Body(...)):
        reply = services.chat.handle(str(body.get("session_id") or "default"), user(request), str(body.get("message", "")))
        return JSONResponse(to_primitive(reply))

    # ---- actions: the confirmation contract -----------------------------------------------------

    @app.post("/v1/actions/proposals")
    def propose(request: Request, body: dict[str, Any] = Body(...)):
        ctx = actor(str(body.get("session_id") or "default"), request)
        return _action_response(services.actions.propose_savings_rule(ctx, str(body.get("plan_snapshot_id", ""))))

    @app.post("/v1/actions/proposals/{proposal_id}/confirm")
    def confirm(proposal_id: str, request: Request, body: dict[str, Any] = Body(...)):
        """The ONLY way to create an authorization: the user confirms the exact terms shown."""
        ctx = actor(str(body.get("session_id") or "default"), request)
        return _action_response(services.actions.confirm(ctx, proposal_id, body.get("terms") or {}))

    @app.post("/v1/actions/execute")
    def execute(request: Request, body: dict[str, Any] = Body(...)):
        ctx = actor(str(body.get("session_id") or "default"), request)
        return _action_response(services.actions.execute(ctx, str(body.get("authorization_id", "")), body.get("requested_terms")))

    @app.get("/v1/actions/pending")
    def pending(request: Request, session_id: str = Query("default")):
        return JSONResponse(to_primitive(services.actions.pending(actor(session_id, request))))

    # ---- bank statements ----------------------------------------------------------------------

    @app.post("/v1/statements")
    async def import_statement(request: Request):
        """The raw file is the body: an .xlsx export, a PDF or an image (the bytes decide, not the
        Content-Type). Reading a scan runs OCR, which takes seconds to minutes, so it runs off the event loop."""
        too_large = JSONResponse({"detail": "the file is larger than 15 MB"}, status_code=413)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_STATEMENT_BYTES:
            return too_large
        owner = user(request)
        # Count while reading: a chunked upload has no Content-Length, so the check above cannot see it.
        content = bytearray()
        async for chunk in request.stream():
            content += chunk
            if len(content) > MAX_STATEMENT_BYTES:
                return too_large
        result = await run_in_threadpool(services.statements.import_statement, owner, bytes(content))
        return _envelope_response(result)

    @app.post("/v1/documents")
    async def ingest_document(request: Request, session_id: str = Query("documents"), kind: str | None = Query(None)):
        """A file dropped on the copilot (ADR-039): a statement, a receipt or an investment document (ADR-044, from a
        signed-in account only), decided by the server, never the Content-Type or the file name. Same size limit and
        threadpool as a statement import."""
        too_large = JSONResponse({"detail": "the file is larger than 15 MB"}, status_code=413)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_STATEMENT_BYTES:
            return too_large
        owner = user(request)
        content = bytearray()
        async for chunk in request.stream():
            content += chunk
            if len(content) > MAX_STATEMENT_BYTES:
                return too_large
        private = await run_in_threadpool(linkable, request) is not None  # never a demo persona that visitors share
        result = await run_in_threadpool(
            lambda: _documents().ingest(owner, bytes(content), session_id[:120] or "documents", kind, investments=private)
        )
        return _envelope_response(result)

    @app.get("/v1/receipts")
    def receipts(request: Request):
        return _envelope_response(_documents().list_receipts(user(request)))

    @app.patch("/v1/receipts/{receipt_id}")
    def correct_receipt(receipt_id: str, request: Request, body: dict[str, Any] = Body(...)):
        """The user's correction of a receipt's total or date (contracts/receipts/receipt_correction). Only the user
        corrects: no agent tool reaches this route."""
        session = str(body.get("session_id") or "documents")[:120]
        result = _documents().correct_receipt(user(request), session, receipt_id, body.get("total"), body.get("issued_on"))
        return _found_response(result, "receipt")

    @app.post("/v1/expenses/{proposal_id}/confirm")
    def confirm_expense(proposal_id: str, request: Request, body: dict[str, Any] = Body(...)):
        """The user confirms an expense the copilot prepared (contracts/expenses/expense_confirmation). Only the user."""
        session = str(body.get("session_id") or "documents")[:120]
        result = _documents().confirm_expense(user(request), session, proposal_id, body.get("payment"), body.get("category"), body.get("spent_on"))
        return _found_response(result, "expense")

    @app.get("/v1/spending")
    def spending(request: Request):
        """The spending check-in the copilot's get_spending_status tool reads (T0)."""
        return _envelope_response(_documents().spending_status(user(request)))

    # ---- read-only connections (ADR-047): every route is the user's; the agent only reads /data's content ----------

    @app.get("/v1/connections")
    def connections(request: Request):
        return _envelope_response(_connections().list(user(request)))

    @app.get("/v1/connections/data")
    def connected_data(request: Request):
        """What the copilot's get_connected_data tool reads (T0): the last sync's answers, untrusted."""
        return _envelope_response(_connections().connected_data(user(request)))

    @app.post("/v1/connections")
    def add_connection(request: Request, body: dict[str, Any] = Body(...)):
        """Add an MCP server (contracts/connections/connection_create). The token is never echoed."""
        session = str(body.get("session_id") or "connections")[:120]
        result = _connections().add_mcp(user(request), session, body.get("name"), body.get("url"), body.get("token"), body.get("consent"))
        return _envelope_response(result)

    @app.post("/v1/connections/bank/start")
    def start_bank(request: Request):
        """A one-time widget token for the bank aggregator; null in fixture mode."""
        return _envelope_response(_connections().bank_start(user(request)))

    @app.post("/v1/connections/bank")
    def connect_bank(request: Request, body: dict[str, Any] = Body(...)):
        """Connect the user's bank with the widget's exchange token (contracts/connections/bank_exchange)."""
        session = str(body.get("session_id") or "connections")[:120]
        return _envelope_response(_connections().connect_bank(user(request), session, body.get("exchange_token"), body.get("consent")))

    @app.put("/v1/connections/{connection_id}/tools")
    def set_connection_tools(connection_id: str, request: Request, body: dict[str, Any] = Body(...)):
        session = str(body.get("session_id") or "connections")[:120]
        return _found_response(_connections().set_tools(user(request), session, connection_id, body.get("enabled")), "connection")

    @app.post("/v1/connections/{connection_id}/sync")
    def sync_connection(connection_id: str, request: Request, session_id: str = Query("connections")):
        """Only the user syncs: no agent tool reaches a connected service."""
        return _found_response(_connections().sync(user(request), session_id[:120], connection_id), "connection")

    @app.delete("/v1/connections/{connection_id}")
    def remove_connection(connection_id: str, request: Request, session_id: str = Query("connections")):
        return _found_response(_connections().remove(user(request), session_id[:120], connection_id), "connection")

    def _connections():
        if services.connections is None:
            raise HTTPException(status_code=503, detail="connections are not configured")
        return services.connections

    def _documents():
        if services.documents is None:
            raise HTTPException(status_code=503, detail="documents are not configured")
        return services.documents

    @app.get("/v1/statements")
    def statements(request: Request):
        return _envelope_response(services.statements.list_statements(user(request)))

    @app.get("/v1/statements/{statement_id}")
    def statement(statement_id: str, request: Request):
        return _found_response(services.statements.get_statement(user(request), statement_id), "statement")

    @app.get("/v1/transactions")
    def transactions(request: Request):
        """The transaction ledger built from verified imported statements, with spend per category."""
        return _envelope_response(services.ledger.list_transactions(user(request)))

    @app.patch("/v1/transactions/{txn_id}")
    def set_category(txn_id: str, request: Request, body: dict[str, Any] = Body(...)):
        """ADR-023, G04: the user sets a transaction's category. The UI path only: no agent tool reaches it."""
        category = body.get("category")
        category = category if isinstance(category, str) else ""  # not a category: INVALID_INPUT with the allowed ones
        session_id = str(body.get("session_id") or "default")
        return _found_response(services.ledger.set_category(user(request), session_id, txn_id, category), "transaction")

    # ---- investments: an account linked at a provider (ADR-044) ---------------------------------
    # Reading works in every mode; linking, syncing and unlinking are user-only flows of a real account (never a demo
    # persona or demo mode), never agent tools, and each commits with its audit event.

    def linkable(request: Request) -> Session | None:
        """The caller's session when it may link an investment account: an account, never a persona or demo mode."""
        if accounts is None:
            return None
        current = session(request)
        return current if accounts.data_source(current.user_id) != "persona" else None

    def read_only_link() -> JSONResponse:
        body = {"status": "READ_ONLY", "link": None, "field": None, "message": "investment accounts are linked from a signed-in account"}
        return JSONResponse(body, status_code=403)

    @app.get("/v1/investments")
    def investments(request: Request):
        return _envelope_response(services.investments.overview(user(request)))

    @app.get("/v1/investments/link")
    def investment_link(request: Request):
        return _link_response(services.investments.status(user(request)), created=False)

    @app.post("/v1/investments/link")
    async def link_investments(request: Request):
        current = await run_in_threadpool(linkable, request)
        if current is None:
            return read_only_link()
        body = await _json_object(request)
        _only(body, ("email", "password", "consent"), ("provider",))
        if body.get("provider", services.investments.provider) != services.investments.provider:
            raise _BadBody("provider")
        email, password = _text(body, "email"), _text(body, "password")
        outcome = await run_in_threadpool(
            services.investments.link, current.user_id, current.session_ref, email, password, consent=body["consent"] is True
        )
        return _link_response(outcome)

    @app.post("/v1/investments/sync")
    async def sync_investments(request: Request):
        current = await run_in_threadpool(linkable, request)
        if current is None:
            return read_only_link()
        return _link_response(await run_in_threadpool(services.investments.sync, current.user_id, current.session_ref))

    @app.delete("/v1/investments/link")
    async def unlink_investments(request: Request):
        current = await run_in_threadpool(linkable, request)
        if current is None:
            return read_only_link()
        return _link_response(await run_in_threadpool(services.investments.unlink, current.user_id, current.session_ref))

    @app.delete("/v1/investments/documents")
    async def remove_investment_documents(request: Request):
        """Forget every imported investment document of the account (they are imported through POST /v1/documents)."""
        current = await run_in_threadpool(linkable, request)
        if current is None:
            return read_only_link()
        removed = await run_in_threadpool(services.investments.remove_documents, current.user_id, current.session_ref)
        return JSONResponse({"removed": removed})

    # ---- audit --------------------------------------------------------------------------------

    @app.get("/v1/audit")
    def audit(request: Request, session_id: str | None = Query(None), limit: int = Query(200)):
        """The caller's own events only. The chain status covers the whole log (no contents leak)."""
        return JSONResponse(to_primitive(services.audit.events(user(request), session_id, limit)))

    @app.get("/v1/audit/verify")
    def audit_verify():
        return JSONResponse(to_primitive(services.audit.verify()))

    return app
