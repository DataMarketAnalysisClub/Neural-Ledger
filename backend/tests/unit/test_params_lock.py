"""Parameter lock: the numbers behind a params_version never change silently.

If this fails, a value in domain/finance/params.py changed. Either revert it, or bump
`version` (e.g. fc-0.2 -> fc-0.3), record the new fingerprint below, and log the team decision in
docs/DECISIONS.md. The golden answers E01-E14 were set under fc-0.1 and hold unchanged through fc-0.3.
"""

from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal
from fractions import Fraction

import pytest

from neural_ledger.domain.finance.params import FC_0_1

LOCKED = {
    "fc-0.1": "6d825a8367ab0c8c435f6207f833993648d6dba1fb497e8acfafa8e51eac4325",
    "fc-0.2": "3404ab82f69f4107063e79f88d83ddeab4feccfd4761b5cfb0c98bfab08ae4ef",  # any installment count from 1 to 48 (ADR-034)
    "fc-0.3": "d952766e5478a69c47dacbd9f0bbd92292a2423fe7659d228c5e65183910953e",  # a single charge (1 cuota) carries no interest (ADR-034)
}


def test_current_parameters_match_their_locked_version():
    assert FC_0_1.version in LOCKED, f"new params version {FC_0_1.version!r}: record its fingerprint in LOCKED"
    assert FC_0_1.fingerprint() == LOCKED[FC_0_1.version], (
        f"{FC_0_1.version} values changed: bump `version` and record the new fingerprint ({FC_0_1.fingerprint()})"
    )


def test_the_version_label_is_not_part_of_the_fingerprint():
    assert replace(FC_0_1, version="fc-other").fingerprint() == FC_0_1.fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"liquidity_floor": FC_0_1.liquidity_floor + 1},
        {"seasonal_factor_max": FC_0_1.seasonal_factor_max + Fraction(1, 10**12)},
        {"profile_share": (Fraction(2, 5), Fraction(3, 5), Fraction(4, 5) + Fraction(1, 10**9))},
        {"essential_categories": FC_0_1.essential_categories | {"dining"}},
        {"suggested_installments": (*FC_0_1.suggested_installments, 36)},
        {"income_cv_ddof": 0},
    ],
    ids=lambda c: next(iter(c)),
)
def test_any_value_change_moves_the_fingerprint(change):
    assert replace(FC_0_1, **change).fingerprint() != FC_0_1.fingerprint()


def _changed(value):
    """A different value of the same type, so a field left out of the fingerprint would go unnoticed."""
    if isinstance(value, Fraction):
        return value + Fraction(1, 10**9)
    if isinstance(value, Decimal):
        return value + Decimal("0.001")
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, frozenset):
        return value | {"__changed__"}
    if isinstance(value, tuple):
        return (*value, value[-1]) if value else (0,)
    raise TypeError(f"no change rule for {type(value).__name__}")


@pytest.mark.parametrize("name", [f.name for f in fields(FC_0_1) if f.name != "version"])
def test_every_parameter_is_fingerprinted(name):
    assert replace(FC_0_1, **{name: _changed(getattr(FC_0_1, name))}).fingerprint() != FC_0_1.fingerprint()
