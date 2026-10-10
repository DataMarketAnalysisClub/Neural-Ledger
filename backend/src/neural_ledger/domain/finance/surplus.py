"""Protected surplus (Financial Core 4.5). We never call this money "safe".

    PS(h) = min over m <= h of [ B_0 - Floor + sum_(k<=m) (A_k - R_k - P_k) ]
i.e. the smallest conservative headroom: how much could leave checking today without
any conservative trough falling below the floor, with the plan (and purchases) included.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..shared.envelope import Fact
from ..shared.month import Month
from .forecast import Recurring, Scenario, project
from .model import FinancialModel
from .params import FinanceParams


@dataclass(frozen=True, slots=True)
class FreeFlow:
    month: Month
    amount: int  # available - plan - purchases


@dataclass(frozen=True, slots=True)
class SurplusResult:
    protected_surplus: int
    binding_month: Month
    horizon_months: int
    plan_amount: int
    plan_start: Month | None
    monthly_free_flow: tuple[FreeFlow, ...]
    breaches: tuple[Month, ...]


def protected_surplus(
    model: FinancialModel,
    params: FinanceParams,
    horizon: int,
    plan: Recurring | None = None,
    purchases: tuple[Recurring, ...] = (),
) -> SurplusResult:
    f = project(model, params, Scenario.CONSERVATIVE, horizon, plan=plan, purchases=purchases)
    lowest = f.lowest
    flows = tuple(FreeFlow(c.month, c.available - c.plan - c.purchase) for c in f.cycles)
    return SurplusResult(
        protected_surplus=lowest.headroom,
        binding_month=lowest.month,
        horizon_months=horizon,
        plan_amount=plan.amount if plan else 0,
        plan_start=plan.start if plan else None,
        monthly_free_flow=flows,
        breaches=f.breaches,
    )


def surplus_facts(result: SurplusResult, currency: str) -> tuple[Fact, ...]:
    facts = [
        Fact("protected_surplus", result.protected_surplus, currency, "min conservative headroom over the horizon"),
        Fact("protected_surplus.binding_month", str(result.binding_month), "month", "month of the minimum"),
        Fact("plan.amount", result.plan_amount, currency, "plan included in the path (0 = none)"),
    ]
    facts += [Fact(f"{f.month}.free_flow", f.amount, currency, "available - plan - purchases") for f in result.monthly_free_flow]
    return tuple(facts)
