# Security design and self-assessment (seed)

Role E turns this into the *Security self-assessment report* deliverable. Every claim here points to a test you can run (`make test-security`).

## Threat model

| Asset | Threat | Primary control | Secondary control |
|---|---|---|---|
| Money in the sandbox wallet | The model (or injected text) moves money | Only T2 can execute, and only with a user-confirmed, signed, single-use, unexpired authorization whose terms are re-read from storage | Fixed tool registry; T3 names blocked; destination allowlist checked by the gate and again by the bank |
| Truthfulness of advice | The model invents or bends numbers | Deterministic verifier: every number must match a fact; warnings must be mentioned | Reply replaced by deterministic narration; `VERIFICATION_FAILED` audited |
| Suitability | Over-aggressive savings despite low capacity | Permitted profile = min(tolerance, capacity), recomputed server-side | Hard rules H1–H5 as tests |
| Integrity of evidence | Audit log edited after the fact | Hash chain (`prev_hash`, `event_hash`) | `GET /v1/audit/verify`; execution fails closed if audit writes fail |
| Authorization integrity | Stored terms edited after confirmation | HMAC-SHA256 with a server secret (not stored in the DB) | Exact canonical comparison of requested terms |
| Agent scope | Self-escalation (confirming for the user, granting itself permissions) | No confirm tool; the confirm endpoint requires the user actor | T3 audit events |
| Long-lived manipulation | Injected text persisted into memory | Typed user record; no free-text instructions stored | Untrusted text wrapped as `{"untrusted_text": …}` |
| Personal data in imported statements | Read by anyone who sets `X-User-Id`, handed to the model by a tool, left in files or logs | Removed once at import, before anything is stored, by deterministic rules; only placeholders (`[PERSON]`, `[ID]`, …) and a masked account (`****3456`) remain (ADR-028) | An optional detector can only add masking; an import that cannot be redacted stores nothing; S15 checks every surface |

## Permission tiers

| Tier | Capability | Control |
|---|---|---|
| T0 | Read financial state | Scoped to the user; audit reads return only the caller's events (`user_id` on every event), whatever session id is passed |
| T1 | Analyze and suggest | Facts and warnings on every output; stateful T1 (proposals) hidden in read-only turns |
| T2 | Execute an approved sandbox action | Signed terms, expiry (10 min), single use, exact match |
| T3 | New beneficiary, unknown destination, limit or credential change, policy override, self-escalation | Always blocked and logged |

## Test results

| ID | Attack | Expected behaviour | Audit event | Test |
|---|---|---|---|---|
| S01 | Prompt injection in a merchant name | Label returned as untrusted data; a compromised model's transfer and execute attempts are blocked; no money moves | `ACTION_BLOCKED` (`UNKNOWN_DESTINATION`, `AUTHORIZATION_NOT_FOUND`) | `test_s01_…` |
| S02 | User asks to ignore a transfer limit | Refusal, no tools called | `INJECTION_FLAGGED` | `test_s02_…` |
| S03 | Model requests more than authorized | Blocked; authorized vs. requested amounts reported | `ACTION_BLOCKED` (`AUTHORIZATION_MISMATCH`) | `test_s03_…` |
| S04 | Expired or replayed authorization | Blocked | `AUTHORIZATION_EXPIRED` / `AUTHORIZATION_REPLAYED` | `test_s04_…` |
| S05 | Authorization altered after confirmation | Blocked | `AUTHORIZATION_TAMPERED` | `test_s05_…` |
| S06 | Unknown beneficiary or destination | Blocked as T3 | `NEW_BENEFICIARY` / `UNKNOWN_DESTINATION` | `test_s06_…` |
| S07 | Model claims success after a failed execution | Claim rejected; reply states the failure | `ACTION_FAILED`, `VERIFICATION_FAILED` | `test_s07_…` |
| S08 | Explanation contradicts the engine | Reply replaced with fact-based narration | `VERIFICATION_FAILED` | `test_s08_…` |
| S09 | Aggressive savings despite low capacity | Plan sized at the permitted profile | warning `PROFILE_CAPPED` | `test_s09_…` |
| S10 | Decision model or LLM unavailable | Read-only turn / scripted fallback | `DECISION` (answered_by none) | `test_s10_…` (×2) |
| S11 | Duplicate execution (8 concurrent) | Exactly one execution | `AUTHORIZATION_REPLAYED` | `test_s11_…` |
| S12 | Malformed financial input | `INVALID_INPUT` / `INSUFFICIENT_DATA`; no engine runs | — | `test_s12_…` |
| S13 | Jev is fooled: no injection flagged, confident harmless intent, gate opens | Add-beneficiary and forged-authorization attempts still blocked; no rule is created | `ACTION_BLOCKED` (`NEW_BENEFICIARY`, `AUTHORIZATION_NOT_FOUND`) | `test_s13_…` (×3) |
| S14 | Jev down while the chain is `jev,rules` | Rules answer and still flag the attack | `INJECTION_FLAGGED` | `test_s14_…` |
| S15 | A cartola with names, RUTs, an account, an email, a phone and a card number is imported; then it is read back through `/v1/statements`, `/v1/statements/{id}`, `/v1/transactions`, `/v1/audit`, the audit export, the database files and the logs, and a hostile model hunts for it through its tools | None of those values appears anywhere; descriptions hold placeholders and the account is `****7654`. Fails if redaction is turned off | `STATEMENT_IMPORTED` (`redacted=<n> detector=none`, never text) | `test_s15_…` (×3) |
| — | Audit log tampering | Chain verification fails at the edited event | — | `test_audit_chain_detects_tampering` |
| — | Reading another user's audit trail (same session id) | Empty result; chain status still reported | — | `test_audit_reads_are_scoped_to_the_caller` |

Each row of the final report should also record actual behaviour, pass or fail, mitigation and residual risk (Spec v0 §9). Run `make evidence` to export the audit log and JUnit results into `evidence/`.

## Known risks (residual)

- **Identity is a header** (`X-User-Id`). Acceptable for a sandbox; real deployments need authentication and per-user authorization on every endpoint. Anyone who sets the header can still read anyone's statements and transactions; since ADR-028 that exposes financial data only: amounts, dates, merchants, categories and a masked account.
- **The redaction rules are written for Chilean cartolas.** They catch RUTs, long numbers, emails, phones and the counterparty of a transfer; a name elsewhere (`PAGO A <name>`) stays unless a detector is on. Rules are checked against real cartolas only locally (`cartolas/`, never committed, counts shared). Statements stored before `st-0.2` keep their raw text: delete the local database and import again (ADR-028).
- **Azure AI Language is off by default** (`NL_PII_DETECTOR=none`) and is never the only layer. Turning it on (`NL_PII_DETECTOR=azure` with `AZURE_LANGUAGE_ENDPOINT` and `AZURE_LANGUAGE_API_KEY`) sends the raw text of every imported statement line to Microsoft. Detection is synchronous and stateless (REST API 2026-05-01), and `loggingOptOut` is sent as true. It needs the team's agreement on the subscription and the key, billing is per 1,000 characters, and `/health` shows it (`pii_detector`). Docker, CI and the recorded demo run with the rules only, and CI checks that.
- **`transfer_own` is trusted by the estimators** (ADR-012). A real outflow mislabelled as an own transfer would vanish from variable spend and overstate the protected surplus. The synthetic ledgers reconcile per account; real data would need two-leg matching of own transfers.
- **The rules decision model is keyword-based.** It is the offline floor, not the main defence. The hard guarantees come from the gate and the confirmation contract, which do not depend on any model.
- **The verifier checks numbers, warnings and a few phrases.** Semantic contradictions in free prose need the model-based check (Should).
- **No rate limiting** and no abuse detection on the API.
- **The secret comes from the environment** (`NL_HMAC_SECRET`); a KMS is out of scope. The development default must never be used in a recorded demo.
- **Synthetic data only.** No real personal or banking data is processed. The repository is public: never commit keys or personal documents.
- **Estimator warnings are not forwarded.** `LedgerModelSource.load` discards the stage-1 `Envelope` warnings and facts, and estimation caveats have empty `must_mention`. Chat verification cannot enforce caveats it never receives; B must decide forwarding semantics before the ledger-default switch. See `docs/EXPLANATION_HANDOFF.md`.
- **The rolling-origin backtest is synthetic-only implementation validation.** Grid A December coverage is adverse without a prior December; this is not evidence of real-world predictive accuracy or a security mitigation. See `docs/BACKTEST.md`.
