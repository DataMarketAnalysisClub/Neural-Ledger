# Privacy policy

Last updated: 2026-10-16.

**Status.** Neural Ledger is a sandbox built for FinTechathon 2026. By default it runs on synthetic data (the personas Camila and Diego, and generated cartolas) and moves no real money. It is not a production service and it is not financial advice. This page describes what the software in this repository does with personal data, so that a team that deploys it can publish it, and it lists what is not built yet. It does not say the app complies with the law. Ley 19.628 as amended by Ley 21.719 is in force from 2026-12-01; the compliance map in [SECURITY.md](SECURITY.md) lists this policy under art. 14 ter (`G12`). This is engineering documentation for counsel to review, not legal advice.

## Who is responsible

The team that runs an instance is responsible for the data it processes. Fill this in before publishing:

- Responsible: `[team or legal entity name]`
- Contact for privacy requests: `[contact email]`

## What is processed, where and for how long

**Where.** Two storage modes, set by `NL_PERSISTENCE`:

- `memory` (the default for `make api` and `make demo`): everything lives in the API process and is gone when it stops.
- `sqlite` (Docker always uses it): one file at `NL_SQLITE_PATH`, by default `./var/neural_ledger.db` relative to where the API runs. In Docker it is `/app/var/neural_ledger.db` on the `ledger-data` volume. The file is not encrypted (`G11`).

**How long.** There is no automatic retention period and nothing is deleted on a schedule. Data in SQLite stays until the operator deletes the database.

| Data | What is kept | Where |
|---|---|---|
| Bank statements (cartolas) you import | Bank, period, each line's date, amount, kind, cuotas and description, daily balances, totals and, for credit cards, the amount due, minimum, due date and credit limit. Personal data is removed at import, before anything is stored (ADR-028): names, RUTs, account and card numbers, emails and phones become placeholders such as `[PERSON]` and `[ID]`, and the account keeps its last 4 digits (`****3456`). Merchants, employer and payee names, amounts and dates stay. The uploaded file is read in memory and never written to disk. | Storage mode |
| Transaction ledger | Each line of a verified statement: date, signed amount, redacted description, kind, spending category, the model that chose it and its confidence, the masked account | Storage mode |
| Profile and questionnaire | Today these are the synthetic persona records (display name, language, declared risk tolerance), loaded at start and read-only through the API. Editing a profile and storing questionnaire answers (ADR-030) is not wired yet. | Memory only |
| Conversation history | Your chat messages (cut at 4,000 characters), the agent's replies and the tool results in between, the last 40 entries per user and chat session | Memory only, also in SQLite mode; gone when the API restarts |
| Savings proposals, authorizations and sandbox savings rules | Amount, currency, frequency, sandbox source and destination accounts, start date, status, expiry, the signature of the confirmed terms, user and session ids. No real bank is involved. | Storage mode |
| Audit trail | A hash-chained record of what happened: event kind, classified intent and confidence, decision model answers, tool name, a hash of its parameters, permission tier, authorization id, result, block reason, model version, a short detail, user and session ids. It holds no holder names, RUTs, emails or card numbers (`C10`); a statement import records counts (`redacted=<n> detector=<name>`), never text. Events cannot be edited or removed without breaking the chain. | Storage mode |
| Technical data | The user id sent in the `X-User-Id` header. The web app keeps a chat session id in the browser's `sessionStorage`; it sets no cookies. The API server (uvicorn) writes one line per request to standard output: client address, request line and status. Docker keeps it with the container's logs. | Server and browser |

The SQLite schema also has tables for accounts and sign-in sessions (email, scrypt password hash, a digest of the session token). Sign-up and sign-in are not wired to the API yet, so these tables stay empty.

## Why

To forecast your cash flow, simulate purchases, compute how much you can spend or save, suggest a savings plan, and run in the sandbox a savings rule you confirmed. Today the forecast and the plans compute from the persona model, not from imported statements (ADR-029 is not built). The audit trail exists to show what the agent did and to detect tampering. Your data is not used for marketing, not sold and not used to profile you for anyone else. The app does not communicate anyone's debts to third parties.

## Who receives data

With the default settings no data leaves the server. Each provider below receives data only when its setting is on. `GET /health` shows which are on (`mode`, `language_model`, `decision_chain`, `classifier`, `pii_detector`).

| Setting | Provider | What is sent |
|---|---|---|
| `NL_LLM=openrouter` | OpenRouter, which routes the request to the provider of the chosen model (default `anthropic/claude-haiku-5.5`) | The system prompt, the session's conversation history, your message, and the results of the tools the agent calls: financial figures, your profile (display name marked as untrusted text), pending actions and your audit events in the session. No agent tool returns statements or transactions. |
| `NL_LLM=anthropic` | Anthropic, directly | The same. ADR-027 chose OpenRouter as the only live provider; the code still accepts this setting. |
| `NL_DECISION_CHAIN` includes `jev` | Jev, through OpenRouter (or TypeSafe directly when only `TYPESAFE_API_KEY` is set) | Each chat message (cut at 4,000 characters), to classify intent and detect injection. For the risk-tolerance tool, the last 2,000 characters of your messages in the session. |
| `NL_CLASSIFIER` includes `jev` | Jev, through OpenRouter or TypeSafe | The text of each charge after redaction, to pick a spending category. Never a deposit (`C13`, ADR-032). |
| `NL_PII_DETECTOR=azure` | Microsoft (Azure AI Language) | The raw text of every imported statement line, before redaction, to find more personal data. Detection is synchronous and `loggingOptOut` is sent as true. |

These providers are outside Chile, so turning any of them on is an international transfer of data (Ley 21.719 art. 27). The safeguards for these transfers are not documented yet. Which agreements a deployer needs with each provider before turning them on is to confirm with counsel. API keys and the signing secret are never sent to the language model (`C09`).

## Security

[SECURITY.md](SECURITY.md) describes the controls and the tests behind them: redaction at import (S15), permission tiers, signed, single-use authorizations that only the user can confirm (the agent has no confirm tool), the hash-chained audit trail, closed CORS (`G08`), `nosniff` and `no-store` headers (`G09`), and a live mode that refuses the development signing secret (`G10`). Known gaps:

- **No authentication (`G01`).** Identity is the `X-User-Id` header. Anyone who can reach the API can read any user's statements and transactions: amounts, dates, merchants, categories and a masked account.
- **The SQLite file is not encrypted (`G11`).**
- **No rate limiting (`G07`).**
- **Redaction is rule-based and written for Chilean cartolas.** A name outside a transfer line (`PAGO A <name>`) stays unless a detector is on. Statements stored before `st-0.2` keep their raw text until the database is deleted.

## Your rights

Ley 21.719 gives you rights over your data (arts. 5–9). The software supports them only in part, as the table shows. Until it does, write to `[contact email]`. How fast a request must be answered is to confirm with counsel.

| Right | Article | In the software today | Meanwhile |
|---|---|---|---|
| A copy of all your data (access, portability) | arts. 5, 9 | Partly: `GET /v1/statements`, `/v1/transactions` and `/v1/audit` show your statements, transactions and audit events. No full export (`G02`). | The team exports it by hand. |
| Correction | art. 6 | Partly: you can change the category of any transaction, and the change is recorded (`G04`). Correcting a statement line's amount, date or description is not built yet (ADR-021). | The team corrects a line by hand. |
| Deletion | art. 7 | No per-user deletion (`G03`) | The operator can delete the whole database: the file at `NL_SQLITE_PATH` (and any `-wal` and `-shm` files next to it), or `docker compose down --volumes` in Docker. This removes every user's data, the audit trail and the sandbox bank. Removing one user's audit events would break the hash chain; what the trail keeps after a deletion request is an open decision (`G03`). |
| Opposition and blocking | arts. 8, 8 ter | No (`G05`) | Stop uploading statements and ask the team. |

**Consent.** Statements are processed when you upload them, without a recorded, purpose-specific consent (`G06`, art. 12).

## What is not built yet

Authentication (`G01`), the rights above (`G02`–`G05`), recorded consent (`G06`), rate limiting (`G07`), encryption at rest (`G11`), the documented safeguards for transfers abroad (art. 27), the impact assessment (art. 15 ter) and an age check (art. 16 quáter; users are assumed to be adults).

## Breaches

If personal data is exposed, the team follows [runbooks/INCIDENT_RESPONSE.md](runbooks/INCIDENT_RESPONSE.md).

## Changes to this policy

This policy changes in this file, through the repository's normal review, and the date at the top changes with it. A deployer should tell its users about changes before they apply; how is to be decided by the team that runs the instance.
