"""ADR-032 (fc-0.2): any installment count from 1 (no cuotas) to max_installments is valid."""

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
    suggested = {a.installments for a in envelope.data.alternatives if a.kind.value == "CHANGE_INSTALLMENTS"}
    assert suggested <= set(FC_0_1.suggested_installments)
