"""HTTP adapter (FastAPI). The ONLY module that imports FastAPI.

Thin by design: parse the request, call one use case, serialize with to_primitive. No money
math and no permission logic here. The user is identified by the X-User-Id header (sandbox
only; real authentication is out of scope and listed in docs/SECURITY.md).
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ....application.facade import ApplicationServices
from ....application.use_cases.actions import ActorContext
from ....application.use_cases.statements import MAX_STATEMENT_BYTES
from ....domain.audit.events import Actor
from ....domain.shared.serialization import to_primitive

_STATUS_CODES = {"OK": 200, "INVALID_INPUT": 422, "INSUFFICIENT_DATA": 409}
_ACTION_CODES = {"PROPOSED": 201, "CONFIRMED": 201, "EXECUTED": 200, "FAILED": 502, "BLOCKED": 403, "INVALID_INPUT": 422, "INSUFFICIENT_DATA": 409}


def _envelope_response(envelope: Any) -> JSONResponse:
    payload = to_primitive(envelope)
    return JSONResponse(payload, status_code=_STATUS_CODES.get(payload.get("status"), 200))


def _action_response(outcome: Any) -> JSONResponse:
    payload = to_primitive(outcome)
    payload["facts"] = to_primitive(outcome.facts())
    return JSONResponse(payload, status_code=_ACTION_CODES.get(outcome.status, 200))


def create_app(services: ApplicationServices, *, cors_origins: tuple[str, ...] = ("*",)) -> FastAPI:
    app = FastAPI(title="Neural Ledger API", version="0.1.0", description="Contracts: see /contracts in the repository.")
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"], allow_headers=["*"])

    def user(x_user_id: str | None) -> str:
        return x_user_id or services.default_user

    def actor(session_id: str, x_user_id: str | None) -> ActorContext:
        return ActorContext(session_id=session_id, user_id=user(x_user_id), actor=Actor.USER)

    @app.get("/health")
    def health() -> dict[str, Any]:
        check = services.audit.verify()
        return {
            "status": "ok",
            "mode": services.mode,
            "language_model": services.language_model,
            "decision_chain": list(services.decision_chain),
            "params_version": services.financial.params.version,
            "audit_chain_ok": check.ok,
            "tools": list(services.registry.names),
        }

    # ---- financial reads (T0/T1) --------------------------------------------------------------

    @app.get("/v1/state")
    def state(x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.financial.financial_state(user(x_user_id)))

    @app.get("/v1/commitments")
    def commitments(horizon_months: int = Query(6), x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.financial.commitments(user(x_user_id), horizon_months))

    @app.get("/v1/forecast")
    def forecast(
        horizon_months: int = Query(6),
        scenario: str = Query("conservative"),
        include_plan: str = Query("none"),
        x_user_id: str | None = Header(default=None),
    ):
        return _envelope_response(services.financial.forecast(user(x_user_id), horizon_months, scenario, include_plan))

    @app.post("/v1/simulate-purchase")
    def simulate(body: dict[str, Any] = Body(...), x_user_id: str | None = Header(default=None)):
        return _envelope_response(
            services.financial.simulate_purchase(
                user(x_user_id),
                body.get("amount"),
                body.get("installments"),
                body.get("first_installment_month"),
                body.get("monthly_rate"),
                body.get("include_plan", "none"),
            )
        )

    @app.get("/v1/protected-surplus")
    def surplus(horizon_months: int = Query(6), include_plan: str = Query("none"), x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.financial.protected_surplus(user(x_user_id), horizon_months, include_plan))

    @app.get("/v1/capacity")
    def capacity(x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.financial.capacity(user(x_user_id)))

    @app.post("/v1/permitted-profile")
    def permitted(body: dict[str, Any] = Body(...), x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.financial.permitted_profile(user(x_user_id), str(body.get("tolerance", ""))))

    @app.post("/v1/savings-plan")
    def savings_plan(body: dict[str, Any] = Body(default={}), x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.financial.savings_plan(user(x_user_id), body.get("permitted_profile")))

    # ---- chat ---------------------------------------------------------------------------------

    @app.post("/v1/chat")
    def chat(body: dict[str, Any] = Body(...), x_user_id: str | None = Header(default=None)):
        reply = services.chat.handle(str(body.get("session_id") or "default"), user(x_user_id), str(body.get("message", "")))
        return JSONResponse(to_primitive(reply))

    # ---- actions: the confirmation contract -----------------------------------------------------

    @app.post("/v1/actions/proposals")
    def propose(body: dict[str, Any] = Body(...), x_user_id: str | None = Header(default=None)):
        ctx = actor(str(body.get("session_id") or "default"), x_user_id)
        return _action_response(services.actions.propose_savings_rule(ctx, str(body.get("plan_snapshot_id", ""))))

    @app.post("/v1/actions/proposals/{proposal_id}/confirm")
    def confirm(proposal_id: str, body: dict[str, Any] = Body(...), x_user_id: str | None = Header(default=None)):
        """The ONLY way to create an authorization: the user confirms the exact terms shown."""
        ctx = actor(str(body.get("session_id") or "default"), x_user_id)
        return _action_response(services.actions.confirm(ctx, proposal_id, body.get("terms") or {}))

    @app.post("/v1/actions/execute")
    def execute(body: dict[str, Any] = Body(...), x_user_id: str | None = Header(default=None)):
        ctx = actor(str(body.get("session_id") or "default"), x_user_id)
        return _action_response(services.actions.execute(ctx, str(body.get("authorization_id", "")), body.get("requested_terms")))

    @app.get("/v1/actions/pending")
    def pending(session_id: str = Query("default"), x_user_id: str | None = Header(default=None)):
        return JSONResponse(to_primitive(services.actions.pending(actor(session_id, x_user_id))))

    # ---- bank statements ----------------------------------------------------------------------

    @app.post("/v1/statements")
    async def import_statement(request: Request, x_user_id: str | None = Header(default=None)):
        """The raw file is the body (Content-Type application/pdf or image/*). Reading a scan runs OCR,
        which takes seconds to minutes, so it runs off the event loop."""
        too_large = JSONResponse({"detail": "the file is larger than 15 MB"}, status_code=413)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_STATEMENT_BYTES:
            return too_large
        # Count while reading: a chunked upload has no Content-Length, so the check above cannot see it.
        content = bytearray()
        async for chunk in request.stream():
            content += chunk
            if len(content) > MAX_STATEMENT_BYTES:
                return too_large
        result = await run_in_threadpool(services.statements.import_statement, user(x_user_id), bytes(content))
        return _envelope_response(result)

    @app.get("/v1/statements")
    def statements(x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.statements.list_statements(user(x_user_id)))

    @app.get("/v1/statements/{statement_id}")
    def statement(statement_id: str, x_user_id: str | None = Header(default=None)):
        return _envelope_response(services.statements.get_statement(user(x_user_id), statement_id))

    @app.get("/v1/transactions")
    def transactions(x_user_id: str | None = Header(default=None)):
        """The transaction ledger built from verified imported statements, with spend per category."""
        return _envelope_response(services.ledger.list_transactions(user(x_user_id)))

    # ---- audit --------------------------------------------------------------------------------

    @app.get("/v1/audit")
    def audit(session_id: str | None = Query(None), limit: int = Query(200), x_user_id: str | None = Header(default=None)):
        """The caller's own events only. The chain status covers the whole log (no contents leak)."""
        return JSONResponse(to_primitive(services.audit.events(user(x_user_id), session_id, limit)))

    @app.get("/v1/audit/verify")
    def audit_verify():
        return JSONResponse(to_primitive(services.audit.verify()))

    return app
