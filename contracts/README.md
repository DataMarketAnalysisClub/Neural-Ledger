# Contracts (source of truth)

JSON Schema 2020-12. If code and a contract disagree, the contract wins and the code gets fixed. `backend/tests/contract` validates real outputs against these files on every run.

| Folder | Contents |
|---|---|
| `common/` | `envelope.schema.json`: status, facts, warnings, snapshot_id, params_version |
| `tools/` | One `<tool>.input.schema.json` per agent tool. `description` is what the LLM reads; `x-tier` must match the tier in `application/catalog.py`; `x-owner` is the role |
| `outputs/` | The `data` of each financial tool |
| `actions/` | `action_terms` (the confirmation contract) and `action_outcome` |
| `audit/` | `audit_event` with the hash-chain fields |
| `chat/` | Chat request and reply |
| `ledger/` | `ledger.schema.json`: the sandbox ledger the stage-1 estimators read. Its limits (CLP only, \|amount\| ≤ 10^9) mirror `domain/finance/estimation.py`; `tests/contract/test_ledger_contract.py` keeps them aligned and validates the generated ledgers |
| `catalog/` | Existing financial Fact key templates, Caveat codes and error-field patterns; `test_fact_catalog.py` checks static emissions and runtime examples. `reaches_tool_envelope` is true only for codes that actually reach a tool envelope; `must_mention` matches whether the runtime caveat carries tokens. |

### Forwarded estimator evidence (ADR-017, Proposed)

With `NL_MODEL_SOURCE=ledger`, every OK financial tool envelope ends with the stage-1 estimator's facts (`estimate.*`) and warnings, after the tool's own. The fixture source (the default) forwards nothing and its payloads are unchanged. Non-OK envelopes carry no evidence. The tool's `data` and `snapshot_id` do not change.

- Forwarded facts keep `key`, `value` and `unit`. Their `derivation` ends with `; source=ledger-estimator; estimator_snapshot=<id>; tool_snapshot=<id>`. Two tools in one chat turn therefore give two distinct facts with the same key; consumers must not dedupe by key.
- All nine estimation warnings carry `must_mention` tokens that are substrings of their own message. The five unbounded-count warnings use static count-free wording, while ADR-016's bounded seasonal-month count is unchanged. No estimator warning includes raw ledger text; a large count could be mistaken for unsupported money by the verifier.
- The proposal and the approvals Role B must give are in `docs/proposals/WARNING_FORWARDING.md`.

**Frontend (Role D):** generate TypeScript types instead of writing them by hand, e.g. `npx json-schema-to-typescript -i 'contracts/**/*.json' -o web/src/contracts`.

**Changing a contract:** a breaking change (removed or renamed field, new required field, tier change) needs a team decision and an entry in `docs/DECISIONS.md`.
