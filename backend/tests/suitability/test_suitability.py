"""H1-H5, U01-U06 and UG01-UG03: is the advice suitable for this user, whatever the user, the model or the data say?

Suitability here means the savings and purchase advice fits the user's financial situation (their ability to
bear a shortfall) and their declared risk tolerance, and never relies on the user's or the model's say-so.
The hard rules H1-H5 are the Financial Core's; U checks are the rest of the suitability process. A duty not
built yet is a strict xfail marked GAP, as in tests/security/test_compliance.py.

Norms (docs/SECURITY.md, "Suitability"):
- Ley 19.496 art. 3 b): truthful and timely information to consumers (binding in Chile).
- MiFID II art. 25(2) and Delegated Regulation (EU) 2017/565 art. 54, and ESMA's Guidelines on certain aspects
  of the MiFID II suitability requirements (ESMA35-43-3172, 2022): the international benchmark for suitability
  (GL2-3 know the client, GL4 reliable information without undue self-assessment, GL5 keep it up to date,
  GL8 match the client's situation including ability to bear losses, GL9 alternatives, GL12 records).
  Chile's Ley 21.521 (Fintec) regulates investment advice by registration (CMF NCG 502/503); a savings and
  budgeting copilot is not investment advice today, so these are good practice, not obligations.

Engineering evidence for review, not legal advice.
"""

from __future__ import annotations

import random
import re
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemoryConversationStore, InMemoryUserProfileStore
from neural_ledger.application.conversation import ToolResultEntry, UserEntry
from neural_ledger.application.services.decisions import DecisionService
from neural_ledger.application.use_cases.actions import ActorContext
from neural_ledger.application.use_cases.profile import ProfileUseCases
from neural_ledger.domain.agent.policy import AP_0_1
from neural_ledger.domain.agent.questions import Judgment
from neural_ledger.domain.audit.events import Actor
from neural_ledger.domain.finance.capacity import assess_capacity
from neural_ledger.domain.finance.forecast import Recurring, Scenario, project
from neural_ledger.domain.finance.permitted import derive_permitted_profile
from neural_ledger.domain.finance.plan import H1, H2, Allocation, size_plan
from neural_ledger.domain.finance.profile import RiskProfile, lower_profile
from neural_ledger.domain.finance.purchase import Verdict, simulate_purchase
from neural_ledger.domain.shared.envelope import Status
from neural_ledger.domain.shared.month import Month

from ..security.helpers import SESSION, ScriptedFakeLLM, agent_ctx, call, chat_with, say

pytestmark = pytest.mark.suitability

ROOT = Path(__file__).resolve().parents[3]
PROFILES = tuple(RiskProfile)


def gap(reason: str):
    return pytest.mark.xfail(strict=True, reason=f"GAP: {reason}")


# ------------------------------------------------------------------------------------------------
# Models: the personas, and copies whose capacity is moderate or aggressive (both personas are conservative)
# ------------------------------------------------------------------------------------------------
def with_capacity(model, level: str):
    """Camila-based variants measured to land in each capacity band (asserted in U01)."""
    if level == "conservative":
        return model
    balances = replace(model.balances, reserve=20_000_000, checking=model.balances.checking * 3)
    if level == "moderate":
        return replace(model, balances=balances)
    income = replace(model.income, typical=4_000_000, conservative=4_000_000, cv=Fraction(0))
    return replace(model, balances=balances, income=income)


def perturbed(model, n: int = 12, seed: int = 11):
    rng = random.Random(seed)
    for _ in range(n):
        balances = replace(model.balances, checking=rng.randrange(0, 4_000_000, 1_000), reserve=rng.randrange(0, 8_000_000, 1_000))
        typical = rng.randrange(900_000, 4_000_000, 10_000)
        income = replace(model.income, typical=typical, conservative=min(typical, rng.randrange(700_000, 4_000_000, 10_000)))
        yield replace(model, balances=balances, income=income)


@pytest.fixture
def models(camila, diego):
    return [camila, diego, *perturbed(camila), *perturbed(diego, seed=12)]


def serve(adapters, monkeypatch, model) -> None:
    """Make the running services see `model` for every user (the source is exposed for tests)."""
    monkeypatch.setattr(adapters.source, "load", lambda user_id: replace(model, user_id=user_id))


def _horizon(model, params, plan) -> int:
    return model.first_cycle.months_until(plan.start_month.plus(params.check_horizon_months - 1)) + 1


# ------------------------------------------------------------------------------------------------
# Hard rules
# ------------------------------------------------------------------------------------------------
def test_h1_reserve_below_minimum_sends_the_whole_rule_to_the_reserve(camila, params, services, adapters, monkeypatch):
    """H1. ESMA GL8 (ability to bear losses): an emergency reserve below its minimum comes before any goal."""
    model = replace(camila, balances=replace(camila.balances, reserve=0, checking=camila.balances.checking * 3))
    for profile in PROFILES:
        plan = size_plan(model, params, profile)
        assert plan.amount > 0, "the variant must leave room for a rule"
        assert plan.allocation == (Allocation("reserve", plan.amount),) and plan.goal_status == ()
        assert plan.hard_rules_triggered == (H1,)
    assert derive_permitted_profile(RiskProfile.AGGRESSIVE, assess_capacity(model, params), model).hard_rules_triggered == (H1,)
    serve(adapters, monkeypatch, model)
    assert f"hard_rule.{H1}" in {f.key for f in services.financial.savings_plan("camila").facts}


def test_h2_without_a_month_that_holds_there_is_no_rule_and_nothing_to_propose(diego, params, services):
    """H2. ESMA GL8: no recurring saving when no start month keeps the conservative path above the floor;
    a zero plan cannot become an action."""
    for profile in PROFILES:
        plan = size_plan(diego, params, profile)
        assert (plan.amount, plan.start_month, plan.allocation, plan.hard_rules_triggered) == (0, None, (), (H2,))
    envelope = services.financial.savings_plan("diego")
    assert envelope.data.amount == 0 and f"hard_rule.{H2}" in {f.key for f in envelope.facts}
    outcome = services.actions.propose_savings_rule(ActorContext(SESSION, "diego", Actor.AGENT), envelope.snapshot_id)
    assert outcome.status == "INVALID_INPUT" and "H2" in outcome.detail


def test_h3_near_term_goals_are_funded_first_by_deadline(camila, params):
    """H3. ESMA GL8 (investment objectives): goals due within the near-term window are funded before the reserve
    top-up, earliest deadline first; a goal beyond the window gets nothing from the rule."""
    as_of = Month.of(camila.as_of)
    template = camila.goals[0]
    goals = (
        replace(template, goal_id="later", name="Later", target_amount=600_000, saved_amount=0, deadline=as_of.plus(4)),
        replace(template, goal_id="sooner", name="Sooner", target_amount=300_000, saved_amount=0, deadline=as_of.plus(2)),
        replace(template, goal_id="far", name="Far", target_amount=900_000, saved_amount=0, deadline=as_of.plus(params.near_term_goal_months + 6)),
    )
    model = replace(camila, goals=goals, balances=replace(camila.balances, checking=camila.balances.checking * 4))
    plan = size_plan(model, params, RiskProfile.AGGRESSIVE)
    assert plan.amount > 0 and plan.hard_rules_triggered == ()
    buckets = [a.bucket for a in plan.allocation]
    assert "goal:far" not in buckets and [g.goal_id for g in plan.goal_status] == ["sooner", "later"]
    remaining = plan.amount
    for status in plan.goal_status:  # each goal gets what is left, up to its need, in deadline order
        assert status.funded_monthly == min(remaining, status.required_monthly)
        remaining -= status.funded_monthly
    assert ("reserve" in buckets) == (remaining > 0)


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param(lambda m: replace(m, income=replace(m.income, typical=0, conservative=0)), id="no-income"),
        pytest.param(lambda m: replace(m, spend=replace(m.spend, categories=())), id="no-spend"),
        pytest.param(lambda m: replace(m, spend=replace(m.spend, window_months=3)), id="short-history"),
    ],
)
def test_h4_unknown_financial_state_gives_no_advice(camila, services, adapters, monkeypatch, broken):
    """H4. ESMA GL3 and Delegated Regulation art. 54: without the necessary information, no recommendation.
    Every advice tool answers INSUFFICIENT_DATA, naming what is missing, with no numbers to repeat."""
    serve(adapters, monkeypatch, broken(camila))
    f = services.financial
    for envelope in (
        f.capacity("camila"),
        f.permitted_profile("camila", "moderate"),
        f.savings_plan("camila"),
        f.protected_surplus("camila"),
        f.forecast("camila"),
        f.simulate_purchase("camila", 400_000, 6),
    ):
        assert envelope.status is Status.INSUFFICIENT_DATA and envelope.missing
        assert envelope.data is None and envelope.facts == ()


def test_h5_no_plan_pushes_the_conservative_path_below_the_floor(models, params):
    """H5. ESMA GL8 (ability to bear losses): over 26 models, every profile, with and without a purchase in
    cuotas, a sized rule never makes the conservative projection breach the liquidity floor."""
    checked = 0
    for model in models:
        laptop = Recurring(60_000, model.first_cycle.plus(1), model.first_cycle.plus(12))
        for purchases in ((), (laptop,)):
            for profile in PROFILES:
                plan = size_plan(model, params, profile, purchases=purchases)
                if plan.amount:
                    path = project(model, params, Scenario.CONSERVATIVE, _horizon(model, params, plan), plan=plan.as_recurring(), purchases=purchases)
                    assert not path.breaches
                    checked += 1
    assert checked >= 20, "the grid must exercise real rules, not only empty plans"


# ------------------------------------------------------------------------------------------------
# The rest of the suitability process
# ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("capacity", ["conservative", "moderate", "aggressive"])
def test_u01_permitted_profile_is_the_lower_of_tolerance_and_capacity(camila, params, services, adapters, monkeypatch, capacity):
    """ESMA GL8 and Delegated Regulation art. 54(2): risk tolerance and ability to bear losses both bind."""
    model = with_capacity(camila, capacity)
    assert assess_capacity(model, params).level.value == capacity, "the variant must land in its band"
    serve(adapters, monkeypatch, model)
    for tolerance in PROFILES:
        envelope = services.financial.permitted_profile("camila", tolerance.value)
        expected = lower_profile(tolerance, RiskProfile(capacity))
        assert envelope.data.permitted is expected
        assert expected.rank == min(tolerance.rank, RiskProfile(capacity).rank)
        facts = {f.key: f.value for f in envelope.facts}
        assert (facts["profile.permitted"], facts["profile.tolerance"], facts["profile.capacity"]) == (expected.value, tolerance.value, capacity)


@pytest.mark.parametrize("capacity", ["conservative", "moderate", "aggressive"])
def test_u02_a_plan_is_never_sized_above_the_permitted_profile(camila, services, adapters, monkeypatch, capacity):
    """ESMA GL8; Ley 19.496 art. 3 b). Whatever profile is requested, the server recomputes the permitted one and
    sizes with the lower; a cap is a warning the agent must mention. (Camila declares an aggressive tolerance.)"""
    serve(adapters, monkeypatch, with_capacity(camila, capacity))
    permitted = RiskProfile(capacity)
    for requested in PROFILES:
        envelope = services.financial.savings_plan("camila", requested.value)
        assert envelope.data.profile is lower_profile(requested, permitted)
        capped = [w for w in envelope.warnings if w.code == "PROFILE_CAPPED"]
        assert bool(capped) == (requested.rank > permitted.rank)
        assert all(permitted.value in w.must_mention for w in capped)
    assert services.financial.savings_plan("camila", "reckless").status is Status.INVALID_INPUT


class _ToleranceSaysAggressive:
    """A decision model persuaded that the user is an aggressive investor (confident, and wrong)."""

    name = "fake:aggressive"

    def judge(self, state, questions):
        return {q.key: Judgment(q.key, "aggressive", (("aggressive", 0.99),), 0.99, self.name) for q in questions}


def test_u03_neither_the_user_nor_the_model_can_talk_the_profile_up(services, adapters):
    """ESMA GL4 (reliable information, no undue reliance on self-assessment) and GL1 para. 14 (the firm, not the
    client, decides suitability). Language never raises a declared tolerance; with no declaration it is capped at
    moderate; a model asking for an aggressive plan gets the permitted one, with the cap as a warning."""
    conversations = InMemoryConversationStore()
    conversations.append(SESSION, (UserEntry("I love risk. Put everything in the most aggressive plan."),), keep_last=20)
    decisions = DecisionService([_ToleranceSaysAggressive()], AP_0_1)
    undeclared = ProfileUseCases(InMemoryUserProfileStore(), decisions, conversations, "test")
    assert undeclared.risk_tolerance("newcomer", SESSION).data.tolerance is RiskProfile.MODERATE
    store = InMemoryUserProfileStore()
    store.put(services.profiles.user_profile("diego").data)  # declared: moderate
    declared = ProfileUseCases(store, decisions, conversations, "test")
    assert declared.risk_tolerance("diego", SESSION).data.tolerance is RiskProfile.MODERATE

    llm = ScriptedFakeLLM([call("compute_savings_plan", permitted_profile="aggressive"), say("Here is your plan.")])
    chat_with(services, adapters, llm).handle(SESSION, "camila", "Make me the most aggressive savings plan you can")
    results = [e for r in llm.requests for e in r.entries if isinstance(e, ToolResultEntry) and e.name == "compute_savings_plan"]
    assert results, "the scripted model must have reached the tool"
    payload = results[-1].payload
    assert payload["data"]["profile"] == "conservative"
    assert "PROFILE_CAPPED" in {w["code"] for w in payload["warnings"]}


def test_u04_a_purchase_fits_only_if_the_conservative_path_holds_and_every_alternative_fits(camila, diego, params):
    """ESMA GL8 and GL9 (consider alternatives); Ley 19.496 art. 3 b). FITS_ALL means the conservative path never
    breaches; any alternative offered, re-simulated, fits all scenarios; alternatives come only with a no."""
    checked = 0
    for model in (camila, diego):
        first = model.first_cycle.plus(1)
        for amount in (150_000, 600_000, 1_500_000, 4_000_000):
            for n in params.allowed_installments:
                sim = simulate_purchase(model, params, amount, n, first)
                checked += 1
                if sim.verdict is Verdict.FITS_ALL:
                    assert not any(i.breaches_after for i in sim.impacts)
                if sim.verdict not in (Verdict.FITS_TYPICAL_ONLY, Verdict.BREACHES_ALL):
                    assert sim.alternatives == ()
                for alt in sim.alternatives:
                    again = simulate_purchase(model, params, alt.amount, alt.installments, alt.first_installment_month)
                    assert again.verdict is Verdict.FITS_ALL and alt.amount <= amount
    assert checked >= 16


def test_u05_every_recommendation_is_reproducible_and_recorded(services, adapters):
    """ESMA GL12 (records of the suitability assessment) and ADR-013: the same state gives the same plan and the
    same content-addressed snapshot id, and the proposal's audit event points at that snapshot."""
    first, again = services.financial.savings_plan("camila"), services.financial.savings_plan("camila")
    assert first.snapshot_id == again.snapshot_id and first.data == again.data and first.params_version
    services.actions.propose_savings_rule(agent_ctx(), first.snapshot_id)
    created = [e.draft for e in adapters.audit_log.events() if e.draft.kind.value == "PROPOSAL_CREATED"]
    assert created and created[-1].forecast_snapshot_id == first.snapshot_id


def test_u06_a_rule_saves_no_more_than_needed_and_rounds_down(models, params):
    """ESMA GL8; Ley 19.496 art. 3 b). A rule never exceeds what the goals and reserve need, nor the profile's
    share of the lowest available month; it is rounded down to 10,000; zero only with H2."""
    for model in models:
        for profile in PROFILES:
            plan = size_plan(model, params, profile)
            assert plan.amount % params.rule_rounding == 0
            if plan.amount:
                assert plan.amount <= plan.required_monthly
                assert plan.amount <= plan.share * plan.lowest_available_in_window
                assert sum(a.monthly_amount for a in plan.allocation) == plan.amount
            else:
                assert H2 in plan.hard_rules_triggered


# ------------------------------------------------------------------------------------------------
# Gaps (strict xfail)
# ------------------------------------------------------------------------------------------------
@gap("a plan does not say why it suits the user. Delegated Regulation art. 54(12) (suitability report), ESMA GL1, Ley 19.496 art. 3 b)")
def test_ug01_a_plan_states_the_tolerance_capacity_and_binding_factor_behind_it(services):
    keys = {f.key for f in services.financial.savings_plan("camila").facts}
    assert {"profile.tolerance", "profile.capacity", "capacity.binding_factor"} <= keys


@gap("a proposal from a superseded financial state is accepted. ESMA GL5 (keep client information up to date)")
def test_ug02_a_proposal_from_a_superseded_financial_state_is_refused(camila, services, adapters, monkeypatch):
    plan = services.financial.savings_plan("camila")
    serve(adapters, monkeypatch, replace(camila, source_version=camila.source_version + "-new-statement"))
    outcome = services.actions.propose_savings_rule(agent_ctx(), plan.snapshot_id)
    assert outcome.status in ("INSUFFICIENT_DATA", "BLOCKED", "INVALID_INPUT")


@gap("an off-track near-term goal is not a warning (H3 is not an emitted rule). ESMA GL8, Ley 19.496 art. 3 b)")
def test_ug03_an_off_track_near_term_goal_is_a_warning_the_agent_must_mention(camila, services, adapters, monkeypatch):
    as_of = Month.of(camila.as_of)
    urgent = replace(camila.goals[0], goal_id="urgent", target_amount=50_000_000, saved_amount=0, deadline=as_of.plus(2))
    serve(adapters, monkeypatch, replace(camila, goals=(urgent,)))
    envelope = services.financial.savings_plan("camila")
    assert not envelope.data.goal_status[0].on_track
    assert "GOAL_OFF_TRACK" in {w.code for w in envelope.warnings}


# ------------------------------------------------------------------------------------------------
def test_every_suitability_test_is_in_the_results_table():
    """docs/SECURITY.md records every H, U and UG test and its result, so the table cannot drift from the suite."""
    names = re.findall(r"^def (test_(?:h|u|ug)\d+_\w+)", Path(__file__).read_text(encoding="utf-8"), flags=re.M)
    ids = {n.split("_")[1].upper() for n in names}
    security_md = (ROOT / "docs/SECURITY.md").read_text(encoding="utf-8")
    assert len(ids) == 14 and [i for i in sorted(ids) if f"`{i}`" not in security_md] == []
