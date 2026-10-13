"""The synthetic backtest: no future data, reproducible output, honest metric kinds (docs/BACKTEST.md)."""

from __future__ import annotations

import copy
import json
from datetime import date
from fractions import Fraction

import jsonschema
import pytest

from neural_ledger.domain.finance.paycycle import is_eve_of_payday
from neural_ledger.domain.shared.month import Month
from tests.backtest import run as bt
from tests.backtest.metrics import BERNOULLI, CONTINUOUS, coverage, summary, wilson
from tests.backtest.reference import BASE_SEED, exact_continuous_rank, exact_continuous_rank_text
from tests.conftest import CONTRACTS
from tests.fixtures.ledger_generator import generate_ledger_with_truth


@pytest.fixture(scope="module")
def salaried():
    return generate_ledger_with_truth(bt.config("salaried", bt.SALARIED_SEED))


@pytest.fixture(scope="module")
def results():
    return bt.run(2, reference_trials=200)


# ---- calendar ---------------------------------------------------------------------------------


def test_calendar_supports_the_required_evaluation():
    assert (bt.CYCLES[0], bt.CYCLES[-1]) == (Month(2025, 4), Month(2026, 12))
    assert bt.CYCLES[8] == Month(2025, 12)  # December 2025 is cycle 9
    for origins in bt.GRIDS.values():
        for k in origins:
            assert is_eve_of_payday(bt.origin_as_of(k))
            assert k + bt.HORIZON <= bt.N_CYCLES  # every evaluated cycle exists
    december_evaluated = [k for k in bt.GRIDS["A"] if Month(2025, 12) in bt.CYCLES[k : k + bt.HORIZON]]
    assert december_evaluated == [6, 7, 8]
    assert Month(2026, 12) in bt.CYCLES[18:21] and Month(2025, 12) in bt.CYCLES[18 - 12 : 18]  # grid B window holds Dec 2025


def test_every_origin_estimates(salaried):
    raw, _ = salaried
    for origins in bt.GRIDS.values():
        for k in origins:
            envelope = bt.estimate_at(raw, k)
            assert envelope.ok, (k, envelope.status, envelope.field, envelope.missing)
            assert envelope.data.as_of == bt.origin_as_of(k)


@pytest.mark.parametrize("kind", ["salaried", "freelance"])
def test_generated_backtest_ledger_matches_schema_and_reconciles(kind):
    raw, _ = generate_ledger_with_truth(bt.config(kind, 17))
    schema = json.loads((CONTRACTS / "ledger" / "ledger.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(raw)
    for account in raw["accounts"]:
        movements = sum(t["amount"] for t in raw["transactions"] if t["account_id"] == account["account_id"])
        assert account["opening_balance"] + movements == account["balance"]


# ---- leakage ----------------------------------------------------------------------------------


def test_origin_ledger_holds_no_future_transaction(salaried):
    raw, _ = salaried
    as_of = bt.origin_as_of(6)
    origin = bt.ledger_at(raw, as_of)
    assert origin["as_of"] == as_of.isoformat()
    assert max(date.fromisoformat(t["date"]) for t in origin["transactions"]) <= as_of
    assert len(origin["transactions"]) < len(raw["transactions"])


def test_changing_post_origin_data_does_not_change_the_origin_estimate(salaried):
    raw, _ = salaried
    k = 6
    before = bt.estimate_at(raw, k)
    mutated = copy.deepcopy(raw)
    later = [t for t in mutated["transactions"] if date.fromisoformat(t["date"]) > bt.origin_as_of(k)]
    assert later
    for t in later:
        t["amount"] = t["amount"] * 3 if t["kind"] == "purchase" else t["amount"]
    after = bt.estimate_at(mutated, k)
    assert after.data.source_version == before.data.source_version
    assert after.data == before.data
    assert bt.estimate_at(mutated, 9).data.source_version != bt.estimate_at(raw, 9).data.source_version  # the mutation is real


# ---- reproducibility and metric kinds ---------------------------------------------------------


def test_two_runs_are_byte_identical(results):
    assert bt.render(bt.run(2, reference_trials=200)) == bt.render(results)


def test_reference_uses_actual_marginals_windows_and_origin_weights(results):
    reference = results["reference"]
    spend = reference["cells"]["spend_p80"]
    income = reference["cells"]["freelance_income_p20"]
    assert reference["base_seed"] == BASE_SEED
    assert [spend[f"A.{origin}.groceries"]["window_n"] for origin in bt.GRIDS["A"]] == [6, 7, 8, 8]
    assert spend["B.18.groceries"]["window_n"] == 11
    assert [income[f"A.{origin}"]["window_n"] for origin in bt.GRIDS["A"]] == [6, 7, 8, 9]
    assert income["B.18"]["window_n"] == 12
    assert spend["A.6.groceries"]["median"] == bt.SPEND["groceries"].median
    assert spend["A.6.health"]["sigma"] == str(bt.SPEND["health"].sigma)
    for grid in bt.GRIDS:
        assert reference["pooled"][grid]["spend_p80"]["observed_n"] == results["results"][grid]["p80_coverage_non_december"]["n"]
        assert reference["pooled"][grid]["freelance_income_p20"]["observed_n"] == results["results"][grid]["freelance_income_p20_coverage"]["n"]
        assert sum(cell["observed_hits"] for cell in spend.values() if cell["grid"] == grid) == results["results"][grid]["p80_coverage_non_december"]["hits"]
        assert sum(cell["observed_hits"] for cell in income.values() if cell["grid"] == grid) == results["results"][grid]["freelance_income_p20_coverage"]["hits"]


@pytest.mark.parametrize("n,q,upper,expected", [
    (6, Fraction(4, 5), True, Fraction(5, 7)),
    (6, Fraction(1, 5), False, Fraction(5, 7)),
    (11, Fraction(4, 5), True, Fraction(9, 12)),
    (7, Fraction(4, 5), True, None),
])
def test_exact_continuous_rank_when_quantile_is_an_order_statistic(n, q, upper, expected):
    assert exact_continuous_rank(n, q, upper) == expected


def test_exact_continuous_rank_text_preserves_order_statistic_denominator(results):
    assert results["reference"]["exact_continuous"] == {
        "spend_p80_n6": "5/7", "spend_p80_n11": "9/12", "freelance_income_p20_n6": "5/7",
    }
    assert exact_continuous_rank_text(7, Fraction(4, 5), True) is None


def test_rounded_monte_carlo_agrees_with_continuous_n6_rank():
    from tests.backtest.reference import _cell

    upper = _cell(bt.SPEND["groceries"], bt.SALARIED_SPEC, 6, Fraction(4, 5), True, 10_000, BASE_SEED)
    lower = _cell(bt.FREELANCE_SPEC.freelance, bt.FREELANCE_SPEC, 6, Fraction(1, 5), False, 10_000, BASE_SEED + 1)
    assert abs(upper["expected"] - 5 / 7) < 4 * upper["mc_se"]
    assert abs(lower["expected"] - 5 / 7) < 4 * lower["mc_se"]


@pytest.mark.parametrize("origin", [6, 7, 8, 9, 18])
def test_estimator_quantiles_use_generator_truth_window(salaried, origin):
    from neural_ledger.domain.finance.estimation import quantile
    from neural_ledger.domain.shared.numbers import round_half_up

    raw, truth = salaried
    model = bt.estimate_at(raw, origin).data
    window = bt.CYCLES[max(0, origin - bt.FC_0_1.spend_window_months):origin]
    base_cycles = [cycle for cycle in window if cycle.month != 12]
    assert model.spend.window_months == len(window)
    for fitted in model.spend.categories:
        expected = round_half_up(quantile([truth["spend"][fitted.category][cycle] for cycle in base_cycles], Fraction(4, 5)))
        assert fitted.p80 == expected


@pytest.mark.parametrize("origin", [6, 7, 8, 9, 18])
def test_freelance_lower_bound_uses_generator_truth_window(origin):
    from neural_ledger.domain.finance.estimation import quantile
    from neural_ledger.domain.shared.numbers import round_half_up

    raw, truth = generate_ledger_with_truth(bt.config("freelance", bt.FREELANCE_SEED))
    model = bt.estimate_at(raw, origin).data
    window = bt.CYCLES[max(0, origin - bt.FC_0_1.spend_window_months):origin]
    assert model.income.conservative == round_half_up(quantile([truth["income"][cycle] for cycle in window], Fraction(1, 5)))


def test_results_carry_labels_sizes_and_diagnostics(results):
    assert results["label"] == bt.LABEL
    assert any("clustered by seed" in note for note in results["notes"])
    assert results["seeds"]["n"] == 2
    assert results["versions"]["params"] == "fc-0.1"
    diagnostics = results["diagnostics"]
    assert {"non_ok_envelopes", "commitment_set_mismatches", "missing_category_trials", "estimates"} <= set(diagnostics)
    assert diagnostics["estimates"] == {"freelance.A": 8, "freelance.B": 2, "salaried.A": 8, "salaried.B": 2}
    a, b = results["results"]["A"], results["results"]["B"]
    assert a["december_conservative_coverage"]["n"] <= 2 * 3  # origins 6, 7, 8 per seed
    assert b["december_conservative_coverage"]["n"] <= 2  # origin 18 per seed
    assert a["december_seasonal_factor_used"]["n"] == a["december_conservative_coverage"]["n"]
    json.loads(bt.render(results))  # valid JSON


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_intervals_only_on_bernoulli_rates(results):
    kinds = set()
    for node in _walk(results):
        kind = node.get("kind")
        if "wilson95" in node:
            assert kind == BERNOULLI
        if kind == CONTINUOUS:
            assert not any(word in key for key in node for word in ("wilson", "interval", "ci"))
            assert "n" in node
        if kind == BERNOULLI:
            assert {"n", "hits", "rate", "wilson95"} <= set(node)
        kinds.add(kind)
    assert {BERNOULLI, CONTINUOUS} <= kinds
    assert results["parameter_recovery_relative_error"]
    assert all(m["kind"] == CONTINUOUS for m in results["parameter_recovery_relative_error"].values())


# ---- metrics ----------------------------------------------------------------------------------


def test_wilson_interval_matches_the_reference_values():
    low, high = wilson(8, 10)
    assert abs(low - 0.4902) < 1e-4 and abs(high - 0.9433) < 1e-4
    assert wilson(0, 5)[0] < 1e-12 and wilson(5, 5)[1] > 1 - 1e-12
    assert 0 < wilson(0, 5)[1] < 1 and 0 < wilson(5, 5)[0] < 1


@pytest.mark.parametrize("hits, n", [(0, 0), (3, 2), (-1, 4)])
def test_wilson_rejects_impossible_counts(hits, n):
    with pytest.raises(ValueError):
        wilson(hits, n)


def test_empty_samples_report_their_size_and_no_rate():
    assert coverage([]) == {"kind": BERNOULLI, "n": 0, "hits": 0, "nominal": None, "rate": None, "wilson95": None}
    assert summary([])["n"] == 0 and summary([])["median"] is None
    s = summary([-0.2, 0.1, 0.3])
    assert (s["n"], s["median"], s["mean_abs"]) == (3, 0.1, 0.2)
