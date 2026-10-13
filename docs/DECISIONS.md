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

**Part 2 STOP (not implemented or adopted):** replacing purchase amount monotonicity with the proposed *cumulative planned savings at every prefix month* is **also false**. A Hypothesis search using the existing `raw_ledgers()`, `purchases` and `PROFILES` strategies found a counterexample; the compact deterministic reproducer below uses `GeneratorConfig`. Its configuration is salaried 600,000, rent 150,000, subscriptions 10,000, `p80` groceries/dining/transport/shopping/utilities 10,000 each and health 145,000, seed 0, no prior plans, no bonus, savings opening 50,000,000, derived reserve, no strict-balance restriction. Conservative profile; purchase principal 277,000 in 3 cuotas, offset 0 (2026-11), monthly rate 0.025. Without purchase: 40,000 from 2026-11, share 2/5. With purchase: 50,000 from 2027-01, share 2/5. The purchase pushes the start past the December trough: the later six-cycle sizing window excludes December, allowing a higher lowest-available-based rule even though available is reduced while the purchase is present. At the **first failing prefix, 2027-09 (k=11)**, baseline funded 11 × 40,000 = 440,000 while purchase case funded 9 × 50,000 = 450,000; at k=12 it remains false (480,000 < 500,000). This is distinct from the 80,000-versus-90,000 deadline case above: that case's trip `Required` rises when the start shifts, but its cumulative-prefix inequality holds at every k=1..12. Here it is the prefix invariant itself that fails. No purchase-engine change is proposed, and the existing strict xfail remains unchanged.

**Part 2 team options (proposed, not accepted):** **(a) Recommended:** drop purchase monotonicity as a required invariant; retain H5 (no conservative-path breach) and the trough/lowest-available sizing invariants as safety properties. **(b)** defer a replacement policy until the team designs a new invariant that captures the intended purchase behavior. Neither option is adopted by this ADR without team decision.

The full exploratory property was run from `backend/` as `/tmp/opencode/test_wp3_prefix.py` with `PYTHONPATH=src:. /home/brunoc/Projects/Universidad/Neural-Ledger/.venv/bin/python -m pytest /tmp/opencode/test_wp3_prefix.py -q -x --hypothesis-seed=20261010 --hypothesis-show-statistics`. It uses `@given(raw_ledgers(), purchases, st.sampled_from(PROFILES))`, `@settings(max_examples=1200, deadline=None, derandomize=False, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])`, computes `prefix(plan, model, k) = plan.amount * sum(model.first_cycle.plus(offset) >= plan.start_month for offset in range(k))` (zero for no start), and asserts `prefix(with_purchase, model, k) <= prefix(without, model, k)` for **every** k in 1..12. The actual run failed: 336 passing / 5 failing / 38 invalid generated examples, then 945 shrink attempts (311 successful), one distinct failure. The raw shrunk ledger and purchase were recorded in `/tmp/opencode/wp3_prefix_counterexample.json` as ephemeral historical evidence, not as the durable reproducer; the compact deterministic code and `GeneratorConfig` above are the durable reproduction in this document. This property was not added to the shipped test suite or xfailed.

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

### ADR-016 · Unobserved seasonal months are flagged, not modelled · Proposed
**Context:** with fc-0.1 (`seasonal_months=(12,)`, 12-cycle window, 6-cycle minimum), a ledger with 6 to 11 cycles of history and no December in the estimation window gets no December factor; `SpendModel.factor` silently defaults to 1 (`docs/SCOPE.md` F17). The forecast then under-states December spend, which the backtest shows as adverse Grid A December coverage without a prior December (`docs/BACKTEST.md`).
**Decision proposed (warning only):** when a month in `params.seasonal_months` has no pay cycle in the estimation window, `estimate_model` appends one `SEASONALITY_UNOBSERVED` caveat listing every missing month in ascending order (static English month names; `must_mention` = the month names plus `"seasonal"`; no ledger text) and the fact `estimate.seasonal.unobserved_months` (ascending month numbers, comma-separated, unit `month_numbers`). Both are emitted only on the success path, after the existing warnings and facts. No amount, factor, quantile, snapshot id, status, params value or `params_version` changes; tests compare the model against a no-season test configuration to prove it.
**Team option, NOT implemented:** return H4 `INSUFFICIENT_DATA` when the requested forecast/check horizon crosses an unobserved December, identifying the missing seasonal evidence. This is a separate team decision; no refusal or default uplift is implemented here. Any future parameter-value change would require a new `params_version` and fingerprint lock.
**Consequences:** the warning is **estimator-only**. `LedgerModelSource.load` drops stage-1 warnings and facts, so the catalogued `must_mention: true` is inert until forwarding is decided (`docs/EXPLANATION_HANDOFF.md`); the under-forecast risk stays open (`docs/SECURITY.md`). The committed backtest evidence predates the warning; its `diagnostics.warning_codes` would gain `SEASONALITY_UNOBSERVED` counts for origins without a December, and no other output changes.
**WP1 verification (Oct 10):** with `PY=/home/brunoc/Projects/Universidad/Neural-Ledger/.venv/bin/python`, `make test-all` reports 387 passed / 2 xfailed / 2 xpassed; `make test-golden` 55 passed and `make test-security` 14 passed (zero xfail/xpass in those lanes). Both demo outputs are byte-identical to cfe1c81. A 100-seed scratch backtest differs only by 600 `SEASONALITY_UNOBSERVED` warnings; every other JSON field is identical. Ruff and protected-path checks pass. Python LSP is unavailable; no server was installed.
---

## Bank statements and the transaction ledger

ADR-011 to ADR-016 cover reading cartolas and posting them to the transaction ledger. Each says whether it is **built** or **decided, not built**. O-1 and O-2 are open issues for further analysis; nothing is changed for them yet.

### ADR-011 · Statement import pipeline: ocr_tabular + one `Bank` per layout · Built
**Decision:** `ocr_tabular` (adapted into `adapters/outbound/statements/`) turns any PDF or image into word boxes and tables; a `Bank` subclass per layout (first: `SantanderCuentaMatica`) says where the table is and what the rows mean. Import = read → reconcile (domain) → store (once per user and statement) → audit `STATEMENT_IMPORTED`. Entry points: `neural-ledger import-statement`, `POST /v1/statements`, `GET /v1/statements[/{id}]`.
**Consequences:** a new bank is one file plus a registry line (recipe in `ARCHITECTURE.md`). Real cartolas live in the git-ignored `cartolas/`; tests use synthetic samples only. Text-layer PDFs need the `pdf` extra; scans and photos also need `ocr` (EasyOCR + torch, not in the Docker image). A scan holds the HTTP request open for minutes (~80 s per page on CPU); a background job is the next step if that matters.

### ADR-012 · Reconciliation is the authority over the reader · Built
**Decision:** the domain recomputes totals, the closing balance and every printed daily balance from the lines. Any misread amount, dropped line or wrong day breaks an equality. Because of that, the reader may be tolerant of OCR noise in amounts and dates (`102/09`, `1 _ 097 .805`), and low OCR confidence (< 0.5) only warns (`OCR_LOW_CONFIDENCE`): EasyOCR scores correct digits at 0.15–0.4, and descriptions are the only thing reconciliation cannot check.
**Consequences:** amounts are never trusted because the reader is confident, only because they add up.

### ADR-013 · Statements that do not reconcile go to the user for review, and are usable either way · Decided, not built
**Context:** today an unreconciled statement is stored as unverified (`STATEMENT_UNVERIFIED`) but **not** posted to the ledger (`NOT_POSTED`).
**Decision:**
1. Every statement that does not reconcile is shown to the user with its issues (which total or which day's balance differs, expected vs found).
2. The user can correct it by hand: a line's amount, date or description, add a missed line, or remove a duplicated one. Reconciliation runs again after each change.
3. It can be used either way: corrected and reconciling, or accepted by the user as it is. In both cases its movements are posted to the ledger.
4. Its transactions stay flagged as coming from an unverified statement until it reconciles. Envelopes that use them carry a warning the agent must mention.
5. The reading stays immutable. Corrections are stored separately (who, when, old → new value) and audited as user actions, so the original read can always be recovered.
**Consequences:** replaces the current "not posted" rule. Needs: a corrections record and store, a review list (`GET /v1/statements?verified=false` or similar), edit endpoints in the UI path only (never an agent tool), a new audit kind, contract changes and a `STATEMENTS_VERSION` bump. Amounts the user types are user input, not model output, so rule 2 (deterministic authority) holds.

### ADR-014 · Spending categories: a swappable classifier, gated by the domain · Built
**Decision:** a `TransactionClassifier` port guesses one category per charge. The default is naive Bayes (TF-IDF character n-grams, from `ocr_tabular/ml`), selected by `NL_CLASSIFIER` from a registry in `container.py`. The domain accepts a guess only if it is in the category vocabulary and has confidence ≥ 0.5; otherwise the charge is `uncategorized`. Deposits are `income` by rule. Bank boilerplate (`Compra Nacional MD`, `TDB`, `Pago`, …) is removed before features. The model trains at first use from a versioned CSV, is never pickled, and its name carries the training data's hash, recorded on every transaction with its confidence.
**Consequences:** changing the model or method is one adapter or one registry entry. On the real sample cartola only 2 of 45 charges were categorized: the training data (96 synthetic rows) is the limit, not the method (see O-2).

### ADR-015 · Categories can be changed by the user · Decided, not built
**Decision:** the user can set or change the category of any transaction, including choosing `Movimiento` (ADR-016). A manual category is stored with `classifier = "user"` and always wins over any model, including when a new model re-categorizes the ledger. Changes are audited as user actions.
**Consequences:** needs a category-override record, an endpoint in the UI path and a contract change. Manual labels are also the best source of new training rows. A row from a real user's statement can only be used locally, never committed.

### ADR-016 · New category `Movimiento` for money that is not spending or income · Decided, not built
**Context:** transfers to the user's own accounts, credit card payments, investments and savings (e.g. `Fondo Mutuo`, `Transf a Fintual`) are posted today as purchases. The financial core requires card payments and own transfers to count as `transfer_own`, never as spending, or cuotas are counted twice.
**Decision:**
- New category `movement`, shown to the user as **"Movimiento"**, with kind `transfer_own`. It applies in both directions: money in from the user's own account is also a Movimiento, not income.
- Movimientos are excluded from spending and income totals and listed in totals of their own.
- Rules come first, and they are deterministic and per bank, in the `Bank` layout: own-account transfers, card payments, mutual funds and investment platforms. A transfer to the account holder's own RUT is a Movimiento. The classifier may also suggest `movement` through the same confidence gate.
- The user can change it either way (ADR-015).
- A transfer to a third party stays spending (`other`) unless the user marks it as a Movimiento.
**Consequences:** vocabulary and contract change (`CATEGORIES`, `transactions.schema.json`), `CATEGORIZATION_VERSION` bump. Role A confirms that estimators read `transfer_own` this way.

### O-1 · Open: a corrected re-read of the same cartola is treated as a duplicate · For analysis
**Observed:** the statement id hashes bank, account, period and lines, but not the printed summary or daily balances. If a scan misreads only a printed balance, the statement is stored unverified. Importing the clean PDF of the same cartola then has the same id, counts as a duplicate, and the stored unverified copy wins.
**Options to analyse:**
- (a) Include the printed summary and balances in the id. Simple, but two readings of one cartola then both exist.
- (b) On a duplicate, supersede the stored copy when the new reading reconciles and the old one does not, keeping the old one as history.
- (c) Let ADR-013's manual review absorb it.
Decide together with ADR-013, since corrections and re-reads both change which version of a statement is current.

### O-2 · Open: category vocabulary, training data and re-categorization · For analysis
- **Vocabulary:** the ledger uses English slugs: the personas' `groceries, dining, health, shopping, transport, utilities`, plus `entertainment`, `other`, `income`, `uncategorized` (and `movement` from ADR-016). The Spanish training labels are mapped to them (Supermercado → groceries, …). To settle: the final list with Role A and E (the estimators and the generator group spend by category), and the Spanish UI labels.
- **Training data:** 96 synthetic rows with few of the merchants a real cartola shows. Options: more synthetic rows, manual labels from ADR-015 kept local, per-user models. The 0.5 confidence floor and the boilerplate word list should be re-checked once there is more data. Use a labelled hold-out set as the quality gate before changing the default model.
- **Re-categorization:** existing transactions keep their category on re-import, and there is no "re-categorize with the current model" yet. Manual categories (ADR-015) must survive it.
- **Classifier unavailable:** today the statement is stored but not posted, and re-importing backfills. Revisit with ADR-013, for example posting as `uncategorized` instead.
