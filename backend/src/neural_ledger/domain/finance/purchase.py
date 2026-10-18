"""Purchase simulator (Financial Core 4.6).

The purchase is a commitment overlay; typical and conservative are re-run over
max(check horizon, last installment). Alternatives are deterministic and re-simulated.
Drawing down the reserve is never offered.

Correction to the design doc (docs/SCOPE.md, issue F3): the largest affordable cuota is
    c_max = min over months m >= first cuota of  H_m / k_m
where k_m is the number of cuotas paid by month m, because cuotas accumulate in the
trough. The doc's "smallest headroom" is only right when the first month binds.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..shared.envelope import Caveat, Fact
from ..shared.errors import InvalidInput
from ..shared.month import Month
from ..shared.numbers import floor_to
from .forecast import Forecast, Recurring, Scenario, project
from .installments import InstallmentQuote, max_principal, percent, quote
from .model import FinancialModel
from .params import FinanceParams


class Verdict(str, Enum):
    BASELINE_BREACH = "BASELINE_BREACH"  # conservative already breaches without the purchase
    FITS_ALL = "FITS_ALL"
    FITS_TYPICAL_ONLY = "FITS_TYPICAL_ONLY"
    BREACHES_ALL = "BREACHES_ALL"


class AlternativeKind(str, Enum):
    DEFER_START = "defer_start"
    CHANGE_INSTALLMENTS = "change_installments"
    REDUCE_AMOUNT = "reduce_amount"


@dataclass(frozen=True, slots=True)
class ScenarioImpact:
    scenario: Scenario
    lowest_headroom_before: int
    lowest_headroom_after: int
    binding_month_after: Month
    trough_after_in_binding_month: int
    breaches_after: tuple[Month, ...]


@dataclass(frozen=True, slots=True)
class Alternative:
    kind: AlternativeKind
    amount: int
    installments: int
    first_installment_month: Month
    installment: int
    total_cost: int
    total_interest: int


@dataclass(frozen=True, slots=True)
class PurchaseSimulation:
    quote: InstallmentQuote
    first_installment_month: Month
    horizon_months: int
    verdict: Verdict
    impacts: tuple[ScenarioImpact, ...]
    alternatives: tuple[Alternative, ...]

    def impact(self, scenario: Scenario) -> ScenarioImpact:
        return next(i for i in self.impacts if i.scenario is scenario)


def default_first_installment(model: FinancialModel) -> Month:
    """Bought during the first projected cycle, billed on the next statement."""
    return model.first_cycle.plus(1)


def validate_purchase(
    model: FinancialModel, params: FinanceParams, amount: int, installments: int, first: Month
) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= params.max_purchase_amount:
        raise InvalidInput("amount", f"amount must be an integer from 1 to {params.max_purchase_amount}")
    if isinstance(installments, bool) or not isinstance(installments, int) or not 1 <= installments <= params.max_installments:
        raise InvalidInput("installments", f"installments must be an integer from 1 to {params.max_installments}")
    if first < model.first_cycle:
        raise InvalidInput("first_installment_month", f"first installment cannot be before {model.first_cycle}")


def evaluation_horizon(model: FinancialModel, params: FinanceParams, first: Month, installments: int) -> int:
    last = first.plus(installments - 1)
    return max(params.check_horizon_months, model.first_cycle.months_until(last) + 1)


def _overlay(q: InstallmentQuote, first: Month) -> Recurring:
    return Recurring(q.installment, first, first.plus(q.installments - 1))


def _impact(before: Forecast, after: Forecast) -> ScenarioImpact:
    lowest = after.lowest
    return ScenarioImpact(
        scenario=after.scenario,
        lowest_headroom_before=before.lowest.headroom,
        lowest_headroom_after=lowest.headroom,
        binding_month_after=lowest.month,
        trough_after_in_binding_month=lowest.trough,
        breaches_after=after.breaches,
    )


def _evaluate(
    model: FinancialModel, params: FinanceParams, q: InstallmentQuote, first: Month, plan: Recurring | None
) -> tuple[Verdict, tuple[ScenarioImpact, ...]]:
    horizon = evaluation_horizon(model, params, first, q.installments)
    overlay = (_overlay(q, first),)
    impacts = []
    breached: dict[Scenario, bool] = {}
    baseline_breach = False
    for scenario in (Scenario.TYPICAL, Scenario.CONSERVATIVE):
        before = project(model, params, scenario, horizon, plan=plan)
        after = project(model, params, scenario, horizon, plan=plan, purchases=overlay)
        impacts.append(_impact(before, after))
        breached[scenario] = bool(after.breaches)
        if scenario is Scenario.CONSERVATIVE and before.breaches:
            baseline_breach = True
    if baseline_breach:
        verdict = Verdict.BASELINE_BREACH
    elif not breached[Scenario.CONSERVATIVE]:
        verdict = Verdict.FITS_ALL
    elif not breached[Scenario.TYPICAL]:
        verdict = Verdict.FITS_TYPICAL_ONLY
    else:
        verdict = Verdict.BREACHES_ALL
    return verdict, tuple(impacts)


def installment_cap(
    model: FinancialModel, params: FinanceParams, first: Month, installments: int, plan: Recurring | None
) -> int:
    """Largest cuota that keeps every conservative trough at or above the floor."""
    horizon = evaluation_horizon(model, params, first, installments)
    base = project(model, params, Scenario.CONSERVATIVE, horizon, plan=plan)
    caps = []
    for c in base.cycles:
        if c.month < first:
            if c.headroom < 0:
                return 0
            continue
        paid = min(installments, first.months_until(c.month) + 1)
        caps.append(c.headroom // paid if c.headroom >= 0 else -1)
    return max(0, min(caps)) if caps else 0


def simulate_purchase(
    model: FinancialModel,
    params: FinanceParams,
    amount: int,
    installments: int,
    first: Month,
    monthly_rate: Decimal | None = None,
    plan: Recurring | None = None,
) -> PurchaseSimulation:
    validate_purchase(model, params, amount, installments, first)
    rate_assumed = monthly_rate is None
    rate = params.default_monthly_rate if monthly_rate is None else Decimal(monthly_rate)
    if not Decimal(0) <= rate <= Decimal("0.2"):
        raise InvalidInput("monthly_rate", "monthly_rate must be between 0 and 0.2")
    q = quote(amount, installments, rate, rate_assumed=rate_assumed)
    verdict, impacts = _evaluate(model, params, q, first, plan)
    alternatives: tuple[Alternative, ...] = ()
    if verdict in (Verdict.FITS_TYPICAL_ONLY, Verdict.BREACHES_ALL):
        alternatives = _alternatives(model, params, q, first, plan)
    return PurchaseSimulation(
        quote=q,
        first_installment_month=first,
        horizon_months=evaluation_horizon(model, params, first, installments),
        verdict=verdict,
        impacts=impacts,
        alternatives=alternatives,
    )


def _as_alternative(kind: AlternativeKind, q: InstallmentQuote, first: Month) -> Alternative:
    return Alternative(kind, q.principal, q.installments, first, q.installment, q.total_cost, q.total_interest)


def _alternatives(
    model: FinancialModel, params: FinanceParams, q: InstallmentQuote, first: Month, plan: Recurring | None
) -> tuple[Alternative, ...]:
    found: list[Alternative] = []
    # (a) the earliest first-installment month that fits
    for k in range(1, params.alternative_defer_max_months + 1):
        start = first.plus(k)
        if _evaluate(model, params, q, start, plan)[0] is Verdict.FITS_ALL:
            found.append(_as_alternative(AlternativeKind.DEFER_START, q, start))
            break
    # (b) another installment count that fits, lowest total interest first
    fitting = []
    for n in params.suggested_installments:
        if n == q.installments:
            continue
        candidate = quote(q.principal, n, q.monthly_rate, rate_assumed=q.rate_assumed)
        if _evaluate(model, params, candidate, first, plan)[0] is Verdict.FITS_ALL:
            fitting.append(candidate)
    if fitting:
        best = min(fitting, key=lambda c: (c.total_interest, c.installments))
        found.append(_as_alternative(AlternativeKind.CHANGE_INSTALLMENTS, best, first))
    # (c) the largest amount that fits at the requested terms
    cap = installment_cap(model, params, first, q.installments, plan)
    amount = floor_to(max_principal(cap, q.installments, q.monthly_rate), params.approx_rounding)
    for _ in range(10):
        if not 0 < amount < q.principal:
            break
        candidate = quote(amount, q.installments, q.monthly_rate, rate_assumed=q.rate_assumed)
        if _evaluate(model, params, candidate, first, plan)[0] is Verdict.FITS_ALL:
            found.append(_as_alternative(AlternativeKind.REDUCE_AMOUNT, candidate, first))
            break
        amount -= params.approx_rounding
    return tuple(found[: params.max_alternatives])


def purchase_facts(sim: PurchaseSimulation, currency: str) -> tuple[Fact, ...]:
    q = sim.quote
    facts = [
        Fact("purchase.amount", q.principal, currency, "requested"),
        Fact("purchase.installments", q.installments, "count", "requested"),
        Fact("purchase.first_installment_month", str(sim.first_installment_month), "month", "requested or default"),
        Fact("purchase.installment", q.installment, currency, "P*r/(1-(1+r)^-n), rounded to the unit"),
        Fact("purchase.total_cost", q.total_cost, currency, "n * installment"),
        Fact("purchase.total_interest", q.total_interest, currency, "total cost - amount"),
        Fact("purchase.monthly_rate_pct", percent(q.monthly_rate, 2), "%", "offer or assumed default"),
        Fact("purchase.effective_annual_rate_pct", percent(q.effective_annual_rate), "%", "(1+r)^12 - 1"),
        Fact("purchase.verdict", sim.verdict.value, "verdict", "typical and conservative re-run with the overlay"),
    ]
    for i in sim.impacts:
        s = i.scenario.value
        facts += [
            Fact(f"purchase.{s}.lowest_headroom_before", i.lowest_headroom_before, currency, "without purchase"),
            Fact(f"purchase.{s}.lowest_headroom_after", i.lowest_headroom_after, currency, "with purchase"),
            Fact(f"purchase.{s}.binding_month_after", str(i.binding_month_after), "month", "with purchase"),
            Fact(f"purchase.{s}.trough_after", i.trough_after_in_binding_month, currency, "binding month trough"),
        ]
    for n, alt in enumerate(sim.alternatives, start=1):
        facts += [
            Fact(f"alternative_{n}.kind", alt.kind.value, "kind", "deterministic alternative"),
            Fact(f"alternative_{n}.amount", alt.amount, currency, "re-simulated, fits all scenarios"),
            Fact(f"alternative_{n}.installments", alt.installments, "count", "re-simulated"),
            Fact(f"alternative_{n}.first_installment_month", str(alt.first_installment_month), "month", "re-simulated"),
            Fact(f"alternative_{n}.installment", alt.installment, currency, "re-simulated"),
            Fact(f"alternative_{n}.total_cost", alt.total_cost, currency, "re-simulated"),
        ]
    return tuple(facts)


def purchase_caveats(sim: PurchaseSimulation) -> tuple[Caveat, ...]:
    caveats = []
    if sim.quote.rate_assumed:
        pct = percent(sim.quote.monthly_rate, 2)
        text = f"{pct:g}%"
        caveats.append(
            Caveat(
                "RATE_ASSUMED",
                f"Monthly rate assumed at {text} because the offer gives none.",
                (text, text.replace(".", ","), "assum", "supuest"),
            )
        )
    return tuple(caveats)
