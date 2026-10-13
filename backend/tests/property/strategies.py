"""Hypothesis strategies: random VALID ledgers built by the same generator as the personas.

Each example is a GeneratorConfig with varied income (salaried or freelance, zero months
allowed), rent, subscriptions, per-category P80, cuota plans (active, ending, finished,
injection merchants included) and unexpected expense. Balances are derived, not pinned.
"""

from __future__ import annotations

import json

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

from neural_ledger.adapters.outbound.fixtures.ledger_source import parse_ledger
from neural_ledger.domain.ledger.entities import LedgerSnapshot
from neural_ledger.domain.shared.month import Month
from tests.fixtures.ledger_generator import INJECTION_MERCHANT, P80, GeneratorConfig, Plan, generate_ledger

PROPERTY_SETTINGS = settings(
    max_examples=60,
    deadline=None,
    derandomize=True,  # same examples on every run and in CI
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

MERCHANTS = ("Phone", "Laptop", "Sofa", "Bicicleta", INJECTION_MERCHANT, "TIENDA <script>alert(1)</script>")
CATEGORIES = ("electronics", "home", "travel", "sports")


def _thousands(low: int, high: int) -> st.SearchStrategy[int]:
    return st.integers(low, high).map(lambda k: k * 1_000)


@st.composite
def plans(draw) -> tuple[Plan, ...]:
    count = draw(st.integers(0, 4))
    out = []
    for i in range(count):
        out.append(
            Plan(
                plan_id=f"plan{i}",
                merchant=draw(st.sampled_from(MERCHANTS)),
                category=draw(st.sampled_from(CATEGORIES)),
                installment=draw(_thousands(10, 300)),
                total=draw(st.sampled_from((3, 6, 12, 18, 24))),
                first=Month(2025, 6).plus(draw(st.integers(0, 16))),
                monthly_rate=draw(st.sampled_from((None, "0.015", "0.025"))),
            )
        )
    return tuple(out)


@st.composite
def configs(draw) -> GeneratorConfig:
    salaried = draw(st.booleans())
    freelance = None
    if not salaried:
        freelance = tuple(draw(st.lists(st.one_of(st.just(0), _thousands(300, 3_500)), min_size=12, max_size=12).filter(lambda xs: sum(1 for x in xs if x) >= 7)))
    p80 = {category: draw(_thousands(10, 400)) for category in P80}
    p80["health"] = min(p80["health"], 200_000)  # the unexpected expense must stay above the health P80 range
    return GeneratorConfig(
        user_id="prop",
        seed=draw(st.integers(0, 2**32 - 1)),
        plans=draw(plans()),
        salary=draw(_thousands(600, 4_000)) if salaried else None,
        freelance_income=freelance,
        rent=draw(_thousands(150, 900)),
        subscriptions=draw(_thousands(5, 120)),
        p80=p80,
        unexpected_expense=draw(_thousands(300, 1_500)),
        bonus=draw(st.sampled_from((0, 150_000))),
        savings_opening=50_000_000,
        savings_buckets=None,
        strict_balances=False,
    )


@st.composite
def raw_ledgers(draw) -> dict:
    return generate_ledger(draw(configs()))


def snapshot_of(raw: dict) -> LedgerSnapshot:
    return parse_ledger(json.loads(json.dumps(raw)))
