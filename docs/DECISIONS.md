# Decision log

Short records of architecture decisions. Status starts as **Proposed**; the team marks each one **Accepted** or **Rejected** at a sync. A change after acceptance gets a new entry that supersedes the old one.

---

### ADR-001 · Clean architecture with a standard-library core · Proposed
**Context:** five people, ten days, undecided providers (LLM, Jev, DB, frontend).
**Decision:** domain and application use only the Python standard library; everything external is a port with an offline adapter; one composition root. Enforced by `tests/architecture`.
**Consequences:** any provider swap is one adapter file. Slightly more structure than a script; mitigated by the recipes in `ARCHITECTURE.md`.

### ADR-002 · Contracts first · Proposed
**Decision:** `contracts/` (JSON Schema 2020-12) defines tools, outputs, actions, audit and chat. LLM tool definitions are loaded from it; contract tests validate real outputs; the frontend generates its types from it.
**Consequences:** B, C and D can build in parallel against fixed shapes. Interface changes need a contract change in the same PR.

### ADR-003 · The application orchestrates; the LLM is an adapter · Proposed
**Context:** the Notion diagram places the LLM in front of everything, in the control path of actions.
**Decision:** use cases own the flow. The decision model classifies the raw user text independently of the LLM. The LLM only chooses tools allowed for the turn and writes text. Execution reads terms from the stored authorization.
**Consequences:** a fully compromised model cannot move money (tested in S01).

### ADR-004 · Decision-model port shaped as closed questions; configurable chain · Proposed
**Context:** Vicente's comment ("Jev first, deterministic fallback").
**Decision:** port = `ChoiceQuestion | ScoreQuestion | YesNoQuestion → Judgment(label, probabilities, confidence, source)`. Adapters: rules (built first, always available), Jev, optional LLM judge. Runtime order via `NL_DECISION_CHAIN`. All unavailable → read-only.
**Consequences:** "Jev first or LLM first" becomes configuration. No money decision depends on any model.

### ADR-005 · Persistence: memory, then SQLite; no Mongo or DynamoDB · Proposed
**Decision:** in-memory adapters for tests and offline mode; SQLite (stdlib) for durable runs; Postgres possible behind the same ports.
**Consequences:** `docker compose up` needs no external services. Single-use authorizations and the audit chain get ACID guarantees.

### ADR-006 · Offline mode is a Must · Proposed
**Decision:** the scripted language model plus the rules decision model run the whole demo arc with no keys and no network.
**Consequences:** reliable CI, reliable video recording, S10 covered, judges can run it.

### ADR-007 · Tool contract changes from Spec v0 · Proposed
- `create_savings_rule(...)` → `propose_savings_rule(plan_snapshot_id)` (amounts only from stored plans; D7).
- `execute_sandbox_action(authorization_id, requested_terms?)`: terms from the authorization; requested terms only compared.
- No confirm tool; confirmation is a UI-only endpoint.
- `compute_savings_plan` caps the requested profile at the permitted profile, recomputed server-side.
- New `get_pending_actions` (T0). `verify_recommendation` is automatic, not a tool. `propose_plan` is split into `derive_permitted_profile` + `compute_savings_plan`.
- Warnings are objects with `must_mention` tokens.

### ADR-008 · HMAC-signed authorizations and a hash-chained audit log · Proposed
**Decision:** `action_hash = HMAC-SHA256(server secret, canonical terms)`; audit events chained by `prev_hash` / `event_hash`; an execution starts only after its audit event is written.
**Consequences:** S05 and audit tampering are detectable; evidence can be verified by the judges.

### ADR-009 · Typed user record instead of a free-form record or graph memory · Proposed
**Decision:** `UserProfile` (display name, language, declared tolerance, questionnaire answers), read-only to the agent (T0); changes are proposals the user confirms.
**Consequences:** no persistent prompt-injection channel; minimal personal data.

### ADR-010 · Financial definition fixes (F1–F4) · Proposed
- Debt service = scheduled debt payments (cuotas + loans), not rent or subscriptions (matches E05).
- Equal cuotas; total = n × cuota (matches E02).
- `c_max = min over months of H_m / k_m` for the largest affordable amount.
- Seasonal factors stored exactly (`Fraction`), e.g. 49/30, not 1.633.
**Owner:** Role A confirms or replaces these in `domain/finance/`.

### ADR-011 · Stage-1 estimation over pay cycles, with exact statistics · Proposed
**Context:** the estimators must produce exactly the `FinancialModel` the fixtures define, without changing stage 2.
**Decision:** months are pay cycles (`paycycle.py`, payday = last weekday); quantiles use linear interpolation on `Fraction`s; the income CV uses the sample standard deviation; one seasonal factor per month (total ÷ Σ category P50); sparse categories merge into `other`; as_of must be the day before a payday or the result is `INVALID_INPUT`. Details: `docs/SCOPE.md` F9–F14. Capacity with zero essentials raises `InsufficientData` (H4) instead of dividing by zero.
**Consequences:** the ledger source and the fixtures are interchangeable (`NL_MODEL_SOURCE`), and the goldens guard both. The design doc (§3, §4.2, §4.3, §8) should record F9–F14.

### ADR-012 · The estimators trust the `transfer_own` classification · Proposed
**Context:** card payments and own-account sweeps appear in checking as outflows. Counting them as spending would double-count the cuotas and card purchases (design §3).
**Decision:** Role C (the ledger/platform) classifies own-account movements as `kind=transfer_own` (and the card side as `card_payment`). The stage-1 estimators trust that classification and exclude those movements from income, variable spend, commitments and the one-off expense. The generated ledgers reconcile per account (opening + Σ movements = closing; `tests/golden/test_reconciliation.py`).
**Consequences:** a real outflow mislabelled `transfer_own` would disappear from variable spend and overstate the protected surplus. This is a **known risk for the security self-assessment** (`docs/SECURITY.md`). Mitigation for real data: reconcile both legs of each own transfer (out of one sandbox account, into another) and treat unmatched `transfer_own` as spending; not needed on synthetic data.

### ADR-013 · Content-addressed snapshot ids and a parameter lock · Proposed
**Decision:** a ledger's `source_version` is `ledger:<user>:<sha256[:16]>` of its canonical content (user, currency, as_of, accounts, buckets, goals, income profile and the effective transactions, one per `txn_id`, sorted; card rates as exact text), never a version label. Every `snapshot_id` hashes `source_version`, `as_of` and `params_version`. `FinanceParams.fingerprint()` hashes every value exactly (Fraction as n/d); `tests/unit/test_params_lock.py` pins it per version, so changing a value without bumping `params_version` fails the build.
**Consequences:** one peso anywhere changes the snapshot id; order and exact duplicates do not. The audit log's `forecast_snapshot_id` and `policy_version` always name the data and the numbers used.

### ADR-014 · Profile-ceiling sizing and purchase-prefix investigation · Proposed (team decision)
**Context:** the hypothesis invariants (design §8) found two recorded cases (`tests/property/test_plan_counterexamples.py`):
1. Before Part 1, a higher profile gave a smaller rule: conservative 20,000 (from 2027-02), moderate 30,000 (from 2027-06), aggressive 0 (H2). Available is 55,200 a month and −596,636 every December; 40,000 a month breaches before every next December within the 12 start months searched.
2. Still unresolved, a purchase raises the rule: without it 80,000 from 2026-11 (Required 81,819); a purchase in 3 cuotas from 2026-11 delays the start to 2027-01, Required rises to 100,000, and the rule becomes 90,000.

**Part 1, Proposed and implemented for review (not accepted):** the requested/permitted profile's share is a ceiling. Compute each discrete eligible share's **earliest H5-feasible** rule with the prior per-share sizing arithmetic; take the **maximum rule amount**, breaking ties by earlier start and then higher share (preserves the existing `share` metadata on a complete money/start tie). The base projection is shared; H2, H5 and allocation rules remain. `SavingsPlan.profile` remains the requested/effective profile and `share` reports the selected share, which can be lower. If no candidate exists, H2 retains the ceiling share. A higher ceiling only adds candidates to the lower ceiling's set, so taking the maximum amount cannot reduce the rule. On the recorded profile case, the results are conservative 20,000 from 2027-02 at 2/5; moderate 30,000 from 2027-06 at 3/5; aggressive 30,000 from 2027-06 at 3/5, no H2. The profile strict xfail and the general profile property now pass normally; the old purchase xfail and non-strict purchase marker are unchanged. Contract `outputs/savings_plan.schema.json` describes the selected-share meaning; focused tests validate actual plans against it. Conservative Camila stays 100,000 from 2027-01 at 2/5; E01–E14 and both demo outputs are unchanged.

**Part 2 STOP (not implemented or adopted):** replacing purchase amount monotonicity with the proposed *cumulative planned savings at every prefix month* is **also false**. The recorded 80,000-versus-90,000 case satisfies 80,000 × k ≥ 90,000 × max(k − 2, 0) for every k=1..12 (through the 2027-09 trip deadline at k=11). But a separate Hypothesis test with the existing `raw_ledgers()`, `purchases` and `PROFILES` strategies found a counterexample. Its shrunk generator configuration is salaried 600,000, rent 150,000, subscriptions 10,000, `p80` groceries/dining/transport/shopping/utilities 10,000 each and health 145,000, seed 0, no prior plans, no bonus, savings opening 50,000,000, derived reserve, no strict-balance restriction. Conservative profile; new purchase principal 277,000 in 3 cuotas, offset 0 (2026-11), monthly rate 0.025. Without purchase: 40,000 from 2026-11, share 2/5. With purchase: 50,000 from 2027-01, share 2/5. At the **first failing prefix, 2027-09 (k=11)**, baseline funded 11 × 40,000 = 440,000 while purchase case funded 9 × 50,000 = 450,000. At k=12 it remains false: 480,000 < 500,000. The purchase engine and both existing purchase markers are untouched; a team decision is required before adopting any replacement invariant.

The full exploratory property is executable as `/tmp/opencode/test_wp3_prefix.py` from `backend/` with `PYTHONPATH=src:. /home/brunoc/Projects/Universidad/Neural-Ledger/.venv/bin/python -m pytest /tmp/opencode/test_wp3_prefix.py -q -x --hypothesis-seed=20261010 --hypothesis-show-statistics`. It uses `@given(raw_ledgers(), purchases, st.sampled_from(PROFILES))`, `@settings(max_examples=1200, deadline=None, derandomize=False, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])`, computes `prefix(plan, model, k) = plan.amount * sum(model.first_cycle.plus(offset) >= plan.start_month for offset in range(k))` (zero for no start), and asserts `prefix(with_purchase, model, k) <= prefix(without, model, k)` for **every** k in 1..12. The actual run failed: 336 passing / 5 failing / 38 invalid generated examples, then 945 shrink attempts (311 successful), one distinct failure. The shrunk raw ledger and purchase are preserved at `/tmp/opencode/wp3_prefix_counterexample.json`; the compact configuration above independently reproduces the same plans. This property was not added to the shipped test suite or xfailed.

Recreate the property in scratch (the imports and test below are complete; run from `backend/` with `PYTHONPATH=src:.`):

```python
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.finance.plan import size_plan
from tests.property.strategies import raw_ledgers
from tests.property.test_engine_properties import HORIZON, PROFILES, _model, _overlay, purchases

@settings(max_examples=1200, deadline=None, derandomize=False,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(raw_ledgers(), purchases, st.sampled_from(PROFILES))
def test_purchase_never_raises_cumulative_planned_savings(raw, purchase, profile):
    model = _model(raw)
    without = size_plan(model, FC_0_1, profile)
    with_purchase = size_plan(model, FC_0_1, profile, purchases=(_overlay(model, purchase),))
    for months in range(1, HORIZON + 1):
        before = (without.amount * sum(model.first_cycle.plus(offset) >= without.start_month
                                       for offset in range(months))) if without.start_month else 0
        after = (with_purchase.amount * sum(model.first_cycle.plus(offset) >= with_purchase.start_month
                                           for offset in range(months))) if with_purchase.start_month else 0
        assert after <= before, (months, without, with_purchase, purchase)
```

Compact deterministic reproducer (also executable from `backend/`):

```python
from decimal import Decimal
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.finance.plan import size_plan
from neural_ledger.domain.finance.profile import RiskProfile
from tests.fixtures.ledger_generator import GeneratorConfig, generate_ledger
from tests.property.test_engine_properties import _model, _overlay

config = GeneratorConfig(
    user_id="prop", seed=0, plans=(), salary=600_000, rent=150_000,
    subscriptions=10_000, p80={
        "groceries": 10_000, "dining": 10_000, "transport": 10_000,
        "shopping": 10_000, "utilities": 10_000, "health": 145_000,
    }, unexpected_expense=300_000, bonus=0, savings_opening=50_000_000,
    savings_buckets=None, strict_balances=False,
)
model = _model(generate_ledger(config))
before = size_plan(model, FC_0_1, RiskProfile.CONSERVATIVE)
after = size_plan(model, FC_0_1, RiskProfile.CONSERVATIVE,
                  purchases=(_overlay(model, (277_000, 3, 0, Decimal("0.025"))),))
assert (before.amount, str(before.start_month)) == (40_000, "2026-11")
assert (after.amount, str(after.start_month)) == (50_000, "2027-01")
assert before.amount * 11 == 440_000 < 450_000 == after.amount * 9
```

**WP3 validation:** `make test-all` 379 passed / 1 xfailed / 1 xpassed; `make test-property` 17 passed / 1 xfailed / 1 xpassed; `make test-golden` 55 passed; `make test-security` 14 passed; focused plan tests 14 passed / 1 xfailed / 1 xpassed. The xfail and xpass are the original purchase cases. Fixture and ledger demo stdout are each byte-identical to the cfe1c81 baseline. Ruff and diff-check pass. ADR-014 remains Proposed; Part 2 is stopped pending a policy decision.

**Part 2 specification:** the original "a purchase never raises the monthly rule" invariant was wrong, not evidence by itself of a purchase-engine bug: delaying the start can raise the required monthly funding rate. No purchase-engine change is proposed here. The independently reproduced prefix counterexample above also falsifies the proposed replacement, so that replacement is stopped rather than adopted.

### ADR-015 · Seeded synthetic rolling-origin implementation backtest · Proposed
**Decision proposed:** opt-in independent lognormal category spend and freelance income, with December factor 49/30, fixed seed lists and no changes to calibrated persona ledgers. Origins after 6/7/8/9 cycles with horizon 3 plus a separately labelled origin after 18 cycles evaluate a second December after observing the first. Truncate the ledger at each origin before estimation. Bernoulli coverage alone gets Wilson intervals; continuous error and recovery get n, median, p10/p90 and mean absolute value. Overlapping trials cluster by seed, so Wilson intervals are optimistic. This validates implementation on known synthetic distributions, not predictive accuracy. Measured results and limitations: `docs/BACKTEST.md`. No estimator parameters were tuned to improve coverage.
