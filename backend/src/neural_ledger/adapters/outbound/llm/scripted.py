"""Scripted language model: deterministic, offline. Plans tool calls from the intent the
application already classified, then narrates the results with the deterministic narrator.

It is the fallback when the real provider is down (S10), the engine of CI tests and the safest
way to record the demo video. It is NOT smart: real conversation needs a real provider.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ....application.conversation import (
    AssistantEntry,
    ModelRequest,
    ModelTurn,
    ToolCall,
    ToolResultEntry,
    UserEntry,
    entries_since_last_user,
    last_user_text,
)
from ....application.services import narration
from ..text.lexicon import installments, language_of, mentioned_month, money_amounts

MAX_CONCEPT_QUERY = 300  # contracts/tools/search_financial_concepts.input.schema.json

ASK_PURCHASE = "Tell me the price and how many cuotas you want, and I'll check it against your forecast."
ASK_EXPENSE = "How much did you spend, and on what? I'll prepare it for you to confirm."
ASK_FLOOR = "Tell me the minimum balance you want your checking account to keep every month, and I'll prepare the rule."
NOTHING_TO_EXECUTE = "There is no confirmed action to execute yet. Please confirm the proposal in the app first."
NO_BYPASS = "I can't skip the conservative check, but here is what does fit."
# "I just added a receipt", "subí una boleta", "acabo de agregar un documento": the copilot first reads what happened to it.
# Another app the user connected (ADR-047): read it whatever the intent; nothing here can call that app. Fintual is
# not listed: its statements and linked account are read by get_investments (ADR-044).
CONNECTED = re.compile(r"\b(portafolio|portfolio|racional|connected|conectad\w*|mis metas|my goals)\b", re.I)
ADDED_DOCUMENT = re.compile(r"\b(added|uploaded|agregu\w*|agregar|sub[ií]\w*|cargu\w*|document\w*|receipts?|boletas?|statements?|cartolas?)\b", re.I)


class ScriptedLanguageModel:
    name = "scripted-0.1"

    def respond(self, request: ModelRequest) -> ModelTurn:
        turn = entries_since_last_user(request.entries)
        results = [e for e in turn if isinstance(e, ToolResultEntry)]
        call = None
        if all(r.payload.get("status") in ("OK", "PROPOSED") for r in results):
            call = self._next_call(request, {r.name: r.payload for r in results}, len(results))
        available = {t.name for t in request.tools}
        if call is not None and call.name in available:
            return ModelTurn(None, (call,), self.name)
        return ModelTurn(self._text(request, results), (), self.name)

    # ---- planning -----------------------------------------------------------------------------

    def _next_call(self, request: ModelRequest, done: dict[str, Any], n: int) -> ToolCall | None:
        intent = request.context.intent
        text = last_user_text(request.entries)

        def call(name: str, **arguments: Any) -> ToolCall:
            return ToolCall(f"call_{n + 1}", name, arguments)

        if intent == "explain" and "search_financial_concepts" not in done and text.strip():
            return call("search_financial_concepts", query=text.strip()[:MAX_CONCEPT_QUERY], lang=language_of(text), k=3)
        if CONNECTED.search(text) and "get_connected_data" not in done:
            return call("get_connected_data")
        if intent == "afford_purchase" and "simulate_purchase" not in done:
            args = _purchase_args(text, request.context.as_of) or _previous_purchase_args(request)
            return call("simulate_purchase", **args) if args else None
        if intent == "log_expense" and "propose_expense" not in done:
            amounts = _recent_amounts(request)
            if not amounts:
                return None
            return call("propose_expense", amount=amounts[0], description=_recent_description(request))
        if intent == "spending_check":
            if ADDED_DOCUMENT.search(text) and "get_latest_document" not in done:
                return call("get_latest_document")
            if "get_spending_status" not in done:
                return call("get_spending_status")
        if intent == "forecast" and "forecast_cashflow" not in done:
            return call("forecast_cashflow", horizon_months=6, scenario="conservative")
        if intent == "investments" and "get_investments" not in done:
            return call("get_investments")
        if intent == "protected_surplus":
            if "compute_protected_surplus" not in done:
                return call("compute_protected_surplus", horizon_months=6, include_plan="none")
            if "assess_financial_capacity" not in done:
                return call("assess_financial_capacity")
        if intent == "savings_plan":
            if "assess_risk_tolerance" not in done:
                return call("assess_risk_tolerance")
            if "derive_permitted_profile" not in done:
                return call("derive_permitted_profile", tolerance=done["assess_risk_tolerance"]["data"]["tolerance"])
            if "compute_savings_plan" not in done:
                return call("compute_savings_plan", permitted_profile=done["derive_permitted_profile"]["data"]["permitted"])
            plan = done["compute_savings_plan"]
            if plan["data"]["amount"] > 0 and "propose_savings_rule" not in done:
                return call("propose_savings_rule", plan_snapshot_id=plan["snapshot_id"])
        if intent == "set_liquidity_floor" and "propose_liquidity_floor" not in done:
            amounts = money_amounts(text)
            return call("propose_liquidity_floor", amount=amounts[0]) if amounts else None
        if intent == "execute_action":
            if "get_pending_actions" not in done:
                return call("get_pending_actions")
            authorizations = done["get_pending_actions"]["data"]["authorizations"]
            if authorizations and "execute_sandbox_action" not in done:
                latest = authorizations[-1]
                amounts = money_amounts(text)
                requested = None
                if amounts and amounts[0] != latest["terms"]["amount"]:
                    requested = {**latest["terms"], "amount": amounts[0]}
                return call("execute_sandbox_action", authorization_id=latest["authorization_id"], requested_terms=requested)
        return None

    # ---- text ---------------------------------------------------------------------------------

    def _text(self, request: ModelRequest, results: list[ToolResultEntry]) -> str:
        intent = request.context.intent
        if intent == "execute_action" and [r.name for r in results] == ["get_pending_actions"]:
            return NOTHING_TO_EXECUTE
        if intent == "explain" and [r.name for r in results] == ["search_financial_concepts"] and results[0].payload.get("status") == "INSUFFICIENT_DATA":
            unavailable = "knowledge_base" in results[0].payload.get("missing", ())
            return narration.no_concept_card(language_of(last_user_text(request.entries)), unavailable)
        if len(results) > 1:
            results = [r for r in results if r.name != "get_pending_actions"]
        if results:
            text = narration.narrate([(r.name, r.payload) for r in results], request.context.currency)
            follow_up = intent == "afford_purchase" and not _purchase_args(last_user_text(request.entries), request.context.as_of)
            return f"{NO_BYPASS} {text}" if follow_up else text
        if intent == "afford_purchase":
            return ASK_PURCHASE
        if intent == "set_liquidity_floor":
            return ASK_FLOOR
        if intent == "log_expense":
            return ASK_EXPENSE
        if intent == "explain":
            return narration.no_concept_card(language_of(last_user_text(request.entries)))
        if intent == "out_of_scope":
            return narration.REFUSAL_SCOPE
        return narration.GREETING


def _purchase_args(text: str, as_of: str) -> dict[str, Any] | None:
    amounts = money_amounts(text)
    count = installments(text)
    if not amounts or count is None:
        return None
    args: dict[str, Any] = {"amount": amounts[0], "installments": count}
    try:
        reference = date.fromisoformat(as_of)
    except ValueError:
        reference = None
    month = mentioned_month(text, reference)
    if month:
        args["first_installment_month"] = str(month)
    return args


def _previous_purchase_args(request: ModelRequest) -> dict[str, Any] | None:
    for entry in reversed(request.entries):
        if isinstance(entry, AssistantEntry):
            for c in entry.tool_calls:
                if c.name == "simulate_purchase":
                    return dict(c.arguments)
    return None


def _recent_user_texts(request: ModelRequest, last: int = 4) -> list[str]:
    """The user's last messages, newest first: an expense may be said over two turns ("gasté 15 lucas" / "efectivo")."""
    return [e.text for e in reversed(request.entries) if isinstance(e, UserEntry)][:last]


def _recent_amounts(request: ModelRequest) -> list[int]:
    for text in _recent_user_texts(request):
        found = money_amounts(text)
        if found:
            return found
    return []


def _recent_description(request: ModelRequest) -> str:
    for text in _recent_user_texts(request):
        if money_amounts(text):
            return text[:120]
    return ""
