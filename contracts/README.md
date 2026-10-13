# Contracts (source of truth)

JSON Schema 2020-12. If code and a contract disagree, the contract wins and the code gets fixed. `backend/tests/contract` validates real outputs against these files on every run.

| Folder | Contents |
|---|---|
| `common/` | `envelope.schema.json`: status, facts, warnings, snapshot_id, params_version |
| `tools/` | One `<tool>.input.schema.json` per agent tool. `description` is what the LLM reads; `x-tier` must match the tier in `application/catalog.py`; `x-owner` is the role |
| `outputs/` | The `data` of each financial tool, and of the bank statement and transaction ledger endpoints (`statement*.schema.json`, `transactions.schema.json`) |
| `actions/` | `action_terms` (the confirmation contract) and `action_outcome` |
| `audit/` | `audit_event` with the hash-chain fields |
| `chat/` | Chat request and reply |
| `ledger/` | `ledger.schema.json`: the sandbox ledger the stage-1 estimators read. Its limits (CLP only, \|amount\| ≤ 10^9) mirror `domain/finance/estimation.py`; `tests/contract/test_ledger_contract.py` keeps them aligned and validates the generated ledgers |
| `catalog/` | Existing financial Fact key templates, Caveat codes and error-field patterns; `test_fact_catalog.py` checks static emissions and runtime examples. Estimation-only warnings are not forwarded by the ledger adapter. |
| `backtest/` | `synthetic_backtest.schema.json`: full rolling-origin output, including observed metrics and the seeded finite-sample `reference` block (ADR-018, Proposed); `test_backtest_contract.py` validates the committed artifact and a small run. |

**Frontend (Role D):** generate TypeScript types instead of writing them by hand, e.g. `npx json-schema-to-typescript -i 'contracts/**/*.json' -o web/src/contracts`.

**Changing a contract:** a breaking change (removed or renamed field, new required field, tier change) needs a team decision and an entry in `docs/DECISIONS.md`.
