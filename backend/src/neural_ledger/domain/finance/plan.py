"""Savings plan sizing and allocation (Financial Core 4.5 and 4.8).

    R = floor_10k( share(profile) * min over m in [s, s+5] of A_m ),   R <= Required
s = the earliest month where R > 0 and the conservative path with R never breaches over
the check horizon (hard rule H5). No such month -> no recurring rule (hard rule H2).
Allocation: reserve below minimum -> all to reserve (H1); otherwise near-term goals by
deadline, then the reserve top-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ..shared.envelope import Caveat, Fact
from ..shared.month import Month
from ..shared.numbers import ceil_div, floor_to, round_half_up
from .capacity import essentials_exact
from .forecast import Recurring, Scenario, project
from .model import FinancialModel
from .params import FinanceParams
from .profile import RiskProfile

H1 = "H1_RESERVE_BELOW_MINIMUM"
H2 = "H2_NO_POSITIVE_RULE"


@dataclass(frozen=True, slots=True)
class Allocation:
    bucket: str  # "reserve" | "goal:<id>"
    monthly_amount: int


@dataclass(frozen=True, slots=True)
class BucketRequirement:
    bucket: str
    required_monthly: int
    funded_monthly: int
    funded_from: Month | None  # when this bucket starts receiving money from the rule


@dataclass(frozen=True, slots=True)
class GoalStatus:
    goal_id: str
    name: str
    target: int
    saved: int
    deadline: Month
    required_monthly: int
    funded_monthly: int
    projected_completion: Month | None
    on_track: bool


@dataclass(frozen=True, slots=True)
class SavingsPlan:
    profile: RiskProfile
    amount: int
    start_month: Month | None
    share: Fraction
    lowest_available_in_window: int | None
    required_monthly: int
    allocation: tuple[Allocation, ...]
    requirements: tuple[BucketRequirement, ...]
    goal_status: tuple[GoalStatus, ...]
    hard_rules_triggered: tuple[str, ...]

    def as_recurring(self) -> Recurring | None:
        if self.amount <= 0 or self.start_month is None:
            return None
        return Recurring(self.amount, self.start_month)


def _near_term_goals(model: FinancialModel, params: FinanceParams):
    as_of = Month.of(model.as_of)
    goals = [g for g in model.goals if as_of.months_until(g.deadline) <= params.near_term_goal_months]
    return sorted(goals, key=lambda g: (g.deadline, g.goal_id))


def _goal_required(goal, start: Month) -> int:
    remaining = max(0, goal.target_amount - goal.saved_amount)
    months = max(1, start.months_until(goal.deadline) + 1)
    return ceil_div(remaining, months)


def _reserve_topup(model: FinancialModel, params: FinanceParams, target: Fraction) -> int:
    gap = target - model.balances.reserve
    return round_half_up(gap / params.reserve_rebuild_months) if gap > 0 else 0


def size_plan(
    model: FinancialModel,
    params: FinanceParams,
    profile: RiskProfile,
    purchases: tuple[Recurring, ...] = (),
) -> SavingsPlan:
    essentials = essentials_exact(model, params)
    reserve_min = params.reserve_min_months * essentials
    reserve_target = params.reserve_target_months * essentials
    share = params.share_for(profile)
    goals = _near_term_goals(model, params)
    first = model.first_cycle

    span = params.check_horizon_months + params.plan_window_months
    base = project(model, params, Scenario.CONSERVATIVE, span, purchases=purchases)
    available = {c.month: c.available - c.purchase for c in base.cycles}

    for i in range(params.check_horizon_months):
        start = first.plus(i)
        window = [start.plus(k) for k in range(params.plan_window_months)]
        lowest = min(available[m] for m in window)
        if lowest <= 0:
            continue
        topup = _reserve_topup(model, params, reserve_target)
        required = topup + sum(_goal_required(g, start) for g in goals)
        amount = floor_to(min(share * lowest, Fraction(required)), params.rule_rounding)
        if amount <= 0:
            continue
        rule = Recurring(amount, start)
        check = first.months_until(start.plus(params.check_horizon_months - 1)) + 1
        if project(model, params, Scenario.CONSERVATIVE, check, plan=rule, purchases=purchases).breaches:
            continue  # hard rule H5: a plan may never push a conservative trough below the floor
        return _allocate(model, profile, amount, start, share, lowest, required, topup, goals, reserve_min)

    return SavingsPlan(
        profile=profile,
        amount=0,
        start_month=None,
        share=share,
        lowest_available_in_window=None,
        required_monthly=0,
        allocation=(),
        requirements=(),
        goal_status=(),
        hard_rules_triggered=(H2,),
    )


def _allocate(model, profile, amount, start, share, lowest, required, topup, goals, reserve_min) -> SavingsPlan:
    if model.balances.reserve < reserve_min:
        return SavingsPlan(
            profile, amount, start, share, lowest, required,
            allocation=(Allocation("reserve", amount),),
            requirements=(BucketRequirement("reserve", topup, amount, start),),
            goal_status=(),
            hard_rules_triggered=(H1,),
        )

    remaining = amount
    allocation: list[Allocation] = []
    requirements: list[BucketRequirement] = []
    statuses: list[GoalStatus] = []
    last_completion: Month | None = None
    for goal in goals:
        need = _goal_required(goal, start)
        give = min(remaining, need)
        remaining -= give
        completion = None
        if give > 0:
            months = ceil_div(max(0, goal.target_amount - goal.saved_amount), give)
            completion = start.plus(months - 1)
            allocation.append(Allocation(f"goal:{goal.goal_id}", give))
            last_completion = completion if last_completion is None else max(last_completion, completion)
        requirements.append(BucketRequirement(f"goal:{goal.goal_id}", need, give, start if give else None))
        statuses.append(
            GoalStatus(
                goal.goal_id, goal.name, goal.target_amount, goal.saved_amount, goal.deadline,
                need, give, completion, completion is not None and completion <= goal.deadline,
            )
        )
    if remaining > 0:
        allocation.append(Allocation("reserve", remaining))
        reserve_from = start
    else:
        reserve_from = last_completion.plus(1) if last_completion else None
    requirements.append(BucketRequirement("reserve", topup, remaining, reserve_from))
    return SavingsPlan(
        profile, amount, start, share, lowest, required,
        allocation=tuple(allocation),
        requirements=tuple(requirements),
        goal_status=tuple(statuses),
        hard_rules_triggered=(),
    )


def plan_caveats(plan: SavingsPlan) -> tuple[Caveat, ...]:
    """H3 as an emitted warning (UG03, ESMA GL8): a near-term goal the plan cannot finish by its deadline.

    goal_status only holds near-term goals (within near_term_goal_months), so a later goal never warns. The
    warning changes no amount: the plan is still the largest rule the profile allows. It names the goal and no
    figure, so the explanation can repeat it word for word and the agent must mention the goal.
    """
    return tuple(
        Caveat(
            "GOAL_OFF_TRACK",
            f"At this rate your {g.name} goal will not be complete by its deadline.",
            (g.name,),
        )
        for g in plan.goal_status
        if not g.on_track
    )


def plan_facts(plan: SavingsPlan, currency: str) -> tuple[Fact, ...]:
    facts = [
        Fact("plan.profile", plan.profile.value, "profile", "permitted profile used for sizing"),
        Fact("plan.amount", plan.amount, currency, "share x lowest available in window, rounded down"),
        Fact("plan.start_month", str(plan.start_month) if plan.start_month else "none", "month", "earliest month that never breaches"),
        Fact("plan.share_pct", round(float(plan.share) * 100, 1), "%", "profile share"),
        Fact("plan.required_monthly", plan.required_monthly, currency, "reserve top-up + near-term goal funding"),
    ]
    if plan.lowest_available_in_window is not None:
        facts.append(Fact("plan.lowest_available", plan.lowest_available_in_window, currency, "min Available in the sizing window"))
    for a in plan.allocation:
        facts.append(Fact(f"allocation.{a.bucket}", a.monthly_amount, currency, "allocation cascade"))
    for r in plan.requirements:
        facts += [
            Fact(f"requirement.{r.bucket}.required", r.required_monthly, currency, "monthly amount to stay on schedule"),
            Fact(f"requirement.{r.bucket}.funded_from", str(r.funded_from) if r.funded_from else "none", "month", "first month funded by the rule"),
        ]
    for g in plan.goal_status:
        facts += [
            Fact(f"goal.{g.goal_id}.target", g.target, currency, "goal"),
            Fact(f"goal.{g.goal_id}.saved", g.saved, currency, "goal bucket"),
            Fact(f"goal.{g.goal_id}.projected_completion", str(g.projected_completion) if g.projected_completion else "none", "month", "at the funded rate"),
        ]
    for h in plan.hard_rules_triggered:
        facts.append(Fact(f"hard_rule.{h}", "triggered", "rule", "hard rules H1-H5"))
    return tuple(facts)
