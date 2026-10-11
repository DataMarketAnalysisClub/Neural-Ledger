"""Rolling-origin synthetic backtest of the stage-1 estimators (docs/BACKTEST.md, ADR-015).

Synthetic implementation validation, not predictive accuracy: the ledgers come from the
stochastic generator (tests/fixtures/stochastic.py), so the "truth" is the generator's own
draws and parameters. It checks that the estimators behave as specified on data whose
distribution is known; it says nothing about real spending.

Calendar: 21 pay cycles, 2025-04 .. 2026-12 (as_of 2026-12-30), so December 2025 is cycle 9
and December 2026 cycle 21.
  Grid A (design section 8): origins after k = 6, 7, 8, 9 cycles, horizon 3. December 2025 is
    evaluated out of sample from k = 6, 7, 8 with no earlier December in the history, so the
    seasonal factor is the default 1 (F17). k = 9 has it in sample.
  Grid B (supplementary): origin k = 18 (history to 2026-09; its 12-cycle window holds
    December 2025), evaluating 2026-10 .. 2026-12 with last year's seasonal evidence.
    With history <= 9 cycles and horizon 3, no origin can both see a December and evaluate
    the next one, hence the extra grid.
Each origin sees only transactions dated <= its as_of (asserted); realized values are read
from the generator's truth record after estimation. Non-OK envelopes are counted, never
retried. Output: sorted JSON without timestamps, byte-identical for the same --seeds.

Usage (from backend/):  python -m tests.backtest.run --seeds 100 --out ../evidence/backtest/synthetic_backtest.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

from neural_ledger.adapters.outbound.fixtures.ledger_source import parse_ledger
from neural_ledger.domain.finance.estimation import estimate_model
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.finance.paycycle import cycle_end
from neural_ledger.domain.shared.envelope import Envelope
from neural_ledger.domain.shared.month import Month, month_range
from tests.backtest.metrics import Z95, coverage, summary
from tests.backtest.reference import DEFAULT_TRIALS, finite_sample_reference
from tests.fixtures.ledger_generator import GENERATOR_VERSION, GeneratorConfig, generate_ledger_with_truth
from tests.fixtures.stochastic import CATEGORIES, SEASONAL_MONTH, Lognormal, StochasticSpec, true_parameters

BACKTEST_VERSION = "bt-0.1"
LABEL = "synthetic implementation validation; not predictive accuracy"
FIRST_CYCLE, N_CYCLES = Month(2025, 4), 21
CYCLES = month_range(FIRST_CYCLE, N_CYCLES)
HORIZON = 3
GRIDS = {"A": (6, 7, 8, 9), "B": (18,)}
RECOVERY_ORIGIN = 18  # the only origin with a full 12-cycle window that holds a December
EXPECTED_COMMITMENTS = frozenset({"rent", "subscriptions"})
SALARIED_SEED, FREELANCE_SEED = 150_000, 250_000

SPEND = {
    "groceries": Lognormal(264_000, Fraction(1, 4)),
    "dining": Lognormal(144_000, Fraction(1, 4)),
    "transport": Lognormal(96_000, Fraction(1, 4)),
    "shopping": Lognormal(96_000, Fraction(2, 5)),
    "utilities": Lognormal(72_000, Fraction(1, 4)),
    "health": Lognormal(48_000, Fraction(2, 5)),
}
SALARIED_SPEC = StochasticSpec(FIRST_CYCLE, N_CYCLES, SPEND)
FREELANCE_SPEC = StochasticSpec(FIRST_CYCLE, N_CYCLES, SPEND, freelance=Lognormal(1_800_000, Fraction(3, 10)))


def config(kind: str, seed: int) -> GeneratorConfig:
    common = dict(plans=(), bonus=0, savings_opening=50_000_000, savings_buckets=None, strict_balances=False)
    if kind == "salaried":
        return GeneratorConfig(f"bt_salaried_{seed}", seed, salary=1_800_000, stochastic=SALARIED_SPEC, **common)
    return GeneratorConfig(f"bt_freelance_{seed}", seed, salary=None, stochastic=FREELANCE_SPEC, **common)


def origin_as_of(k: int) -> date:
    return cycle_end(CYCLES[k - 1])


def ledger_at(raw: dict[str, Any], as_of: date) -> dict[str, Any]:
    """The ledger as it was on `as_of`: later transactions removed, balances recomputed.

    A leak cannot pass silently: validate_snapshot answers INVALID_INPUT for any transaction
    dated after as_of, and that would be counted as a non-OK envelope.
    """
    txns = [t for t in raw["transactions"] if date.fromisoformat(t["date"]) <= as_of]
    accounts = [
        {**a, "balance": a["opening_balance"] + sum(t["amount"] for t in txns if t["account_id"] == a["account_id"])}
        for a in raw["accounts"]
    ]
    savings = next(a["balance"] for a in accounts if a["account_id"] == "savings")
    return {**raw, "as_of": as_of.isoformat(), "accounts": accounts, "buckets": [{"bucket": "reserve", "amount": savings}], "transactions": txns}


def estimate_at(raw: dict[str, Any], k: int) -> Envelope:
    as_of = origin_as_of(k)
    prefix = ledger_at(raw, as_of)
    assert all(date.fromisoformat(txn["date"]) <= as_of for txn in prefix["transactions"])
    return estimate_model(parse_ledger(prefix), FC_0_1)


def _rel(estimate: float, true: float) -> float:
    return (estimate - true) / true


class _Grid:
    def __init__(self) -> None:
        self.p80_hits: list[bool] = []
        self.p80_by_origin: dict[int, list[bool]] = {}
        self.p50_rel: list[float] = []
        self.december_hits: list[bool] = []
        self.december_factors: list[float] = []
        self.income_hits: list[bool] = []
        self.per_seed_p80: list[float] = []

    def results(self, origins: tuple[int, ...]) -> dict:
        return {
            "p80_coverage_non_december": coverage(self.p80_hits, nominal=0.8),
            "p80_coverage_by_origin": {str(k): coverage(self.p80_by_origin.get(k, []), nominal=0.8) for k in origins},
            "p80_coverage_per_seed_rate": summary(self.per_seed_p80),
            "p50_signed_relative_error_non_december": summary(self.p50_rel),
            "december_conservative_coverage": coverage(self.december_hits),
            "december_seasonal_factor_used": summary(self.december_factors),
            "freelance_income_p20_coverage": coverage(self.income_hits, nominal=0.8),
        }


def run(seeds: int, reference_trials: int = DEFAULT_TRIALS) -> dict[str, Any]:
    if seeds < 1:
        raise ValueError("at least one seed")
    grids = {name: _Grid() for name in GRIDS}
    non_ok: Counter[str] = Counter()
    mismatches: Counter[str] = Counter()
    missing_categories: Counter[str] = Counter()
    warning_codes: Counter[str] = Counter()
    estimates = Counter()
    spend_weights: Counter[tuple[str, int, str]] = Counter()
    income_weights: Counter[tuple[str, int]] = Counter()
    spend_hits: Counter[tuple[str, int, str]] = Counter()
    income_hits: Counter[tuple[str, int]] = Counter()
    recovery: dict[str, list[float]] = {}
    clamped = 0

    def collect(key: str, value: float) -> None:
        recovery.setdefault(key, []).append(value)

    for i in range(seeds):
        for kind, base in (("salaried", SALARIED_SEED), ("freelance", FREELANCE_SEED)):
            raw, truth = generate_ledger_with_truth(config(kind, base + i))
            seed_hits: dict[str, list[bool]] = {name: [] for name in GRIDS}
            for name, origins in GRIDS.items():
                grid = grids[name]
                for k in origins:
                    envelope = estimate_at(raw, k)
                    estimates[f"{kind}.{name}"] += 1
                    warning_codes.update(w.code for w in envelope.warnings)
                    if not envelope.ok:
                        non_ok[f"{kind}.{name}.{envelope.status.value}"] += 1
                        continue
                    model = envelope.data
                    if {c.commitment_id for c in model.commitments} != EXPECTED_COMMITMENTS:
                        mismatches[f"{kind}.{name}"] += 1
                    evaluated = CYCLES[k : k + HORIZON]
                    if kind == "freelance":
                        grid.income_hits += [truth["income"][c] >= model.income.conservative for c in evaluated]
                        income_weights[(name, k)] += len(evaluated)
                        income_hits[(name, k)] += sum(truth["income"][c] >= model.income.conservative for c in evaluated)
                        if k == RECOVERY_ORIGIN:
                            p = true_parameters(FREELANCE_SPEC)["income"]
                            collect("income.p50", _rel(model.income.typical, p["p50"]))
                            collect("income.p20", _rel(model.income.conservative, p["p20"]))
                            collect("income.cv", _rel(float(model.income.cv), p["cv"]))
                        continue
                    estimated = {c.category: c for c in model.spend.categories}
                    for cycle in evaluated:
                        if cycle.month == SEASONAL_MONTH:
                            realized = sum(truth["spend"][c][cycle] for c in CATEGORIES)
                            grid.december_hits.append(realized <= model.spend.total(cycle, "p80"))
                            grid.december_factors.append(float(model.spend.factor(cycle)))
                            continue
                        for category in CATEGORIES:
                            if category not in estimated:
                                missing_categories[f"{kind}.{name}"] += 1
                                continue
                            realized = truth["spend"][category][cycle]
                            hit = realized <= estimated[category].p80
                            grid.p80_hits.append(hit)
                            spend_weights[(name, k, category)] += 1
                            spend_hits[(name, k, category)] += hit
                            grid.p80_by_origin.setdefault(k, []).append(hit)
                            seed_hits[name].append(hit)
                            grid.p50_rel.append(_rel(estimated[category].p50, realized))
                    if k == RECOVERY_ORIGIN:
                        p = true_parameters(SALARIED_SPEC)
                        for category, c in estimated.items():
                            if category in p["spend"]:
                                collect(f"spend.{category}.p50", _rel(c.p50, p["spend"][category]["p50"]))
                                collect(f"spend.{category}.p80", _rel(c.p80, p["spend"][category]["p80"]))
                        factor = model.spend.seasonal_factors.get(SEASONAL_MONTH)
                        if factor is not None:
                            collect("seasonal_factor", _rel(float(factor), float(SALARIED_SPEC.seasonal_factor)))
                            clamped += factor in (FC_0_1.seasonal_factor_min, FC_0_1.seasonal_factor_max)
            if kind == "salaried":
                for name, hits in seed_hits.items():
                    if hits:
                        grids[name].per_seed_p80.append(sum(hits) / len(hits))

    return {
        "label": LABEL,
        "notes": [
            "trials clustered by seed: one seed contributes several origins, categories and cycles, so Wilson intervals are optimistic",
            "Wilson 95% intervals only on Bernoulli coverage rates; continuous errors and recovery report n, median, p10, p90, mean_abs and no interval",
            "relative error = (estimate - realized or true) / (realized or true); the P50 error is against a single realized draw, not the true median",
            "december_conservative_coverage: realized December total <= model.spend.total(December, 'p80'); no nominal level",
            "grid A evaluates December 2025 from origins 6, 7 and 8 without any December in the history (factor 1, F17); grid B evaluates December 2026 with December 2025 in the window",
        ],
        "versions": {"backtest": BACKTEST_VERSION, "generator": GENERATOR_VERSION, "params": FC_0_1.version},
        "calendar": {
            "first_cycle": str(FIRST_CYCLE),
            "n_cycles": N_CYCLES,
            "as_of": cycle_end(CYCLES[-1]).isoformat(),
            "horizon": HORIZON,
            "grids": {name: {"origins": list(origins), "origin_as_of": [origin_as_of(k).isoformat() for k in origins]} for name, origins in GRIDS.items()},
            "recovery_origin": RECOVERY_ORIGIN,
        },
        "seeds": {"n": seeds, "salaried": [SALARIED_SEED, SALARIED_SEED + seeds - 1], "freelance": [FREELANCE_SEED, FREELANCE_SEED + seeds - 1]},
        "spec": {"salaried": true_parameters(SALARIED_SPEC), "freelance": true_parameters(FREELANCE_SPEC), "step": SALARIED_SPEC.step},
        "wilson_z": round(Z95, 6),
        "results": {name: grids[name].results(GRIDS[name]) for name in GRIDS},
        "parameter_recovery_relative_error": {key: summary(values) for key, values in sorted(recovery.items())},
        "diagnostics": {
            "estimates": dict(sorted(estimates.items())),
            "non_ok_envelopes": dict(sorted(non_ok.items())),
            "commitment_set_mismatches": dict(sorted(mismatches.items())),
            "missing_category_trials": dict(sorted(missing_categories.items())),
            "warning_codes": dict(sorted(warning_codes.items())),
            "seasonal_factor_clamped_at_recovery": clamped,
        },
        "reference": finite_sample_reference(FREELANCE_SPEC, CYCLES, spend_weights, income_weights, spend_hits, income_hits, reference_trials),
    }


def render(results: dict[str, Any]) -> str:
    return json.dumps(results, indent=1, sort_keys=True) + "\n"


def headline(results: dict[str, Any]) -> str:
    """A markdown table of the main rates, to paste verbatim into docs/BACKTEST.md."""
    def rate(m: dict) -> str:
        if m["rate"] is None:
            return f"n={m['n']}: no trials"
        low, high = m["wilson95"]
        return f"{m['hits']}/{m['n']} = {m['rate']} (Wilson 95% {low}-{high})"

    rows = ["| Grid | Metric | Result |", "|---|---|---|"]
    for name, r in results["results"].items():
        rows.append(f"| {name} | P80 coverage, non-December (nominal 0.8) | {rate(r['p80_coverage_non_december'])} |")
        rows.append(f"| {name} | December conservative coverage | {rate(r['december_conservative_coverage'])} |")
        rows.append(f"| {name} | Freelance income P20 coverage (nominal 0.8) | {rate(r['freelance_income_p20_coverage'])} |")
        e = r["p50_signed_relative_error_non_december"]
        rows.append(f"| {name} | P50 signed relative error (n={e['n']}) | median {e['median']}, p10 {e['p10']}, p90 {e['p90']}, mean abs {e['mean_abs']} |")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--out", type=Path, default=Path("../evidence/backtest/synthetic_backtest.json"))
    args = parser.parse_args(argv)
    results = run(args.seeds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(results), encoding="utf-8")
    print(f"wrote {args.out}")
    print(headline(results), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
