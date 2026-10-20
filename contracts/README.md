# Contracts (source of truth)

JSON Schema 2020-12. If code and a contract disagree, the contract wins and the code gets fixed. `backend/tests/contract` validates real outputs against these files on every run.

| Folder | Contents |
|---|---|
| `common/` | `envelope.schema.json`: status, facts, warnings, snapshot_id, params_version. `redaction.schema.json`: the placeholder codes (`PERSON`, `ID`, …) that replace personal data in statement and transaction text (ADR-028); clients translate them, the backend never does. `rate_limited.schema.json`: the body of a 429 (G07) |
| `tools/` | One `<tool>.input.schema.json` per agent tool. `description` is what the LLM reads; `x-tier` must match the tier in `application/catalog.py`; `x-owner` is the role |
| `outputs/` | The `data` of each financial tool, and of the bank statement and transaction ledger endpoints (`statement*.schema.json`, `transactions.schema.json`) |
| `actions/` | `action_terms` (the confirmation contract) and `action_outcome` |
| `audit/` | `audit_event` with the hash-chain fields |
| `chat/` | Chat request and reply |
| `auth/` | Accounts mode (`NL_AUTH=accounts`) HTTP bodies: `signup_request`, `signin_request`, `demo_session_request`, `session` (signup, signin and demo-session responses), `me` (`GET /v1/me`; `data_source` is `statements` once the account's own statements feed its financial model, ADR-029) and `error` (`AuthError` for HTTP, body, guard and auth errors, with its HTTP status in `x-http-status`). The session token travels only in the HttpOnly `nl_session` cookie, never in a body; no error echoes an email, password, token or supplied value |
| `profile/` | `questionnaire` and `questionnaire_submission` (`POST /v1/profile/questionnaire`), and `profile_update` (`PUT /v1/profile`: display name and language only; the tolerance comes only from the questionnaire). Both writes are user-only, accounts-mode HTTP flows that commit with their `PROFILE_UPDATED` audit event or not at all. Domain validation errors and compare-and-swap conflicts use `common/envelope.schema.json`, not `AuthError` |
| `transactions/` | `category_update` (`PATCH /v1/transactions/{txn_id}`, ADR-023): the user sets one transaction's category; the categories allowed depend on its kind. User-only, UI path, audited as `CATEGORY_CHANGED`; errors use `common/envelope.schema.json` |
| `connections/` | Read-only connections (ADR-047): `connection` and `connections` (`GET /v1/connections`), `connection_create` (`POST /v1/connections`, an MCP server; the token is never returned), `tools_update` (`PUT /v1/connections/{id}/tools`), `sync_result` (`POST /v1/connections/{id}/sync`; a bank sync carries a `statement_import`), `bank_start` and `bank_exchange` (`POST /v1/connections/bank/start`, `POST /v1/connections/bank`). The agent reads `outputs/connected_data` through `get_connected_data` (T0); every write is the user's |
| `ledger/` | `ledger.schema.json`: the sandbox ledger the stage-1 estimators read. Its limits (CLP only, \|amount\| ≤ 10^9) mirror `domain/finance/estimation.py`; `tests/contract/test_ledger_contract.py` keeps them aligned and validates the generated ledgers |
| `catalog/` | Existing financial Fact key templates, Caveat codes and error-field patterns; `test_fact_catalog.py` checks static emissions and runtime examples. Estimation-only warnings are not forwarded by the ledger adapter. |

**Frontend (Role D):** generate TypeScript types instead of writing them by hand, e.g. `npx json-schema-to-typescript -i 'contracts/**/*.json' -o web/src/contracts`.

**Changing a contract:** a breaking change (removed or renamed field, new required field, tier change) needs a team decision and an entry in `docs/DECISIONS.md`.
