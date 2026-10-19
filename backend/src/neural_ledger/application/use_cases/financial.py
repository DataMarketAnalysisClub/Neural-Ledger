"""Financial use cases (Role A engines behind the read-only tools T0/T1).

Each method loads the model, runs pure domain code and returns an Envelope with
snapshot_id, params_version, facts and warnings. Inputs outside the contract return
INVALID_INPUT and touch no engine; missing data returns INSUFFICIENT_DATA (hard rule H4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, TypeVar

from ...domain.actions.terms import liquidity_floor_from, savings_rules
from ...domain.agent.untrusted import wrap_untrusted
from ...domain.finance.capacity import (
    CapacityAssessment,
    assess_capacity,
    capacity_facts,
)
from ...domain.finance.forecast import (
    Forecast,
    Recurring,
    Scenario,
    forecast_facts,
    project,
)
from ...domain.finance.model import FinancialModel
from ...domain.finance.params import FinanceParams
from ...domain.finance.permitted import (
    PermittedProfile,
    derive_permitted_profile,
    permitted_facts,
)
from ...domain.finance.plan import SavingsPlan, plan_facts, size_plan
from ...domain.finance.profile import RiskProfile, lower_profile
from ...domain.finance.purchase import (
    PurchaseSimulation,
    default_first_installment,
    purchase_caveats,
    purchase_facts,
    simulate_purchase,
)
from ...domain.finance.surplus import SurplusResult, protected_surplus, surplus_facts
from ...domain.shared.envelope import Caveat, Envelope, Fact
from ...domain.shared.errors import InsufficientData, InvalidInput
from ...domain.shared.hashing import content_id
from ...domain.shared.month import Month, month_range
from ..ports import (
    FinancialModelSource,
    NotFound,
    SandboxBank,
    SnapshotStore,
    UserProfileStore,
)

T = TypeVar("T")
MAX_HORIZON = 24


class IncludePlan(str, Enum):
    NONE = "none"
    RECOMMENDED = "recommended"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class FinancialStateView:
    user_id: str
    currency: str
    as_of: str
    first_cycle: Month
    checking: int
    reserve: int
    goal_buckets: dict[str, int]
    income_type: str
    active_rules: int


@dataclass(frozen=True, slots=True)
class CommitmentView:
    commitment_id: str
    type: str
    label: dict[str, str]  # {"untrusted_text": ...}
    amount: int
    first_due: Month
    last_due: Month | None
    is_debt: bool


@dataclass(frozen=True, slots=True)
class MonthTotal:
    month: Month
    total: int
    debt: int


@dataclass(frozen=True, slots=True)
class CommitmentsView:
    horizon_months: int
    commitments: tuple[CommitmentView, ...]
    schedule: tuple[MonthTotal, ...]


@dataclass(frozen=True, slots=True)
class StoredPlan:
    """What a plan snapshot id points to. Proposals read the amount from here."""

    plan: SavingsPlan
    currency: str
    user_id: str


class FinancialUseCases:
    def __init__(
        self,
        source: FinancialModelSource,
        snapshots: SnapshotStore,
        bank: SandboxBank,
        profiles: UserProfileStore,
        params: FinanceParams,
    ) -> None:
        self._source = source
        self._snapshots = snapshots
        self._bank = bank
        self._profiles = profiles
        self._params = params

    @property
    def params(self) -> FinanceParams:
        return self._params

    # ---- plumbing -------------------------------------------------------------------------

    def _run(self, user_id: str, body: Callable[[FinancialModel], Envelope[T]]) -> Envelope[T]:
        version = self._params.version
        try:
            model = self._source.load(user_id)
        except NotFound as exc:
            return Envelope.insufficient(("financial_model",), params_version=version, message=str(exc))
        except InsufficientData as exc:
            return Envelope.insufficient(exc.missing, params_version=version, message=exc.message)
        except InvalidInput as exc:
            return Envelope.invalid(exc.field, exc.allowed, params_version=version, message=exc.message)
        missing = model.missing_fields()
        if missing:
            return Envelope.insufficient(missing, params_version=version, message="financial state is incomplete")
        try:
            return body(model)
        except InvalidInput as exc:
            return Envelope.invalid(exc.field, exc.allowed, params_version=version, message=exc.message)
        except InsufficientData as exc:
            return Envelope.insufficient(exc.missing, params_version=version, message=exc.message)

    def _user_floor(self, user_id: str) -> int | None:
        """The user's own liquidity floor from an executed floor rule (ADR-037), or None for the parameter register's."""
        return liquidity_floor_from(self._bank.active_rules(user_id))

    def _params_for(self, model: FinancialModel) -> FinanceParams:
        """The parameter register with the user's floor in place of its own, when the user set one (ADR-037)."""
        floor = self._user_floor(model.user_id)
        return self._params if floor is None else replace(self._params, liquidity_floor=floor)

    def _ok(self, model: FinancialModel, data: T, facts, warnings=(), *, kind: str, parts: tuple = ()) -> Envelope[T]:
        floor = self._user_floor(model.user_id)
        if floor is not None:  # the same data with another floor is another snapshot
            parts = (*parts, ("liquidity_floor", floor))
        snapshot_id = content_id(kind, model.source_version, model.as_of, self._params.version, *parts)
        return Envelope.success(
            data,
            params_version=self._params.version,
            snapshot_id=snapshot_id,
            as_of=model.as_of.isoformat(),
            facts=tuple(facts),
            warnings=tuple(warnings),
        )

    def context(self, user_id: str) -> tuple[str, str]:
        """(as_of, currency) for prompts and verification. Defaults if the user is unknown."""
        try:
            model = self._source.load(user_id)
        except (NotFound, InsufficientData, InvalidInput):
            return ("unknown", "CLP")
        return (model.as_of.isoformat(), model.currency)

    def first_cycle(self, user_id: str) -> tuple[Month, str] | Envelope[Any]:
        """(first projected cycle, currency) for a rule that starts now, or the INSUFFICIENT_DATA envelope."""
        def body(model: FinancialModel) -> Envelope[tuple[Month, str]]:
            return Envelope.success((model.first_cycle, model.currency), params_version=self._params.version, snapshot_id="cycle", as_of=model.as_of.isoformat())

        result = self._run(user_id, body)
        return result.data if result.ok and result.data is not None else result

    def _floor_fact(self, model: FinancialModel) -> Fact:
        floor = self._user_floor(model.user_id)
        if floor is None:
            return Fact("liquidity_floor", self._params.liquidity_floor, model.currency, "parameter register")
        return Fact("liquidity_floor", floor, model.currency, "your liquidity floor rule")

    @staticmethod
    def _horizon(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HORIZON:
            raise InvalidInput("horizon_months", f"horizon_months must be an integer from 1 to {MAX_HORIZON}")
        return value

    def _tolerance(self, user_id: str) -> RiskProfile:
        profile = self._profiles.get(user_id)
        if profile and profile.declared_tolerance:
            return profile.declared_tolerance
        return RiskProfile.CONSERVATIVE

    def _permitted(self, model: FinancialModel) -> PermittedProfile:
        return derive_permitted_profile(self._tolerance(model.user_id), assess_capacity(model, self._params_for(model)), model)

    def _plan_overlay(self, model: FinancialModel, include: IncludePlan) -> Recurring | None:
        if include is IncludePlan.NONE:
            return None
        if include is IncludePlan.RECOMMENDED:
            return size_plan(model, self._params_for(model), self._permitted(model).permitted).as_recurring()
        rules = savings_rules(self._bank.active_rules(model.user_id))
        if not rules:
            return None
        start = min(Month.of(r.effective_date) for r in rules)
        return Recurring(sum(r.amount for r in rules), start)

    # ---- T0 ---------------------------------------------------------------------------------

    def financial_state(self, user_id: str) -> Envelope[FinancialStateView]:
        def body(model: FinancialModel) -> Envelope[FinancialStateView]:
            b = model.balances
            view = FinancialStateView(
                user_id=model.user_id,
                currency=model.currency,
                as_of=model.as_of.isoformat(),
                first_cycle=model.first_cycle,
                checking=b.checking,
                reserve=b.reserve,
                goal_buckets=dict(b.goal_buckets),
                income_type=model.income.type.value,
                active_rules=len(self._bank.active_rules(user_id)),
            )
            facts = [
                Fact("balance.checking", b.checking, model.currency, "opening trough"),
                Fact("balance.reserve", b.reserve, model.currency, "savings bucket"),
            ]
            facts += [Fact(f"balance.goal.{k}", v, model.currency, "savings bucket") for k, v in b.goal_buckets.items()]
            return self._ok(model, view, facts, kind="state")

        return self._run(user_id, body)

    def commitments(self, user_id: str, horizon_months: int = 6) -> Envelope[CommitmentsView]:
        def body(model: FinancialModel) -> Envelope[CommitmentsView]:
            horizon = self._horizon(horizon_months)
            months = month_range(model.first_cycle, horizon)
            active = [c for c in model.commitments if any(c.due_in(m) for m in months)]
            views = tuple(
                CommitmentView(c.commitment_id, c.type.value, wrap_untrusted(c.label), c.amount, c.first_due, c.last_due, c.is_debt)
                for c in active
            )
            schedule = tuple(MonthTotal(m, model.commitments_due(m), model.debt_service_due(m)) for m in months)
            facts = [Fact(f"{s.month}.commitments_total", s.total, model.currency, "commitment schedule") for s in schedule]
            facts += [Fact(f"commitment.{c.commitment_id}.amount", c.amount, model.currency, "per due month") for c in active]
            return self._ok(model, CommitmentsView(horizon, views, schedule), facts, kind="commitments", parts=(horizon,))

        return self._run(user_id, body)

    # ---- T1 ---------------------------------------------------------------------------------

    def forecast(
        self, user_id: str, horizon_months: int = 6, scenario: str = "conservative", include_plan: str = "none"
    ) -> Envelope[Forecast]:
        def body(model: FinancialModel) -> Envelope[Forecast]:
            horizon = self._horizon(horizon_months)
            scen = _parse_enum(Scenario, scenario, "scenario")
            include = _parse_enum(IncludePlan, include_plan, "include_plan")
            plan = self._plan_overlay(model, include)
            result = project(model, self._params_for(model), scen, horizon, plan=plan)
            parts = (horizon, scen, include, plan)
            return self._ok(model, result, forecast_facts(result, model.currency), kind="forecast", parts=parts)

        return self._run(user_id, body)

    def simulate_purchase(
        self,
        user_id: str,
        amount: Any,
        installments: Any,
        first_installment_month: str | None = None,
        monthly_rate: Any = None,
        include_plan: str = "none",
    ) -> Envelope[PurchaseSimulation]:
        def body(model: FinancialModel) -> Envelope[PurchaseSimulation]:
            caveats: list[Caveat] = []
            if first_installment_month:
                first = _parse_month(first_installment_month, "first_installment_month")
            else:
                first = default_first_installment(model)
                caveats.append(
                    Caveat(
                        "FIRST_INSTALLMENT_ASSUMED",
                        f"I assumed the first cuota is billed in {first}.",
                        (str(first), "assum", "supuse"),
                    )
                )
            rate = _parse_rate(monthly_rate)
            include = _parse_enum(IncludePlan, include_plan, "include_plan")
            plan = self._plan_overlay(model, include)
            principal = _parse_int(amount, "amount")
            count = _parse_int(installments, "installments")
            sim = simulate_purchase(model, self._params_for(model), principal, count, first, rate, plan)
            facts = (*purchase_facts(sim, model.currency), self._floor_fact(model))
            parts = (principal, count, first, str(rate), include, plan)
            return self._ok(model, sim, facts, (*purchase_caveats(sim), *caveats), kind="purchase", parts=parts)

        return self._run(user_id, body)

    def protected_surplus(self, user_id: str, horizon_months: int = 6, include_plan: str = "none") -> Envelope[SurplusResult]:
        def body(model: FinancialModel) -> Envelope[SurplusResult]:
            horizon = self._horizon(horizon_months)
            include = _parse_enum(IncludePlan, include_plan, "include_plan")
            plan = self._plan_overlay(model, include)
            result = protected_surplus(model, self._params_for(model), horizon, plan)
            facts = (*surplus_facts(result, model.currency), self._floor_fact(model))
            return self._ok(model, result, facts, kind="surplus", parts=(horizon, include, plan))

        return self._run(user_id, body)

    def capacity(self, user_id: str) -> Envelope[CapacityAssessment]:
        def body(model: FinancialModel) -> Envelope[CapacityAssessment]:
            result = assess_capacity(model, self._params_for(model))
            return self._ok(model, result, capacity_facts(result, model.currency), kind="capacity")

        return self._run(user_id, body)

    def permitted_profile(self, user_id: str, tolerance: str) -> Envelope[PermittedProfile]:
        def body(model: FinancialModel) -> Envelope[PermittedProfile]:
            tol = _parse_enum(RiskProfile, tolerance, "tolerance")
            result = derive_permitted_profile(tol, assess_capacity(model, self._params_for(model)), model)
            return self._ok(model, result, permitted_facts(result), kind="profile", parts=(tol,))

        return self._run(user_id, body)

    def savings_plan(self, user_id: str, requested_profile: str | None = None) -> Envelope[SavingsPlan]:
        """The requested profile is CAPPED at the permitted profile, which is recomputed here.

        The model may pass any profile; it cannot obtain a larger rule than the user's
        tolerance and capacity allow (fix for the trust gap in the v0 contract, test S09).
        """

        def body(model: FinancialModel) -> Envelope[SavingsPlan]:
            permitted = self._permitted(model).permitted
            requested = _parse_enum(RiskProfile, requested_profile, "permitted_profile") if requested_profile else permitted
            effective = lower_profile(requested, permitted)
            caveats = []
            if effective is not requested:
                caveats.append(
                    Caveat(
                        "PROFILE_CAPPED",
                        f"I sized it with your permitted profile ({permitted.value}), not {requested.value}.",
                        (permitted.value,),
                    )
                )
            plan = size_plan(model, self._params_for(model), effective)
            envelope = self._ok(
                model, plan, plan_facts(plan, model.currency), caveats, kind="plan", parts=(effective,)
            )
            self._snapshots.put(envelope.snapshot_id, user_id, StoredPlan(plan, model.currency, user_id))
            return envelope

        return self._run(user_id, body)


def _parse_enum(enum: type, value: Any, field: str):
    try:
        return enum(str(value).strip().lower())
    except ValueError as exc:
        raise InvalidInput(field, f"invalid {field}", tuple(e.value for e in enum)) from exc


def _parse_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise InvalidInput(field, f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise InvalidInput(field, f"{field} must be an integer")


def _parse_month(value: Any, field: str) -> Month:
    try:
        return Month.parse(str(value))
    except ValueError as exc:
        raise InvalidInput(field, f"{field} must be YYYY-MM") from exc


def _parse_rate(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        rate = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidInput("monthly_rate", "monthly_rate must be a number like 0.025") from exc
    if not Decimal(0) <= rate <= Decimal("0.2"):
        raise InvalidInput("monthly_rate", "monthly_rate must be between 0 and 0.2")
    return rate
