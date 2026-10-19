"""S23 (ADR-037): a hostile or careless model and the user's liquidity floor.

The model may only relay a floor the user wrote this turn, and only in a turn whose gate allows proposals.
"""

from __future__ import annotations

import pytest

from .helpers import USER, ScriptedFakeLLM, agent_ctx, audit_kinds, call, chat_with, say

pytestmark = pytest.mark.security


def test_s23_the_model_cannot_choose_a_floor_the_user_did_not_write(services, adapters):
    """Rule 2: the model only relays the user's number. Any other amount is refused and nothing is proposed."""
    llm = ScriptedFakeLLM([call("propose_liquidity_floor", amount=10_000), say("Done, your floor is 10,000.")])
    reply = chat_with(services, adapters, llm).handle("s-floor-4", USER, "Quiero que el piso sea de 100.000")
    assert reply.pending_proposal is None
    assert reply.actions[-1].status == "INVALID_INPUT" and reply.actions[-1].field == "amount"
    assert "PROPOSAL_CREATED" not in audit_kinds(adapters)
    assert services.actions.pending(agent_ctx("s-floor-4")).proposals == ()


def test_s23_a_read_only_turn_cannot_propose_a_floor(services, adapters):
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
