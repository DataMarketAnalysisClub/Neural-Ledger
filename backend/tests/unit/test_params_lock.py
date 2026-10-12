"""Parameter lock: the numbers behind a params_version never change silently.

If this fails, a value in domain/finance/params.py changed. Either revert it, or bump
`version` (fc-0.1 -> fc-0.2), record the new fingerprint below, and log the team decision in
docs/DECISIONS.md. The golden answers E01-E14 belong to fc-0.1.
"""

from __future__ import annotations

from dataclasses import fields, replace
from fractions import Fraction

import pytest

from neural_ledger.domain.finance.params import FC_0_1

LOCKED = {
    "fc-0.1": "6d825a8367ab0c8c435f6207f833993648d6dba1fb497e8acfafa8e51eac4325",
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
        {"allowed_installments": (*FC_0_1.allowed_installments, 36)},
        {"income_cv_ddof": 0},
    ],
    ids=lambda c: next(iter(c)),
)
def test_any_value_change_moves_the_fingerprint(change):
    assert replace(FC_0_1, **change).fingerprint() != FC_0_1.fingerprint()


def test_every_parameter_is_fingerprinted():
    for f in fields(FC_0_1):
        if f.name == "version":
            continue
        assert FC_0_1.fingerprint() == replace(FC_0_1, **{f.name: getattr(FC_0_1, f.name)}).fingerprint()
