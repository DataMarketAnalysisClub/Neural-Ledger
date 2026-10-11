"""The deterministic narrator is the safe fallback, so its output must ALWAYS pass the verifier."""

from __future__ import annotations

import pytest

from neural_ledger.application.conversation import ToolCall
from neural_ledger.application.services.narration import narrate
from neural_ledger.application.services.tools import ToolContext
from neural_ledger.domain.agent.verification import verify_explanation
from neural_ledger.domain.permissions.policy import Tier

CALLS = [
    ("get_financial_state", {}),
    ("get_commitments", {"horizon_months": 6}),
    ("forecast_cashflow", {"scenario": "conservative"}),
    ("forecast_cashflow", {"scenario": "typical", "include_plan": "recommended"}),
    ("forecast_cashflow", {"scenario": "stress"}),
    ("simulate_purchase", {"amount": 400000, "installments": 12}),
    ("simulate_purchase", {"amount": 400000, "installments": 12, "first_installment_month": "2027-01", "monthly_rate": 0.02}),
    ("simulate_purchase", {"amount": 3000000, "installments": 3}),
    ("compute_protected_surplus", {"include_plan": "recommended"}),
    ("assess_financial_capacity", {}),
    ("assess_risk_tolerance", {}),
    ("derive_permitted_profile", {"tolerance": "aggressive"}),
    ("compute_savings_plan", {"permitted_profile": "aggressive"}),
    ("get_pending_actions", {}),
    ("simulate_purchase", {"amount": 400000, "installments": 7}),
]


@pytest.mark.parametrize("user", ["camila", "diego"])
@pytest.mark.parametrize("name, args", CALLS)
def test_narration_passes_verification(services, user, name, args):
    ctx = ToolContext("s-narration", user)
    outcome = services.registry.invoke(ToolCall("c1", name, args), ctx, max_tier=Tier.T2, allow_stateful=True)
    text = narrate([(name, outcome.payload)], "CLP")
    result = verify_explanation(text, outcome.facts, outcome.warnings)
    assert result.ok, (text, result.issues)


def run(services, name, args, user="camila"):
    outcome = services.registry.invoke(ToolCall("c1", name, args), ToolContext("s-narration", user), max_tier=Tier.T2, allow_stateful=True)
    return name, outcome.payload


def test_a_tool_called_twice_with_the_same_input_is_narrated_once(services):
    result = run(services, "simulate_purchase", {"amount": 400000, "installments": 12})
    assert narrate([result, result], "CLP") == narrate([result], "CLP")


def test_a_warning_shared_by_several_results_is_said_once(services):
    first = run(services, "simulate_purchase", {"amount": 400000, "installments": 12})
    second = run(services, "simulate_purchase", {"amount": 300000, "installments": 12})
    text = narrate([first, second], "CLP")
    assert text.count("Monthly rate assumed") == 1 and text.count("I assumed the first cuota") == 1
    assert "400,000 CLP" in text and "300,000 CLP" in text  # different results are both kept


def test_deduplicated_narration_still_passes_the_verifier(services):
    results = [run(services, "simulate_purchase", {"amount": a, "installments": 12}) for a in (400000, 300000, 400000)]
    facts = [f for _, p in results for f in _facts(p)]
    caveats = [c for _, p in results for c in _caveats(p)]
    assert verify_explanation(narrate(results, "CLP"), facts, caveats).ok


def _facts(payload):
    from neural_ledger.domain.shared.envelope import Fact

    return [Fact(f["key"], f["value"], f["unit"], f.get("derivation", "")) for f in payload.get("facts", ())]


def _caveats(payload):
    from neural_ledger.domain.shared.envelope import Caveat

    return [Caveat(w["code"], w["message"], tuple(w.get("must_mention", ()))) for w in payload.get("warnings", ())]
