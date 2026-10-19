"""ADR-037: the copilot proposes the user's own liquidity floor, and once confirmed and executed every engine uses it.

Offline and deterministic: the rules decision model and the scripted language model, as in the demo.
"""

from __future__ import annotations

import pytest

from neural_ledger.domain.shared.serialization import to_primitive
from tests.security.helpers import ScriptedFakeLLM, agent_ctx, audit_kinds, call, chat_with, say, user_ctx

USER = "camila"


def _facts(envelope) -> dict:
    return {f.key: (f.value, f.derivation) for f in envelope.facts}


@pytest.mark.parametrize("message", ["Quiero que el piso sea de 100.000", "Quiero poner una regla de piso de 100.000"])
def test_the_copilot_proposes_the_floor_the_user_asks_for(services, message):
    reply = services.chat.handle("s-floor", USER, message)

    assert (reply.intent, reply.gate) == ("set_liquidity_floor", "proceed")
    assert reply.tools_called == ("propose_liquidity_floor",)
    proposal = reply.pending_proposal
    assert proposal is not None and proposal.user_id == USER
    terms = to_primitive(proposal.terms)
    assert {k: terms[k] for k in ("action", "amount", "currency", "source_account", "destination")} == {
        "action": "set_liquidity_floor", "amount": 100_000, "currency": "CLP", "source_account": "checking", "destination": "checking",
    }
    assert "liquidity floor rule of 100,000 CLP" in reply.text and "Nothing changes until you confirm" in reply.text
    assert reply.verification.ok and not reply.fallback_used


@pytest.mark.parametrize(
    "message",
    ["No quiero que mi cuenta baje de 200 mil, pon un saldo mínimo", "Set my minimum balance to 120,000", "I want a floor of 80,000 in my checking account"],
)
def test_other_ways_of_asking_for_a_floor_reach_the_same_tool(services, message):
    reply = services.chat.handle("s-floor-2", USER, message)
    assert reply.intent == "set_liquidity_floor" and reply.tools_called == ("propose_liquidity_floor",)
    assert reply.pending_proposal is not None


def test_without_an_amount_the_copilot_asks_for_it(services):
    reply = services.chat.handle("s-floor-3", USER, "Quiero poner una regla de piso")
    assert reply.intent == "set_liquidity_floor" and reply.tools_called == () and reply.pending_proposal is None
    assert "minimum balance" in reply.text


def test_the_model_cannot_choose_a_floor_the_user_did_not_write(services, adapters):
    """Rule 2: the model only relays the user's number. Any other amount is refused and nothing is proposed."""
    llm = ScriptedFakeLLM([call("propose_liquidity_floor", amount=10_000), say("Done, your floor is 10,000.")])
    reply = chat_with(services, adapters, llm).handle("s-floor-4", USER, "Quiero que el piso sea de 100.000")
    assert reply.pending_proposal is None
    assert reply.actions[-1].status == "INVALID_INPUT" and reply.actions[-1].field == "amount"
    assert "PROPOSAL_CREATED" not in audit_kinds(adapters)
    assert services.actions.pending(agent_ctx("s-floor-4")).proposals == ()


def test_a_read_only_turn_cannot_propose_a_floor(services, adapters):
    llm = ScriptedFakeLLM([call("propose_liquidity_floor", amount=100_000)])

    class Unsure:
        name = "unsure"

        def judge(self, state, questions):
            from neural_ledger.domain.agent.questions import Judgment

            return {
                q.key: Judgment(q.key, "set_liquidity_floor" if q.key == "intent" else "no", (), 0.3 if q.key == "intent" else 0.99, "unsure")
                for q in questions
            }

    reply = chat_with(services, adapters, llm, decision_models=[Unsure()]).handle("s-floor-5", USER, "piso de 100.000")
    assert reply.gate == "read_only" and reply.pending_proposal is None
    assert reply.blocked_reason == "TIER_NOT_ALLOWED"


def test_once_confirmed_and_executed_every_engine_uses_the_users_floor(services):
    before = services.financial.forecast(USER, 6, "conservative")
    assert _facts(before)["liquidity_floor"] == (150_000, "parameter register")

    reply = services.chat.handle("s-floor-6", USER, "Quiero que el piso sea de 100.000")
    proposal = reply.pending_proposal
    confirmed = services.actions.confirm(user_ctx("s-floor-6"), proposal.proposal_id, to_primitive(proposal.terms))
    assert confirmed.status == "CONFIRMED"
    executed = services.chat.handle("s-floor-6", USER, "hazlo")
    assert executed.actions[-1].status == "EXECUTED" and "liquidity floor of 100,000 CLP is now active" in executed.text

    after = services.financial.forecast(USER, 6, "conservative")
    assert after.data.floor == 100_000 and after.snapshot_id != before.snapshot_id
    assert [c.headroom for c in after.data.cycles] == [c.headroom + 50_000 for c in before.data.cycles]
    assert _facts(services.financial.protected_surplus(USER, 6))["liquidity_floor"] == (100_000, "your liquidity floor rule")
    # a floor rule moves no money: it is not a savings rule in the active-plan overlay
    assert services.financial.forecast(USER, 6, "conservative", "active").data.cycles == after.data.cycles


def test_a_later_floor_replaces_the_earlier_one(services):
    for amount, text in ((100_000, "piso de 100.000"), (250_000, "Cambia mi piso a 250.000 todos los meses")):
        session = f"s-floor-{amount}"
        proposal = services.chat.handle(session, USER, text).pending_proposal
        services.actions.confirm(user_ctx(session), proposal.proposal_id, to_primitive(proposal.terms))
        assert services.chat.handle(session, USER, "hazlo").actions[-1].status == "EXECUTED"
    assert services.financial.forecast(USER, 3, "conservative").data.floor == 250_000
