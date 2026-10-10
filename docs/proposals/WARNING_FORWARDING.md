# Proposal: forward stage-1 estimator evidence to ledger-mode tool envelopes (ADR-017, Proposed)

**Status: Proposed. Not accepted.** The fixture source stays the default; nothing here switches it (`docs/runbooks/MODEL_SOURCE_SWITCH.md`). The diff is implemented behind `NL_MODEL_SOURCE=ledger` so Role B can judge real behaviour. Role B answers the three questions below. A "no" on any of them reverts or reworks the matching part before FC-4.

## Approvals Role B must give (yes / no)

1. **Shape.** Yes / No: in ledger mode every OK financial tool envelope **appends** the estimator's facts and warnings **after** its own. The tool's `data`, `snapshot_id` and own facts and warnings are unchanged. Forwarded facts keep `key`, `value` and `unit`. Provenance is a fixed suffix on `derivation`: `; source=ledger-estimator; estimator_snapshot=<id>; tool_snapshot=<id>`. It is carried through an optional application port (`EstimationEvidenceSource`), wired only for the ledger source.
2. **Exact wording and tokens.** Yes / No: the nine messages and `must_mention` tokens in the table below. Every token is a case-insensitive substring of its own message. No message carries merchant, category, label, txn_id or an unbounded dynamic count; ADR-016's bounded seasonal-month count is unchanged.
3. **Verifier obligation.** Yes / No: forwarded warnings bind chat explanations exactly as tool warnings do today. The existing verifier semantics apply unchanged: English tokens; an explanation mentions a warning if it contains **any** of its tokens. An explanation that omits one is rejected (`MISSING_WARNING`), audited (`VERIFICATION_FAILED`) and replaced by deterministic narration.

## Wording and tokens (question 2)

Month names are static English names. Unbounded dynamic counts are omitted from warning prose because counts of 1,000 or more can be parsed as unsupported money by the unchanged verifier. ADR-016's seasonal-month count is bounded by the calendar and unchanged.

| Code | Message | `must_mention` |
|---|---|---|
| `DUPLICATE_TXN_ID` | `Transactions with a repeated id were dropped as exact duplicates.` | `exact duplicate` |
| `NEAR_DUPLICATE` | `Groups of transactions share date, amount and counterparty; they were kept as possible duplicates.` | `possible duplicate` |
| `INSTALLMENT_UNPARSED` | `Installment lines had no metadata and no readable CUOTA nn/NN; they were counted as variable spend.` | `variable spend` |
| `RECURRING_PROVISIONAL` | `Recurring items with only two payments replace an item that ended; they were taken as provisional commitments at their last amount.` | `provisional` |
| `SALARY_MISSING` | `A salary credit is missing in the last 3 cycles; contracted income was used.` | `missing` |
| `SALARY_DIFFERS` | `Recent salary credits differ from the contracted net by more than five percent; the lower was used.` | `differ` |
| `CONTRACT_UNKNOWN` | `No contracted net income; income was estimated from percentiles.` | `contracted net` |
| `CATEGORY_SPARSE` | `Spend categories with limited history were modelled together as 'other'.` | `modelled together` |
| `SEASONALITY_UNOBSERVED` | `{n} seasonal month(s) ({names}) are not in the estimation window; no seasonal uplift was applied for them (factor 1).` (unchanged, ADR-016) | the month names, `seasonal` |

Changes from the estimator-only wording:

- `NEAR_DUPLICATE` no longer lists the raw txn_ids. They are untrusted ledger text and would have reached the prompt and the fallback narration.
- `CATEGORY_SPARSE` no longer lists the ledger category names, for the same reason.
- `DUPLICATE_TXN_ID` says "dropped as exact duplicates" instead of "ignored".
- `RECURRING_PROVISIONAL` says "provisional commitments".
- `SALARY_DIFFERS` writes "five percent" in words. A literal `5%` would be an unsupported percentage for the verifier, so even the deterministic fallback would fail verification.
- Dynamic counts are omitted from the five count-bearing warnings. A ledger with 1,000 duplicate inputs reproduced `UNSUPPORTED_NUMBER:1000` in deterministic fallback before this wording change. Warning codes, actual computed counts and snapshot ids are unchanged.

No warning-code, computed-count, amount, snapshot-id or parameter changes.

## Explicit policies

- **Non-OK envelopes carry no evidence.** `INVALID_INPUT` and `INSUFFICIENT_DATA` envelopes are returned exactly as before. A ledger the estimator cannot build already maps to those statuses.
- **The estimator runs once per tool call.** `load_with_evidence` returns the model and its evidence from one `estimate_model` call. `FinancialUseCases.context()` (prompt as_of and currency) still calls `load()` separately, as today.
- **Repeated warnings across tools in one turn (proposed shape semantics, pending B approval).** Each OK tool envelope carries the estimator warnings. A turn that calls two tools has each warning twice in `ChatReply.warnings`. The deterministic narrator then repeats the sentence once per tool payload; it is not deduplicated. Chat, verifier and narrator are unchanged by this proposal. One mention satisfies the verifier for both copies, because every copy has the same tokens.
- **Provenance and colliding keys.** The same `estimate.*` key from two tools in one turn stays two facts. Key, value and unit are identical; the `tool_snapshot` in the derivation differs. Consumers must not dedupe facts by key. Provenance is a derivation-string convention, not a typed field: a typed field needs a change to the domain `Fact` and the envelope schema (`additionalProperties: false`), which is out of scope here.
- **Fixture source.** `FinancialUseCases` gets `evidence=None`. Its code path and serialized payloads are unchanged.

## Diff summary

| Area | Change |
|---|---|
| `application/ports.py` | `ModelEvidence(snapshot_id, facts, warnings)` and the optional `EstimationEvidenceSource.load_with_evidence` port |
| `adapters/outbound/fixtures/ledger_source.py` | `load_with_evidence` estimates once, with the same `InvalidInput` / `InsufficientData` mapping; `load()` delegates |
| `application/use_cases/financial.py` | Optional `evidence` argument; `_run` loads through it and `_forward` appends the evidence to OK results |
| `bootstrap/container.py` | `evidence=source` only for the ledger source |
| `domain/finance/estimation.py` | Wording and tokens above; `_caveat` takes tokens; no numeric change |
| `contracts/catalog/financial_core.catalog.json` | The nine estimation codes: `must_mention: true`, `reaches_tool_envelope: true` |
| `contracts/common/envelope.schema.json`, `contracts/README.md` | Provenance suffix and message rules documented; no shape change |
| Tests | `tests/contract/test_fact_catalog.py` (forwarding and provenance parity instead of the gap assertions), `tests/application/test_ledger_mode.py`, new `tests/application/test_warning_forwarding.py` and `tests/security/test_forwarded_warnings.py` |

## Consequences Role B should weigh

- **More speakable numbers.** Forwarded `estimate.income.*` and `estimate.spend.*` are CLP facts, so the verifier now accepts those amounts in ledger-mode explanations.
- **The ledger demo text changes.** Both generated persona ledgers seed a near-duplicate (S12, `backend/tests/fixtures/ledger_generator.py`), and the generator also plants an exact duplicate txn_id. Their estimator warnings now reach every financial tool, so the scripted narrator adds those sentences to each tool's narration. The fixture demo is unaffected. These warnings intentionally omit dynamic counts; warning codes and estimator computations do not change.
- **Spanish explanations.** Tokens are English. A live model answering in Spanish fails `MISSING_WARNING` and falls back to English narration. This already holds for the existing tool warnings' English tokens, except the few with Spanish stems.
- **Large counts.** The proposed count-free warning wording prevents the reproduced large-duplicate case from failing deterministic fallback verification. This wording remains subject to approval question 2.

## Evidence

Measured against the WP1 `ff4c7cf` baselines under `.agentic/runtime/qa/` with the repository's absolute `.venv/bin/python`:

- Targeted application, security and contract tests: **88 passed**. The chat test with 1,000 extra exact duplicates reproduced `UNSUPPORTED_NUMBER:1000` in deterministic fallback before the count-free wording; after it, the real chat reports `MISSING_WARNING:DUPLICATE_TXN_ID`, uses fallback and verifies that fallback. The short-history omission test reports `MISSING_WARNING:SEASONALITY_UNOBSERVED` and a verified fallback. Non-OK purchase envelopes are `INVALID_INPUT`, `field=installments`, with no facts/warnings.
- `make test-all`: **413 passed, 2 xfailed, 2 xpassed** (the existing plan/purchase property cases remain unchanged). `make test`: **399 passed, 18 deselected**. `make test-golden`: **55 passed**. `make test-security`: **22 passed**, including all 8 new forwarded-warning security cases. The one Starlette/TestClient `httpx` deprecation warning is pre-existing.
- `make demo` (fixture): stdout byte-identical to `base.fixture.demo.txt`. Its exported audit is byte-identical to `base.fixture.audit.jsonl`: **22 events**, unchanged snapshot ids and hashes. The full chain verifies.
- `make demo-ledger`: exactly **five AGENT lines** gain warning prose; seven appearances of the pair `DUPLICATE_TXN_ID` / `NEAR_DUPLICATE` (one pair each in forecast and the two purchase replies, two pairs each in the two-tool surplus and savings replies). Removing only these fourteen appended warning sentences yields the base demo byte-for-byte: all monetary text, statuses, action outcomes, tool calls and source/tool snapshot ids remain unchanged. All five replies print `verified=True`; there is **no new `VERIFICATION_FAILED` event or fallback**. The 22-event ledger audit is byte-identical to `base.ledger.audit.jsonl`, including every snapshot id, `prev_hash` and `event_hash`; chain verification passes.
- Each of the four audit exports (base/WP2, fixture/ledger) has 22 events: `DECISION` 6, `TOOL_CALL` 11, and one each of `PROPOSAL_CREATED`, `ACTION_CONFIRMED`, `EXECUTION_STARTED`, `ACTION_EXECUTED`, `ACTION_BLOCKED`; **zero `VERIFICATION_FAILED`**. Both WP2 audits have no changed event fields or hashes relative to their respective bases.
- `ruff check backend` and `git diff --check` pass. The diff is confined to the 18 WP2 scoped paths; `chat.py`, `verification.py`, `narration.py`, `params.py`, golden expectations, ledger/persona data, fixture adapter and source default remain unchanged. LSP was unavailable and its installation was declined; no server was installed.
- Execution note: the Claude implementation exceeded the shell window and its subsequent read-only review hit the personal session limit. One fallback session completed the scoped diff; Sisyphus independently repeated the full, golden and security suites (413/2/2, 55/0/0, 22/0/0), protected-path and audit comparisons. Supplemental Claude review remains unavailable; this evidence does not replace Role B's review.

**Approval remains pending:** Role B must answer Yes/No for the forwarding shape, the exact count-free wording/tokens, and the existing verifier obligation above. Test and demo evidence does not constitute business acceptance or authorize switching the default source.
