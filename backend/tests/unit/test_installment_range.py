"""ADR-034: any installment count from 1 (no cuotas) to max_installments is valid (fc-0.2), and 1 carries no interest (fc-0.3)."""

from __future__ import annotations

import pytest

from neural_ledger.domain.finance.params import FC_0_1


@pytest.mark.parametrize("installments", [1, 2, 7, 10, FC_0_1.max_installments])
def test_any_count_in_range_is_priced(services, installments):
    envelope = services.financial.simulate_purchase("camila", 400_000, installments)
    assert envelope.status.value == "OK"
    assert envelope.data.quote.installments == installments


@pytest.mark.parametrize("installments", [0, -3, FC_0_1.max_installments + 1, True, 12.5])
def test_counts_outside_the_range_are_refused(services, installments):
    envelope = services.financial.simulate_purchase("camila", 400_000, installments)
    assert envelope.status.value == "INVALID_INPUT" and envelope.field == "installments"


def test_alternatives_only_suggest_the_standard_counts(services):
    envelope = services.financial.simulate_purchase("camila", 400_000, 7)
    suggested = {a.installments for a in envelope.data.alternatives if a.kind.value == "change_installments"}
    assert suggested <= set(FC_0_1.suggested_installments)


@pytest.mark.parametrize("rate", [None, 0.05])
def test_a_single_charge_carries_no_interest_whatever_the_rate(services, rate):
    kwargs = {} if rate is None else {"monthly_rate": rate}
    envelope = services.financial.simulate_purchase("camila", 400_000, 1, **kwargs)
    q = envelope.data.quote
    assert (q.installment, q.total_cost, q.total_interest, q.monthly_rate, q.rate_assumed) == (400_000, 400_000, 0, 0, False)
    facts = {f.key: f.value for f in envelope.facts}
    assert facts["purchase.total_interest"] == 0 and facts["purchase.effective_annual_rate_pct"] == 0


def test_alternatives_with_cuotas_still_pay_the_offers_rate_and_say_it_was_assumed(services):
    envelope = services.financial.simulate_purchase("camila", 250_000, 1)  # fits only in cuotas
    sim = envelope.data
    assert (float(sim.offer_rate), sim.offer_rate_assumed) == (float(FC_0_1.default_monthly_rate), True)
    (change,) = [a for a in sim.alternatives if a.kind.value == "change_installments"]
    assert change.installments > 1 and change.total_interest > 0  # priced at the offer's rate, never the single charge's 0
    assert sim.quote.total_interest == 0 and "RATE_ASSUMED" in [w.code for w in envelope.warnings]


def test_a_single_charge_without_cuotas_alternatives_has_no_rate_warning(services):
    envelope = services.financial.simulate_purchase("camila", 20_000, 1)  # fits: no alternatives are computed
    assert envelope.data.alternatives == () and "RATE_ASSUMED" not in [w.code for w in envelope.warnings]
