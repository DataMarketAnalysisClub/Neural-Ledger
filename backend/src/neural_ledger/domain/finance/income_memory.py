"""A declared salary in the income model: by decomposition, never by difference (ADR-049 §5-9).

The observed income is the estimator's percentiles over everything credited in the window. With a declared salary,
the salary is taken out of that history and the declaration put in its place:

    typical(m)      = others_P50 + d(m)
    conservative(m) = others_P20 + s(m)

for cycle m, funded by pay month m - 1. `d(m)` is the version that applies to m - 1. `others` is the estimator's own
series (canonical window, income rules and quantiles, never a copy) without the salary identified in each cycle.
`s(m)` is what the statements support: min(d, median of the version's matched credits) with two or more of them;
otherwise min(d, the previous version's level), that same rule applied to it. With no supported level at all, the
conservative income is the lower of the observed one and others_P20 + d: a declared decrease always counts, a raise
never lifts it.

No effect (the observed income in every cycle) when: there is no declaration; the income is a contracted net (the
personas); the chain is in conflict (SALARY_CONFLICT); or the salary is not identified in every cycle of the window
(SALARY_UNIDENTIFIED), which also covers a first declaration with no verified base. Because the raised salary leaves
the others' series by txn_id, a raise is counted once even after it reaches the history.

`with_income_memory` puts the overlay in the model the forecast, stress, plan, purchase, surplus and capacity read
(they take each cycle's income from the calendar), and its fingerprint in `source_version`, so every snapshot id
tells results with different memory apart. The `estimate.*` facts stay the observed ones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction

from ..memory.catalog import Declaration, applicable, chain, previous
from ..memory.salary_check import PROPOSED_RULES, Outcome, SalaryCheck, SalaryRules, Status
from ..shared.envelope import Caveat, Fact
from ..shared.hashing import content_id
from ..shared.month import Month
from ..shared.numbers import round_half_up
from .estimation import CanonicalWindow, income_credits, income_percentiles, income_series, quantile
from .model import FinancialModel, IncomeModel, IncomeStep
from .params import FinanceParams

# Each message says whether the declaration is applied or only saved, and never calls it a credited salary.
_MENTION = ("declar",)
RAISE_ASSUMED = Caveat(
    "INCOME_RAISE_ASSUMED",
    "Applied: the typical scenario uses the salary you declared; your statements do not show it yet, so the "
    "conservative scenario keeps the level they support.",
    _MENTION,
)
SALARY_DIFFERS = Caveat(
    "SALARY_DIFFERS",
    "Applied: the salary credits in your statements are below the salary you declared; the conservative scenario "
    "uses the lower amount.",
    _MENTION,
)
SALARY_CONFLICT = Caveat(
    "SALARY_CONFLICT",
    "Saved only: two paydays in a row show no credit close to the salary you declared, so the forecast uses what "
    "your statements show until you confirm your salary again.",
    _MENTION,
)
SALARY_UNIDENTIFIED = Caveat(
    "SALARY_UNIDENTIFIED",
    "Saved only: the salary you declared could not be found in every month your forecast is estimated from, so it "
    "uses what your statements show.",
    _MENTION,
)


@dataclass(frozen=True, slots=True)
class SalaryBasis:
    """What one income step rests on: the declared amount and the level the statements support (None: no level)."""

    start: Month
    declared: int
    supported: int | None


@dataclass(frozen=True, slots=True)
class IncomeOverlay:
    applied: bool
    income: IncomeModel  # the observed model, with its per-cycle steps when applied
    warnings: tuple[Caveat, ...]
    others_typical: Fraction | None = None
    others_conservative: Fraction | None = None
    fingerprint: str | None = None  # declarations, evidence and rules used; None without declarations
    basis: tuple[SalaryBasis, ...] = ()  # one per income step when applied


def overlay_income(
    model: FinancialModel,
    window: CanonicalWindow,
    declarations: Sequence[Declaration],
    check: SalaryCheck | None,
    params: FinanceParams,
    rules: SalaryRules = PROPOSED_RULES,
) -> IncomeOverlay:
    observed = model.income
    versions = chain(declarations)
    if not versions or check is None or observed.method != "percentile":
        return IncomeOverlay(False, observed, ())
    fingerprint = content_id("income-memory", versions, check.evidence, rules, params.version)
    if check.status is Status.CONFLICT:
        return IncomeOverlay(False, observed, (SALARY_CONFLICT,), fingerprint=fingerprint)

    evidence = {e.pay_month: e for e in check.evidence}
    identified: set[str] = set()
    for cycle in window.window:
        found = evidence.get(cycle.plus(-1))
        if found is None or found.outcome is not Outcome.MATCHED or found.credit is None:
            return IncomeOverlay(False, observed, (SALARY_UNIDENTIFIED,), fingerprint=fingerprint)
        identified.add(found.credit.txn_id)

    others = [(t, c) for t, c in income_credits(window.in_window) if t.txn_id not in identified]
    others_typical, others_conservative = income_percentiles(income_series(others, window.window), params)

    starts = sorted({window.first_cycle} | {v.effective_from.plus(1) for v in versions if v.effective_from.plus(1) > window.first_cycle})
    steps: list[IncomeStep] = []
    basis: list[SalaryBasis] = []
    warnings: list[Caveat] = []
    for start in starts:
        version = applicable(versions, start.plus(-1))
        if version is None:  # every window cycle had a matched version, so this cannot happen; keep the observed
            steps.append(IncomeStep(start, observed.typical, observed.conservative))
            continue
        declared = version.value.amount
        level = _level(versions, version, check, rules)
        typical = round_half_up(others_typical + declared)
        if level is None:
            conservative = min(observed.conservative, round_half_up(others_conservative + declared))
        else:
            conservative = round_half_up(others_conservative + level)
        if level is None or level < declared:
            supported = len(check.matched_amounts(version.version)) >= rules.raise_confirm_cycles
            warnings.append(SALARY_DIFFERS if supported else RAISE_ASSUMED)
        steps.append(IncomeStep(start, typical, conservative))
        basis.append(SalaryBasis(start, declared, None if level is None else round_half_up(level)))
    unique = tuple(dict.fromkeys(warnings))
    return IncomeOverlay(
        True, replace(observed, monthly=tuple(steps)), unique, others_typical, others_conservative, fingerprint, tuple(basis)
    )


def with_income_memory(model: FinancialModel, overlay: IncomeOverlay) -> FinancialModel:
    """The model the projections read. Unchanged without declarations; otherwise the fingerprint joins its
    source_version even when memory is only saved, because the warnings differ."""
    if overlay.fingerprint is None:
        return model
    return replace(model, income=overlay.income, source_version=f"{model.source_version}+memory:{overlay.fingerprint}")


def overlay_facts(overlay: IncomeOverlay, currency: str) -> tuple[Fact, ...]:
    """The numbers behind an applied overlay, so the agent can say what the forecast rests on."""
    if not overlay.applied or overlay.others_typical is None or overlay.others_conservative is None:
        return ()
    facts = [
        Fact("income.others.typical", round_half_up(overlay.others_typical), currency, "income other than the declared salary (P50)"),
        Fact("income.others.conservative", round_half_up(overlay.others_conservative), currency, "income other than the declared salary (P20)"),
    ]
    for b in overlay.basis:
        m = str(b.start)
        facts.append(Fact(f"income.{m}.declared_salary", b.declared, currency, "salary you declared (user memory)"))
        if b.supported is not None:
            facts.append(Fact(f"income.{m}.supported_salary", b.supported, currency, "salary your statements support"))
    return tuple(facts)


def _level(versions: Sequence[Declaration], version: Declaration, check: SalaryCheck, rules: SalaryRules) -> Fraction | None:
    """The salary the statements support for a version (s in ADR-049 §6): never above what it declares."""
    matched = check.matched_amounts(version.version)
    declared = Fraction(version.value.amount)
    if len(matched) >= rules.raise_confirm_cycles:
        return min(declared, quantile(matched, Fraction(1, 2)))
    before = previous(versions, version)
    if before is None:
        return None
    level = _level(versions, before, check, rules)
    return None if level is None else min(declared, level)

