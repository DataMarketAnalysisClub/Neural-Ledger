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

### ADR-014 · size_plan is not monotone in the profile or in purchases · Proposed (team decision)
**Context:** the hypothesis invariants (design §8) found two minimal counterexamples (`tests/property/test_plan_counterexamples.py`):
1. A higher profile gives a smaller rule: conservative 20,000 (from 2027-02), moderate 30,000 (from 2027-06), aggressive 0 (H2). Available is 55,200 a month and −596,636 every December; 40,000 a month breaches before every next December within the 12 start months searched.
2. A purchase raises the plan: without it the rule is 80,000 from 2026-11 (capped by Required 81,819); a purchase in 3 cuotas from 2026-11 pushes the start to 2027-01, fewer months remain to the trip deadline, Required rises to 100,000 and the rule becomes 90,000.
**Updated proposal (NOT accepted or implemented):** treat the permitted profile's share as a ceiling. For **every** eligible share at or below that ceiling, compute the feasible rule amount at its earliest feasible start. Select the share with the **maximum feasible RULE AMOUNT**, breaking ties by earlier start. Taking merely the highest feasible share is not equivalent and is not authorized. Separately propose that adding a purchase never increases cumulative planned savings **at each month** over the horizon (the prefix sum of rule amount over funded months), not merely the final horizon total. This replaces the earlier suggestion to size Required from an unconstrained/no-purchase start; do not adopt that workaround. Team approval and engine design are pending; E01–E14 and existing strict xfails/non-strict xpasses stay unchanged.

### ADR-015 · Seeded synthetic rolling-origin implementation backtest · Proposed
**Decision proposed:** opt-in independent lognormal category spend and freelance income, with December factor 49/30, fixed seed lists and no changes to calibrated persona ledgers. Origins after 6/7/8/9 cycles with horizon 3 plus a separately labelled origin after 18 cycles evaluate a second December after observing the first. Truncate the ledger at each origin before estimation. Bernoulli coverage alone gets Wilson intervals; continuous error and recovery get n, median, p10/p90 and mean absolute value. Overlapping trials cluster by seed, so Wilson intervals are optimistic. This validates implementation on known synthetic distributions, not predictive accuracy. Measured results and limitations: `docs/BACKTEST.md`. No estimator parameters were tuned to improve coverage.
