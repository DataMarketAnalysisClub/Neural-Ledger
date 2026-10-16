# Decision log

Short records of architecture decisions. Status starts as **Proposed**; the team marks each one **Accepted** or **Rejected** at a sync. A change after acceptance gets a new entry that supersedes the old one.

Numbers are global: take the next free one, and check open PRs first (ADR-016 to ADR-018 belong to Role A's draft PRs).

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

### ADR-025 · Frontend stack and design system (closes D-04) · Proposed
**Context:** D-04 left the framework to Role D ("fastest stack, web first"). The Figma mockup was audited with WCAG, UX and several design skills; the findings asked for a minimalist, accessible UI that does not read as a generic AI dashboard, legible in a compressed demo video and for international judges.
**Decision:**
- Stack: React 18 + Vite + TypeScript + Tailwind v4, Radix primitives, Recharts, TanStack Query, Phosphor icons, Geist (self-hosted). Types are generated from `contracts/` (`npm run contracts`); served by nginx in `docker compose`, which proxies `/api` to the API.
- Style: minimalist with flat surfaces; cool neutrals with a cobalt accent reserved for action, focus, selection and the current step; green, amber and red only as states, always with icon and words. Tokens in three layers in `web/src/index.css`; the design record is `docs/DESIGN.md`.
- Language and money: English first with every string in `web/src/i18n/en.ts` (more languages are new files); every amount shows its ISO code (`CLP 1,500,000`). The UI formats engine facts and never computes money.
- `/health` exposes `server_time` so countdowns use the API clock (fixed in recorded demos).
- The statements screen stays behind `VITE_FEATURE_STATEMENTS` until `/v1/statements` reaches `main`.
**Consequences:** the UI is one adapter over the contracts; a framework swap touches only `web/`. Open items for other roles: a typed `pending_proposal`, a flag for "the verifier replaced the reply", an HTTP profile endpoint, structured amounts in audit events, a purchase-segment breakdown for the simulator, and ISO-formatted amounts and month names in the copilot's narration.
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
---

## Bank statements and the transaction ledger

ADR-019 to ADR-024, ADR-031 and ADR-029 cover reading cartolas and posting them to the transaction ledger, and ADR-028 removes the personal data they carry. Each says whether it is **built** or **decided, not built**. O-1 and O-2 are open issues for further analysis; nothing is changed for them yet.

### ADR-019 · Statement import pipeline: ocr_tabular + one `Bank` per layout · Built
**Decision:** `ocr_tabular` (adapted into `adapters/outbound/statements/`) turns any PDF or image into word boxes and tables; a `Bank` subclass per layout (first: `SantanderCuentaMatica`) says where the table is and what the rows mean. Import = read → reconcile (domain) → store (once per user and statement) → audit `STATEMENT_IMPORTED`. Entry points: `neural-ledger import-statement`, `POST /v1/statements`, `GET /v1/statements[/{id}]`.
**Consequences:** a new bank is one file plus a registry line (recipe in `ARCHITECTURE.md`). Real cartolas live in the git-ignored `cartolas/`; tests use synthetic samples only. Text-layer PDFs need the `pdf` extra; scans and photos also need `ocr` (EasyOCR + torch, not in the Docker image). A scan holds the HTTP request open for minutes (~80 s per page on CPU); a background job is the next step if that matters.

### ADR-020 · Reconciliation is the authority over the reader · Built
**Decision:** the domain recomputes totals, the closing balance and every printed daily balance from the lines. Any misread amount, dropped line or wrong day breaks an equality. Because of that, the reader may be tolerant of OCR noise in amounts and dates (`102/09`, `1 _ 097 .805`), and low OCR confidence (< 0.5) only warns (`OCR_LOW_CONFIDENCE`): EasyOCR scores correct digits at 0.15–0.4, and descriptions are the only thing reconciliation cannot check.
**Consequences:** amounts are never trusted because the reader is confident, only because they add up.

### ADR-021 · Statements that do not reconcile go to the user for review, and are usable either way · Decided, not built
**Context:** today an unreconciled statement is stored as unverified (`STATEMENT_UNVERIFIED`) but **not** posted to the ledger (`NOT_POSTED`).
**Decision:**
1. Every statement that does not reconcile is shown to the user with its issues (which total or which day's balance differs, expected vs found).
2. The user can correct it by hand: a line's amount, date or description, add a missed line, or remove a duplicated one. Reconciliation runs again after each change.
3. It can be used either way: corrected and reconciling, or accepted by the user as it is. In both cases its movements are posted to the ledger.
4. Its transactions stay flagged as coming from an unverified statement until it reconciles. Envelopes that use them carry a warning the agent must mention.
5. The reading stays immutable. Corrections are stored separately (who, when, old → new value) and audited as user actions, so the original read can always be recovered.
**Consequences:** replaces the current "not posted" rule. Needs: a corrections record and store, a review list (`GET /v1/statements?verified=false` or similar), edit endpoints in the UI path only (never an agent tool), a new audit kind, contract changes and a `STATEMENTS_VERSION` bump. Amounts the user types are user input, not model output, so rule 2 (deterministic authority) holds.

### ADR-022 · Spending categories: a swappable classifier, gated by the domain · Built
**Decision:** a `TransactionClassifier` port guesses one category per charge. The default is naive Bayes (TF-IDF character n-grams, from `ocr_tabular/ml`), selected by `NL_CLASSIFIER` from a registry in `container.py`. The domain accepts a guess only if it is in the category vocabulary and has confidence ≥ 0.5; otherwise the charge is `uncategorized`. Deposits are `income` by rule. Bank boilerplate (`Compra Nacional MD`, `TDB`, `Pago`, …) is removed before features. The model trains at first use from a versioned CSV, is never pickled, and its name carries the training data's hash, recorded on every transaction with its confidence.
**Consequences:** changing the model or method is one adapter or one registry entry. On the real sample cartola only 2 of 45 charges were categorized: the training data (96 synthetic rows) is the limit, not the method (see O-2).

### ADR-023 · Categories can be changed by the user · Decided, not built
**Decision:** the user can set or change the category of any transaction, including choosing `Movimiento` (ADR-024). A manual category is stored with `classifier = "user"` and always wins over any model, including when a new model re-categorizes the ledger. Changes are audited as user actions.
**Consequences:** needs a category-override record, an endpoint in the UI path and a contract change. Manual labels are also the best source of new training rows. A row from a real user's statement can only be used locally, never committed.

### ADR-024 · New category `Movimiento` for money that is not spending or income · Decided; card side built (ADR-031)
**Context:** transfers to the user's own accounts, credit card payments, investments and savings (e.g. `Fondo Mutuo`, `Transf a Fintual`) are posted today as purchases. The financial core requires card payments and own transfers to count as `transfer_own`, never as spending, or cuotas are counted twice.
**Decision:**
- New category `movement`, shown to the user as **"Movimiento"**, with kind `transfer_own`. It applies in both directions: money in from the user's own account is also a Movimiento, not income.
- Movimientos are excluded from spending and income totals and listed in totals of their own.
- Rules come first, and they are deterministic and per bank, in the `Bank` layout: own-account transfers, card payments, mutual funds and investment platforms. A transfer to the account holder's own RUT is a Movimiento. The classifier may also suggest `movement` through the same confidence gate.
- The user can change it either way (ADR-023).
- A transfer to a third party stays spending (`other`) unless the user marks it as a Movimiento.
**Consequences:** vocabulary and contract change (`CATEGORIES`, `transactions.schema.json`), `CATEGORIZATION_VERSION` bump. Role A confirms that estimators read `transfer_own` this way.

### ADR-028 · Personal data is removed from a statement once, at import · Built
**Context:** identity is only the `X-User-Id` header, so anyone could read anyone's statements, with every description intact and the full account number (risk B). The planned `get_transactions` tool would also send that text to the language model's provider (risk A). Descriptions carry names, RUTs, account and card numbers, emails and phones.
**Decision:**
- **Once, at import.** Redaction runs right after reading, before anything is stored, classified, audited or returned. The statement as read lives only in memory during the import call.
- **Two layers.** Deterministic rules in `domain/privacy/redaction.py` always run and are the floor. They catch:
  - RUTs (módulo 11 decides `[ID]`; a failing check digit is still masked, as `[NUMBER]`);
  - runs of 7 or more digits, also split by spaces or dashes;
  - emails and Chilean phones;
  - names after `TRANSF` / `TRANSFERENCIA` / `TEF` / `TRASPASO` and `A` / `DE` / `DESDE` / `PARA`, with an own-account allowlist.

  An optional detector behind the `PersonalDataDetector` port runs after them and can only add masking. Azure AI Language is built but off by default (`NL_PII_DETECTOR=none`); a new detector is one adapter plus one `DETECTORS` entry.
- **Kept, as financial data:** employer and payee names (`REMUNERACION <company>`, `PAGO PROVEEDOR <company>`), merchants, `CUOTA nn/NN`, amounts, dates, short store numbers, the bank's document number and the branch code. `account_ref` keeps its last 4 digits (`****3456`).
- **Placeholders are stable codes:** `[PERSON]`, `[ID]`, `[NUMBER]`, `[EMAIL]`, `[PHONE]` and `[ADDRESS]`, enumerated in `contracts/common/redaction.schema.json`. They contain no digits, and the backend never translates them. The web shows them as translated chips (`redaction.<CODE>`), and the agent prompt says they mark hidden data the agent must not guess.
- **Fail closed:**
  - If redaction raises, the import is rejected (`INSUFFICIENT_DATA`, missing `redaction`), and nothing is stored, posted or audited.
  - If the detector is unavailable or answers something unusable, the rules alone run and the import is flagged degraded (`REDACTION_DEGRADED`, `degraded=yes` in the audit).
- **The statement id still hashes the statement as read,** so importing the same cartola again is still a duplicate. A duplicate is not redacted again, nor sent to a detector again.
- **Reporting:**
  - The import output gains `redaction` (rules version, detector, degraded flag, counts per code). The audit detail gains `redacted=<n> detector=<name>`, never text.
  - The classifier's training rows go through the same rules, and the rules version is part of its name.
  - `STATEMENTS_VERSION` moves to `st-0.2`.

**Consequences:**
- **Only financial data is stored or returned.** S15 checks every surface: the API, the audit export, the database files and the logs. What the header still exposes (risk B) is amounts, dates, merchants, categories and a masked account.
- **Names outside a transfer stay with the rules alone.** The rules are written for Chilean cartolas, so a name outside a transfer line (`PAGO A <name>`) is caught only by a detector. Extending the word lists needs real cartolas, checked locally in `cartolas/`, sharing counts only.
- **Transfers to different people now read the same** (`Transf a [PERSON]`). Grouping recurring transfers by counterparty, such as rent paid by transfer, would need a stable pseudonym; none is built.
- **ADR-024's "transfer to the holder's own RUT" rule,** when built, has to run inside the import, on the statement as read: stored text has no RUTs.
- **Statements stored before `st-0.2` keep their raw text.** There is no migration and no `redact-stored` command: delete the local database (`var/neural_ledger.db`, or `docker compose down --volumes`) and import again. Importing the same cartola into the old database counts as a duplicate and keeps the old copy.
- **A degraded import stays rules-only:** a statement imported while the detector was down keeps that redaction, because re-importing it is a duplicate.
- **Two accounts with the same last 4 digits share an `account_id` label;** their statement and transaction ids still differ, since those hash the statement as read. Someone who already holds a raw cartola could confirm it was imported, by hashing it.
- **Turning Azure on sends the raw text of every line to Microsoft.** Synchronous detection is stateless, and `loggingOptOut` is sent as true. See `SECURITY.md`.
- **pdfminer's loggers are capped at WARNING:** S15 found that pdfminer logs page text at DEBUG.
- **The team's "skill reverse engineering" idea,** if it turns out to be a detector, plugs in behind the same port.

### O-1 · Open: a corrected re-read of the same cartola is treated as a duplicate · For analysis
**Observed:** the statement id hashes bank, account, period and lines, but not the printed summary or daily balances. If a scan misreads only a printed balance, the statement is stored unverified. Importing the clean PDF of the same cartola then has the same id, counts as a duplicate, and the stored unverified copy wins.
**Options to analyse:**
- (a) Include the printed summary and balances in the id. Simple, but two readings of one cartola then both exist.
- (b) On a duplicate, supersede the stored copy when the new reading reconciles and the old one does not, keeping the old one as history.
- (c) Let ADR-021's manual review absorb it.
Decide together with ADR-021, since corrections and re-reads both change which version of a statement is current.

### O-2 · Open: category vocabulary, training data and re-categorization · For analysis
- **Vocabulary:** the ledger uses English slugs: the personas' `groceries, dining, health, shopping, transport, utilities`, plus `entertainment`, `other`, `income`, `uncategorized` (and `movement` from ADR-024). The Spanish training labels are mapped to them (Supermercado → groceries, …). To settle: the final list with Role A and E (the estimators and the generator group spend by category), and the Spanish UI labels.
- **Training data:** 96 synthetic rows with few of the merchants a real cartola shows. Options: more synthetic rows, manual labels from ADR-023 kept local, per-user models. The 0.5 confidence floor and the boilerplate word list should be re-checked once there is more data. Use a labelled hold-out set as the quality gate before changing the default model.
- **Re-categorization:** existing transactions keep their category on re-import, and there is no "re-categorize with the current model" yet. Manual categories (ADR-023) must survive it.
- **Classifier unavailable:** today the statement is stored but not posted, and re-importing backfills. Revisit with ADR-021, for example posting as `uncategorized` instead.

### ADR-031 · Two read pipelines (Excel, documents) and credit card statements with obligations · Built
**Context:** new cartolas arrived as Excel exports (Santander checking account; Banco BICE card, unbilled movements, CLP and USD) and as a card statement PDF (Banco Edwards: national CLP plus international USD in one file). Reading a spreadsheet through PDF or OCR would waste the work the export already did, and a card is not a checking account: its payments are not income, and it carries obligations.
**Decision:**
1. **Route by the bytes, never the file name.** `.xlsx` (zip with `xl/workbook.xml`) goes to `spreadsheet.py`, which uses only the standard library and never touches PDF or OCR. PDFs and images keep the existing path, and text-layer PDFs never run OCR. Legacy binary `.xls` is refused with a message to re-save it as `.xlsx`. Limits on parts and size and a refused DOCTYPE guard against zip and entity bombs.
2. **Two layout families:** `SheetBank.parse(sheets)` and `Bank.read(pages)`. A `Bank` reads a table per page by default (CuentaMática), or page lines when its rows are regular (the card statement). The reader returns every statement in the file, so a card PDF imports two, and `POST /v1/statements` answers with `imports: [...]`.
3. **Account type comes from the layout** (`checking` or `credit_card`), which is how a card is detected. On a card, signs are the holder's: purchases are negative, payments positive, and the debt (opening and closing balance) negative. Lines carry a `kind` (purchase, payment, refund, fee), their printed `section`, and their `Installment` (n of N, purchase amount, monthly rate, purchase date). A cuota of an older purchase is dated at the statement's end.
4. **Card statements in the standard A–G structure** are one layout (`cl_tarjeta_credito_pdf`), not one per bank: every section's lines must add up to its printed subtotal (`SECTION_TOTAL`), and opening debt plus lines must equal the billed total (`CLOSING_BALANCE`). A line the layout cannot read therefore breaks its section instead of vanishing.
5. **Obligations** (`CardObligations`): amount due, minimum, due date, credit limit, used and available, as printed. The cuotas still to bill are computed in the domain (`installment_plans`, `installment_schedule`); at 0 % the last cuota absorbs the rounding remainder, which matches the issuer's printed "vencimiento próximos 4 meses". When that schedule is printed, it is checked (`INSTALLMENT_SCHEDULE`). Obligations are exposed on the statement and as facts (`statement.<id>.amount_due`, `.minimum_due`, `.due_date`, `.installments_remaining`, …). They do not feed the forecast yet (ADR-029).
6. **Posting by kind on a card:** a payment is `card_payment` with category `movement` by rule (ADR-024, card side), never income. Refunds and fees keep their kinds and are classified like purchases. Ledger spending = purchases + fees − refunds; card payments count as neither spending nor income. A cuota carries its plan (`plan_id` stable across statements) into `Transaction.installment`, which the stage-1 estimator already reads.
7. **Unbilled exports are provisional:** they are read, checked against the printed `Total Cargos` / `Total Abonos`, and stored, but never posted (`NOT_POSTED`), because the next export and the billed statement repeat their lines.

`STATEMENTS_VERSION` st-0.2, `CATEGORIZATION_VERSION` cat-0.2. Contracts: `statement*.schema.json`, `transactions.schema.json`.
**Consequences:** statement ids changed (lines carry more fields, and the id includes the currency), so a statement imported before st-0.2 is not recognized as a duplicate of its re-import. Old stored payloads still load (missing fields default to checking, final, no sections). The BICE layout is recognized by wording only (the bank is named only in the logo), and the card layout has been seen from one issuer. A scanned card PDF goes through OCR, whose line text is untested against the card patterns. The bank's own category column in the BICE export is ignored (categories stay the classifier's and the user's, ADR-022/023).

### ADR-029 · Feed card obligations into the forecast · Plan, not built
**Goal:** the forecast and the surplus see the card's real obligations (the billed amount due on its date, and the cuotas left), estimated from imported statements instead of the fixture ledgers, without changing E01–E14.
**Plan, in order:**
1. **Prerequisite: the checking side of ADR-024.** Checking layouts mark payments to the card and own transfers as `transfer_own` (rules per bank: `PAGO TARJETA`, a transfer to the holder's own RUT, `Fondo Mutuo`, `Transf a Fintual`). Without this, a purchase is counted on the card and again when the checking account pays the card. This is the blocker.
2. **A `StatementLedgerSource` adapter** (`NL_MODEL_SOURCE=statements`, opt-in) builds a `LedgerSnapshot` from the posted transactions: accounts from the latest verified statement per account (checking balance = closing balance; card balance = −amount due), income profile and goals from the user record, and transactions as posted. It then runs the existing `estimate_model`. Personas and golden tests keep `fixture`.
3. **Cuotas need no new estimator logic:** card cuotas already carry `InstallmentInfo` with a `plan_id` that is stable across statements, so stage 1 turns them into `INSTALLMENT` commitments. Check them in a test against the statement's own `installment_schedule`. A known gap: the estimator uses the last cuota amount for every remaining month, while the issuer's last cuota absorbs the remainder (off by at most N−1 pesos). Decide whether stage 1 should take the remainder rule.
4. **Timing of card spend:** a card purchase leaves the checking account at the next due date, not on the purchase date. Role A decides whether stage 2 shifts card spend to the paying cycle, or keeps cycle-of-purchase (simpler, and conservative when the due date falls in the next cycle). Until then, the amount due is shown as an obligation, not projected.
5. **Currency:** the FinancialModel has one currency. USD card lines need a dated exchange rate from a port with an offline adapter (a fixed table), or they stay out of the model with a warning naming the USD amount due. Recommended: exclude them and warn first, add the FX port later.
6. **Unbilled exports** (provisional) stay out of the estimator. Optionally, the unbilled charges become a one-off commitment in the next cycle, with a warning; this needs a team decision.
7. **Quality gate before switching any default:** a backtest over several months of real, local statements, the golden E01–E14 unchanged under `fixture`, and a `params_version` bump if stage 1 changes (3 or 4).
**Needs:** Role A sign-off on 3–5, ADR-024 checking rules (1), and at least `min_history_months` of verified statements per user.

---

## Decision model and language model (Role B)

ADR-026 and ADR-027 are numbered after Role A's ADR-014 to ADR-018, the statements ADR-019 to ADR-024 and the frontend ADR-025; renumber them if the team orders it differently.

### ADR-026 · Jev first in the decision chain, through OpenRouter, pinned to jev-1.13.0 · Proposed (go/no-go 2026-10-14)
**Context:** the rules model is keyword based and unmeasured. OpenRouter serves the real Jev classifier (System One protocol at `POST /api/v1/systemone`, billed to the OpenRouter key), so no second provider or key is needed (D-02).
**Decision:** `NL_DECISION_CHAIN=jev,rules` in live mode; `rules` stays first-and-only in offline mode and is the fallback when Jev is down (S10). Jev is pinned to `jev-1.13.0` (`NL_JEV_MODEL`); the `jev-latest` alias moves when TypeSafe ships a release, which would silently change the calibration. Intent and injection are asked in one call, and each option of the intent question carries a short description (Jev reads criteria literally). The TypeSafe endpoint stays as a direct path when only `TYPESAFE_API_KEY` is set.
**Evidence** (`backend/tests/decision_eval`, 112 Spanish and English examples written by Role B; `python -m tests.decision_eval.run --model jev --model-id jev-1.13.0 --reverse-options`):

| | rules | Jev, names only | Jev, with descriptions |
|---|---|---|---|
| Intent correct (alternatives accepted) | 64% | 92% | 100% |
| Confident (>= 0.80) and wrong | 6 | 0 | 0 |
| Injection recall / false positives | 76% / 1 | 100% / 0 | 100% / 0 |

Reversing the option order changed the label in 2% of the cases, all ambiguous. Median latency 570 ms (p95 830 ms) per call.
**Limits:** the set is small, was written by the same person who wrote the option descriptions, and has no adaptive attacks or real user messages. The injection margin is narrow (lowest attack 0.64, highest legitimate request 0.31, threshold 0.5), and TypeSafe documents that text arguing for its own classification can move an answer.
**Consequences:** Jev is advisory. A fooled or down Jev must not open any door: S13 and S14 test it, and permissions, stored authorizations and the verifier stay deterministic. Next: enlarge the set with adaptive attacks and messages from teammates, then re-check the 0.80 and 0.55 thresholds.

### ADR-027 · OpenRouter is the only live LLM provider; the verifier allows one repair per turn (ap-0.2) · Proposed
**Context:** Groq's free tier (8,000 tokens per minute) cannot hold a turn that grows from about 3,700 to over 10,000 tokens. Claude 5.x models on OpenRouter reject `temperature`, and real models quote numbers from earlier turns or do their own arithmetic.
**Decision:** one live provider, OpenRouter (default `anthropic/claude-haiku-5.5`), with the scripted model as fallback. When the verifier rejects a reply only for `UNSUPPORTED_NUMBER` or `MISSING_WARNING`, the model gets one chance to fix it (`AgentPolicy.max_repairs=1`, `ap-0.2`, `max_tool_rounds` 6 to 8). Banned wording, contradictions and false execution claims are never retried, and there is no repair once an action was proposed. The rejected reply and the repair note are not stored in history, and the final reply is verified again.
**Consequences:** the verifier is not loosened (rule 4). Runs are not reproducible, so the recorded demo uses offline mode. Scene 2 still falls back to deterministic text until `alternative_N.total_interest` is a fact (Role A).

### ADR-030 · Versioned user profile, questionnaire, and scoped conversation history · Proposed
**Context:** the profile record replaces free-form user memory with typed fields and an optional questionnaire. Conversation history was keyed only by `session_id`, which permits unrelated identities to share context when they reuse an identifier. Profile names also reach a language model and must be treated as untrusted data.
**Decision:** persist questionnaire answers with their version and derive tolerance using `pq-0.1`: five questions with option scores 0/1/2; totals 0-3 map to conservative, 4-7 to moderate, and 8-10 to aggressive, with `tight_month=0` capping the result at moderate. Keep the versioned registry so historical submissions remain interpretable; accept only the current version for new submissions. Scope conversation history by `(user_id, session_id)`, a breaking change to the `ConversationStore` port with no legacy overload. Validate display names as 1-40 Unicode letters, ASCII spaces, periods, apostrophes, or hyphens, and wrap names in `untrusted_text` in profile views before they reach model requests.
**Consequences:** Other punctuation and control characters, including newlines, are rejected. Letter-only instructions can still be valid names; validation is not instruction detection, so model-facing names remain wrapped and deterministic policy remains authoritative. Combining marks outside Unicode letter categories are rejected rather than normalized, preserving the entered value. Profile editing use cases and SQLite/overlay persistence are deliberately unwired until PR3; PR1 exposes only the approved read-only HTTP getters.

## Personal data rights and the remaining security gaps (Role C)

### ADR-033 · Close G01–G07 and G11 before real users · Proposed (in progress on `c/compliance-gaps`)
**Context:** the compliance map (`docs/SECURITY.md`) lists the duties that Ley 21.719 (in force 2026-12-01) and the OWASP lists ask of us and that are not built. Each one is a strict xfail in `tests/security/test_compliance.py`. Real users need G01 to G07 and G11. PRs #27 (accounts HTTP API) and #26 (accounts web client), both drafts, add cookie sessions, `NL_AUTH=demo|accounts`, user accounts in memory and SQLite, profile writes and onboarding. This plan builds on them instead of beside them.
**Decision:** one gap per step, each turning its xfail into a plain test:
1. **G07 rate limiting. Built.** Per caller and per IP, one-minute windows, 429 with `Retry-After`. It also covers sign-in (`POST /v1/auth/*`, 10 per minute per IP), which #27 lists as deferred (D10). The limiter sits outside #27's identity guard, so rejected 400 and 401 requests also spend the budget. Its body has the shape of #27's error body (`status`, `message`).
2. **Merge #27 and #26 first, then staging into this branch.** Every later step reads accounts, uses #27's `user(request)` helper and touches the same files (`app.py`, `container.py`, `sqlite.py`, `ports.py`, `SECURITY.md`). A trial merge of this branch onto #26 has two small conflicts and the full suite passes.
3. **G01 authentication.** #27 closes it in accounts mode only; its strict xfail stays because the test runs the default demo app. Proposed closure, a team decision: the G01 test runs the API in accounts mode (401 without a session), and demo mode refuses to start in live mode, as G10 does for the development secret, so a public deployment cannot identify users by a header.
4. **G02 export.** `GET /v1/me/export`: one JSON document with the account (email, created and session times; never the password hash or a token digest), the profile and questionnaire, statements, transactions, conversation history, proposals, authorizations, savings rules and the user's audit events. It reuses the redacted views of the UI routes (ADR-028).
5. **G03 deletion.** `DELETE /v1/me/data` removes statements, transactions, conversation history and snapshots, and revokes pending proposals and unused authorizations; `DELETE /v1/me` also deletes the account and its profile and revokes its sessions. Both are accounts-mode routes: in demo mode the personas are shared and read-only, so deletion is 403. The audit chain keeps its events, which hold no holder identifiers (C10), on the legal-obligation basis, plus one `DATA_DELETED` event with counts only. This is the UI's "delete my data" button (#26 adds the account page it belongs on). A full reset of a local database is a developer command, next to #24's seed command, not an API route.
6. **G06 consent and G05 opposition and blocking.** One processing record per account and purpose (`statement_import`, `financial_advice`), with when and which text version was accepted, revocable through `PUT /v1/me/processing`. Consent is asked during #26's onboarding. An import without consent is 428 and advice under opposition is refused; blocking freezes all processing except export and deletion. Every change is audited. New statuses join #27's error body (`contracts/auth/error.schema.json`).
7. **G04 correction.** ADR-023 first: `PATCH /v1/transactions/{id}` sets a category with `classifier = "user"`, audited as a user action. ADR-021 line corrections follow. Starts after PR #25 (Jev categories) merges, since both touch the ledger's category fields.
8. **G11 encryption at rest.** Text columns that hold personal or financial data in SQLite (statements, transactions, conversations, and the account email from #27) are encrypted per field with AES-GCM in the SQLite adapter; the key comes from `NL_DATA_KEY`, never from the database. The email keeps an HMAC blind index so sign-in can still look it up. Amounts and dates stay queryable. The memory adapter needs no key.

**Consequences:** new routes, contracts and audit kinds land with each step. All of them are UI routes; the agent gets no tool for export, deletion, consent or correction. Store ports gain per-user delete and export methods, each with a memory and a SQLite adapter. Advice refused for opposition is a new status the UI must show. The audit trail surviving deletion must be stated in `docs/PRIVACY.md` (G12). Steps 4 to 8 wait for #27 and #26; G12 (documents only) can go meanwhile.
