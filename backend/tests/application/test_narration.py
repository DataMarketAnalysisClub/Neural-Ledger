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
