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
