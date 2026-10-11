# Contracts (source of truth)

JSON Schema 2020-12. If code and a contract disagree, the contract wins and the code gets fixed. `backend/tests/contract` validates real outputs against these files on every run.

| Folder | Contents |
|---|---|
| `common/` | `envelope.schema.json`: status, facts, warnings, snapshot_id, params_version |
| `tools/` | One `<tool>.input.schema.json` per agent tool. `description` is what the LLM reads; `x-tier` must match the tier in `application/catalog.py`; `x-owner` is the role |
| `outputs/` | The `data` of each financial tool, and of the bank statement endpoints (`statement*.schema.json`) |
| `actions/` | `action_terms` (the confirmation contract) and `action_outcome` |
| `audit/` | `audit_event` with the hash-chain fields |
| `chat/` | Chat request and reply |

**Frontend (Role D):** generate TypeScript types instead of writing them by hand, e.g. `npx json-schema-to-typescript -i 'contracts/**/*.json' -o web/src/contracts`.

**Changing a contract:** a breaking change (removed or renamed field, new required field, tier change) needs a team decision and an entry in `docs/DECISIONS.md`.
