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
| `ledger/` | `ledger.schema.json`: the sandbox ledger the stage-1 estimators read. Its limits (CLP only, \|amount\| ≤ 10^9) mirror `domain/finance/estimation.py`; `tests/contract/test_ledger_contract.py` keeps them aligned and validates the generated ledgers |
| `memory/` | User memory (ADR-047, ADR-040): `memory_value` (the closed catalog `mem-0.1`, one type `salary_net`), `declaration` (a stored version, origin as an opaque reference), `salary_check` (what the statements say, derived on read), `memory_view` (`GET /v1/memory` and the answer of every memory write), `memory_summary` (`get_user_memory`: typed values, no text), `income_proposal` (`propose_income_change`), `income_declaration` (body of the proposal confirmation and of `PUT /v1/profile/income`), `memory_deletion`, `memory_export`, `warnings` (codes, each applied or saved only) and `memory_error` (with its HTTP status in `x-http-status`). `memory/tools/` holds the two tool schemas as drafts: they move to `tools/` together with their registry entry, since `tools/` must match the registry |
| `catalog/` | Existing financial Fact key templates, Caveat codes and error-field patterns; `test_fact_catalog.py` checks static emissions and runtime examples. Estimation-only warnings are not forwarded by the ledger adapter. |

**Frontend (Role D):** generate TypeScript types instead of writing them by hand, e.g. `npx json-schema-to-typescript -i 'contracts/**/*.json' -o web/src/contracts`.

**Changing a contract:** a breaking change (removed or renamed field, new required field, tier change) needs a team decision and an entry in `docs/DECISIONS.md`.
