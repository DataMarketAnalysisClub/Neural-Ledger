"""Cuota plans that complete inside the window are history: never variable spend, never commitments."""

from __future__ import annotations

from datetime import date

from neural_ledger.domain.ledger.entities import InstallmentInfo
from tests.unit.test_estimation_edges import base_transactions, cycles, estimate, txn


def test_cuota_plans_completed_inside_the_window_never_reach_spend_or_commitments(params):
    months = cycles(10)
    base = base_transactions(10)
    metadata_plan = [
        txn(date(c.year, c.month, 1), -60_000, f"BICI CUOTA {k:02d}/03", "sports", account="credit_card", installment=InstallmentInfo("bici", k, 3, 180_000))
        for k, c in enumerate(months[1:4], start=1)
    ]
    text_plan = [
        txn(date(c.year, c.month, 1), -35_000, f"ZAPATOS CUOTA {k:02d}/02", "shopping", account="credit_card")
        for k, c in enumerate(months[5:7], start=1)
    ]
    clean = estimate(base, params).data
    with_plans = estimate(base + metadata_plan + text_plan, params)
    assert with_plans.ok
    assert with_plans.data.spend == clean.spend
    assert with_plans.data.largest_one_off_expense == clean.largest_one_off_expense
    assert {c.commitment_id for c in with_plans.data.commitments} == {c.commitment_id for c in clean.commitments}
    assert "INSTALLMENT_UNPARSED" not in {w.code for w in with_plans.warnings}
