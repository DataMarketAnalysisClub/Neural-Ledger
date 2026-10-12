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
