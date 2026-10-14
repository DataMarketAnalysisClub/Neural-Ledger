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
| — | Audit log tampering | Chain verification fails at the edited event | — | `test_audit_chain_detects_tampering` |
| — | Reading another user's audit trail (same session id) | Empty result; chain status still reported | — | `test_audit_reads_are_scoped_to_the_caller` |

Each row of the final report should also record actual behaviour, pass or fail, mitigation and residual risk (Spec v0 §9). Run `make evidence` to export the audit log and JUnit results into `evidence/`.

## Compliance map (laws and standards)

`backend/tests/security/test_compliance.py` turns each requirement below into a test that names its norm. A **C** row is a built control and its test passes. A **G** row is a duty that is not built yet: its test is a strict xfail marked `GAP`, so CI stays green and the gap stays visible, and the day the control lands the test XPASSes and the run fails until the marker is removed. `test_every_compliance_test_is_in_the_security_map` fails if a C or G test is missing from this page. This is engineering evidence for counsel to review, not legal advice.

**Norms.** Ley 19.628 as amended by **Ley 21.719** (personal data; published 2024-12-13, **in force 2026-12-01**; article numbers per the [BCN summary of the law](https://obtienearchivo.bcn.cl/obtienearchivo?id=repositorio%2F10221%2F37137%2F1%2FInforme_12_25_Ley_Datos_Personales_rev.pdf)): art. 3 principles, arts. 5–9 rights, art. 12 consent, arts. 14 bis–14 sexies duties, art. 15 ter impact assessment, arts. 17–19 financial obligations data, art. 27 international transfers. **Ley 19.496** art. 3 b) (truthful, timely information). **Ley 21.663** (cybersecurity framework). **PCI DSS v4.0** (card data). **OWASP ASVS 5.0**, **OWASP API Security Top 10 (2023)**, **OWASP Top 10 for LLM Applications (2025)**.

**Existing attack tests and the norms they evidence:** S01, S13 → LLM01 prompt injection; S02, S03, S06, S13, S14 → LLM06 excessive agency; S04, S05, S11 → ASVS V2 business logic and V11 cryptography (HMAC, single use); S07, S08 → LLM09 misinformation and Ley 19.496 art. 3 b); S09 → suitability (hard rules H1–H5); S10 → fail closed (ASVS V16); S12 → ASVS V2 input validation; audit tests → Ley 21.719 art. 14 quinquies and ASVS V16.

### Built controls

| ID | Requirement | Norm | Test |
|---|---|---|---|
| `C01` | Card numbers are kept as the last four digits only, even when a statement prints the full PAN; nothing card-shaped is stored or returned | PCI DSS 3.3, 3.4.1; Ley 21.719 art. 3 c) | `test_c01_…` |
| `C02` | The holder's name, RUT and e-mail printed on a statement are never stored (database, WAL or audit) | Ley 21.719 art. 3 c) | `test_c02_…` |
| `C03` | Statement text reaches clients and the model only as `{"untrusted_text": …}` | LLM01; ASVS V1; Ley 19.496 art. 3 b) | `test_c03_…` |
| `C04` | A user cannot read another user's statements, transactions or audit events; a foreign id answers like a missing one | API1:2023; Ley 21.719 art. 14 bis | `test_c04_…` |
| `C05` | Uploads are typed by their bytes and bounded in size (HTML-as-PDF and legacy `.xls` refused; 413 over 15 MB) | API4:2023; ASVS V5 | `test_c05_…` |
| `C06` | Server errors expose no stack trace, path or message | ASVS V16; API8:2023 | `test_c06_…` |
| `C07` | The public repository tracks no `.env`, no key-shaped secret, no card number and no file under `cartolas/` | ASVS V13; Ley 21.719 arts. 3 h), 14 bis | `test_c07_…` |
| `C08` | SQL is never built from strings, and injection-shaped ids are plain ids | ASVS V1; API8:2023 | `test_c08_…` |
| `C09` | The language model never receives the HMAC secret or an API key | LLM02, LLM07 | `test_c09_…` |
| `C10` | The audit trail is hash-chained and holds no holder identifiers or card numbers | Ley 21.719 arts. 14 quinquies, 14 sexies; Ley 21.663; ASVS V16 | `test_c10_…` |
| `C11` | Chat input is cut at 4,000 characters before any model sees it | LLM10; API4:2023 | `test_c11_…` |
| `C12` | The tests that keep numbers traceable and warnings mentioned (S07, S08) stay in the suite | Ley 19.496 art. 3 b); LLM09 | `test_c12_…` |

### Gaps (strict xfail until built)

| ID | Missing control | Norm | Suggested fix |
|---|---|---|---|
| `G01` | Authentication: identity is the `X-User-Id` header | API2:2023; Ley 21.719 art. 14 quinquies | Session or token auth; reject requests without credentials (401) |
| `G02` | Export of all of a user's data | Ley 21.719 arts. 5, 9 | `GET /v1/me/export`, structured JSON |
| `G03` | Deletion of a user's statements and transactions | Ley 21.719 art. 7 | `DELETE /v1/me/data`; decide what the audit trail keeps (legal-obligation basis) |
| `G04` | Correction of records | Ley 21.719 art. 6 | ADR-021 and ADR-023 (`PATCH /v1/transactions/{id}`) |
| `G05` | Opposition to and blocking of processing | Ley 21.719 arts. 8, 8 ter | `PUT /v1/me/processing` |
| `G06` | Recorded, purpose-specific consent before a statement is processed | Ley 21.719 art. 12 | Consent record per user and purpose, revocable; imports refused without it |
| `G07` | Rate limiting | API4:2023; LLM10 | Per-user and per-IP limits, stricter on uploads and chat |
| `G08` | CORS open to any origin by default | API8:2023 | Default to the web app's origin; `*` only when set explicitly |
| `G09` | Security headers on responses | ASVS V3; API8:2023 | `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` on financial data |
| `G10` | Live mode starts with the development HMAC secret (it only warns) | ASVS V13; Ley 21.719 art. 14 quinquies | Raise instead of warn in `bootstrap/container.py` |
| `G11` | Statements and transactions stored in plaintext SQLite | Ley 21.719 art. 14 quinquies; ASVS V14 | Encrypted volume or SQLCipher; key outside the database |
| `G12` | Published privacy policy and breach response runbook | Ley 21.719 arts. 14 ter, 14 sexies; Ley 21.663 | `docs/PRIVACY.md`, `docs/runbooks/INCIDENT_RESPONSE.md` |

The routes in G02–G05 are proposals; change the test with the API design.

### Obligations reviewed but not testable as code

- **Impact assessment (Ley 21.719 art. 15 ter).** Profiling a person's finances from bank statements is likely high-risk processing. Write the assessment before real users.
- **International transfers (art. 27).** In live mode, prompts go to the LLM provider and, for Jev, to OpenRouter, both outside Chile. Prompts carry financial facts, not statements or identifiers (C09 covers secrets only). Document the safeguards before live use with real users.
- **Financial obligations data (arts. 17–19).** The app does not communicate anyone's debts to third parties. Keep it that way, or review these articles first.
- **Ley 21.521 (Fintec) and the Open Finance System (CMF NCG 514).** Not applicable while statements are uploaded by the user. Connecting to banks through the system's APIs brings its consent and security rules, and its start date should be confirmed with the CMF.
- **Ley 21.663.** Its incident duties (an early alert within 3 hours to the national CSIRT) bind essential services and operators of vital importance. The app is neither, and G12's runbook should follow the same steps anyway.
- **Children's data (art. 16 quáter).** There is no age check. Personas and uploads are assumed to be adults.

**Development tooling.** `npx ecc-agentshield scan` on the repository (2026-10-14) graded the agent configuration B (79/100). All 13 findings were about `CLAUDE.md` (missing prompt-defense wording, file group-writable). After a "Working safely" section in `CLAUDE.md` and a local `chmod 600` (file modes other than the executable bit are not tracked by git, so each checkout needs its own), the re-scan graded A (100/100) with no findings.

## Known risks (residual)

- **Identity is a header** (`X-User-Id`). Acceptable for a sandbox; real deployments need authentication and per-user authorization on every endpoint (G01).
- **`transfer_own` is trusted by the estimators** (ADR-012). A real outflow mislabelled as an own transfer would vanish from variable spend and overstate the protected surplus. The synthetic ledgers reconcile per account; real data would need two-leg matching of own transfers.
- **The rules decision model is keyword-based.** It is the offline floor, not the main defence. The hard guarantees come from the gate and the confirmation contract, which do not depend on any model.
- **The verifier checks numbers, warnings and a few phrases.** Semantic contradictions in free prose need the model-based check (Should).
- **No rate limiting** and no abuse detection on the API (G07).
- **The secret comes from the environment** (`NL_HMAC_SECRET`); a KMS is out of scope. The development default must never be used in a recorded demo.
- **Real statements are processed locally.** A developer's own cartolas in the git-ignored `cartolas/` are read on their machine; the repository and the test suite hold synthetic data only (C01, C02, C07). The repository is public: never commit keys or personal documents.
- **Estimator warnings are not forwarded.** `LedgerModelSource.load` discards the stage-1 `Envelope` warnings and facts, and estimation caveats have empty `must_mention`. Chat verification cannot enforce caveats it never receives; B must decide forwarding semantics before the ledger-default switch. See `docs/EXPLANATION_HANDOFF.md`.
- **The rolling-origin backtest is synthetic-only implementation validation.** Grid A December coverage is adverse without a prior December; this is not evidence of real-world predictive accuracy or a security mitigation. See `docs/BACKTEST.md`.
