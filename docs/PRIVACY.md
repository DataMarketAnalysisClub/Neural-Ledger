# Privacy policy

Last updated: 2026-10-19.

**Status.** Neural Ledger is a sandbox built for FinTechathon 2026. Anyone can create an account on a public demo, and the sign-up page asks every new user to acknowledge that it is a sandbox: **do not upload real bank statements or enter real personal data**. The acknowledgement is recorded. By default it runs on synthetic data (the personas Camila and Diego, and generated cartolas) and moves no real money. It is not a production service and it is not financial advice. This page describes what the software in this repository does with personal data, so that a team that deploys it can publish it, and it lists what is not built yet. It does not say the app complies with the law. Ley 19.628 as amended by Ley 21.719 is in force from 2026-12-01; the compliance map in [SECURITY.md](SECURITY.md) lists this policy under art. 14 ter (`G12`). This is engineering documentation for counsel to review, not legal advice.

## Who is responsible

The team that runs an instance is responsible for the data it processes. Fill this in before publishing:

- Responsible: `[team or legal entity name]`
- Contact for privacy requests: `[contact email]`

## What is processed, where and for how long

**Where.** Two storage modes, set by `NL_PERSISTENCE`:

- `memory` (the default for `make api` and `make demo`): everything lives in the API process and is gone when it stops.
- `sqlite` (Docker always uses it): one file at `NL_SQLITE_PATH`, by default `./var/neural_ledger.db` relative to where the API runs, which is `backend/var/neural_ledger.db` with the `make` targets. In Docker it is `/app/var/neural_ledger.db` on the `ledger-data` volume. Everything personal in it is encrypted with AES-256-GCM (`G11`): statements, transactions, profiles and questionnaire answers, accounts (the email is kept only as a keyed hash for sign-in), proposals, authorizations, savings rules, the audit trail, a linked investment account with what each sync read, and the investment documents you import. Ids and dates used to find and order rows stay readable. The key is kept apart from the file; on a server, as a Docker secret outside the data volume ([SECURITY.md](SECURITY.md), "Data at rest and key management").

**How long.** There is no automatic retention period and nothing is deleted on a schedule. Data stays until you delete your account (below) or the operator deletes the database.

| Data | What is kept | Where |
|---|---|---|
| Bank statements (cartolas) you import | Bank, period, each line's date, amount, kind, cuotas and description, daily balances, totals and, for credit cards, the amount due, minimum, due date and credit limit. Personal data is removed at import, before anything is stored (ADR-028): names, RUTs, account and card numbers, emails and phones become placeholders such as `[PERSON]` and `[ID]`, and the account keeps its last 4 digits (`****3456`). Merchants, employer and payee names, amounts and dates stay. The uploaded file is read in memory and never written to disk. | Storage mode |
| Receipts (boletas) you add on the copilot | The store's name as printed, the date, the total, the folio, whether the SII stamp confirmed it, a spending category and any problem found reading it. The store's name goes through the same redaction as a statement line before it is stored; the store's RUT is used only to recognize the same receipt again and is never stored; any other line (items, a customer's name or RUT) is not kept. The file is read in memory and never written to disk (ADR-039). | Storage mode |
| Transaction ledger | Each line of a verified statement: date, signed amount, redacted description, kind, spending category, the model that chose it and its confidence, the masked account | Storage mode |
| Account | Email and a scrypt hash of the password (never the password), creation time, whether you chose sample data. The email is stored encrypted and found through a keyed hash. | Storage mode |
| Profile and questionnaire | Display name, language, the questionnaire answers and the tolerance derived from them. The personas Camila and Diego are synthetic, read-only fixtures. | Storage mode |
| Conversation history | Your chat messages (cut at 4,000 characters), the agent's replies and the tool results in between, the last 40 entries per user and chat session | Memory only, also in SQLite mode; gone when the API restarts |
| Investment documents (Fintual), if you import them | From the investment statement: each fund and series with its shares, value per share and balance, and the total, on the statement's day. From the transactions certificate: each contribution and withdrawal with its day, goal name, fund, shares and pesos, and whether it was a move between your goals. Not your name or RUT: they are printed on the documents but never read. Goal names are kept without personal data (ADR-028). Only a document whose figures add up is kept, once, up to your last 24 imports; the file itself is not kept. **Investments → Delete imported documents** deletes them (ADR-044). Accounts only: demo mode and the demo personas cannot import. | Storage mode |
| Investment account (Fintual), if you link one (in development) | The Fintual email you typed and the access token Fintual returns, when you linked it and whether Fintual still accepts it. Never your Fintual password: it is sent to Fintual once and dropped. Each sync keeps the name, value and net deposits of each of your goals, up to the last 400 syncs. Unlinking deletes all of it; your account at Fintual does not change, and the token stays valid there until it expires (ADR-044). Accounts only: demo mode and the demo personas cannot link. | Storage mode |
| Savings proposals, authorizations and sandbox savings rules | Amount, currency, frequency, sandbox source and destination accounts, start date, status, expiry, the signature of the confirmed terms, user and session ids. No real bank is involved. | Storage mode |
| Audit trail | A hash-chained record of what happened: event kind, classified intent and confidence, decision model answers, tool name, a hash of its parameters, permission tier, authorization id, result, block reason, model version, a short detail, user and session ids, and at sign-up the version of the sandbox notice you acknowledged. It holds no holder names, RUTs, emails or card numbers (`C10`); a statement import records counts (`redacted=<n> detector=<name>`), never text. Events cannot be edited without breaking the chain; when you delete your account they are erased and only their place in the chain stays. | Storage mode |
| Technical data | In accounts mode, a session cookie (`nl_session`, HttpOnly, 12 hours) whose token is stored only as a digest. In demo mode, the user id sent in the `X-User-Id` header. The web app keeps a chat session id in the browser's `sessionStorage`. The API server (uvicorn) writes one line per request to standard output: client address, request line and status. Docker keeps it with the container's logs. | Server and browser |

## Why

To forecast your cash flow, simulate purchases, compute how much you can spend or save, suggest a savings plan, and run in the sandbox a savings rule you confirmed. Today the forecast and the plans compute from the persona model, not from imported statements (ADR-029 is not built). If you import your investment documents or link an investment account, they are read to show you what you hold, what you put in and how it has done, and to answer your questions about it; the agent describes those figures and never recommends an investment. The documents are read on the server: they are never sent to a language model or to any provider. The audit trail exists to show what the agent did and to detect tampering. Your data is not used for marketing, not sold and not used to profile you for anyone else. The app does not communicate anyone's debts to third parties.

## Who receives data

With the default settings no data leaves the server. Each provider below receives data only when its setting is on. `GET /health` shows which are on (`language_model`, `decision_chain`, `classifier`, `pii_detector`, `investments`); `mode` is `live` as soon as any of them sends data out.

| Setting | Provider | What is sent |
|---|---|---|
| `NL_LLM=openrouter` | OpenRouter, which routes the request to the provider of the chosen model (default `anthropic/claude-haiku-5.5`) | The system prompt, the session's conversation history, your message, and the results of the tools the agent calls: financial figures, your profile (display name marked as untrusted text), pending actions and your audit events in the session. No agent tool returns statements or transactions. |
| `NL_LLM=anthropic` | Anthropic, directly | The same. ADR-027 chose OpenRouter as the only live provider; the code still accepts this setting and logs a deprecation warning at startup. |
| `NL_DECISION_CHAIN` includes `jev` | Jev, through OpenRouter (or TypeSafe directly when only `TYPESAFE_API_KEY` is set) | Each chat message (cut at 4,000 characters), to classify intent and detect injection. For the risk-tolerance tool, the last 2,000 characters of your messages in the session. |
| `NL_CLASSIFIER` includes `jev` | Jev, through OpenRouter or TypeSafe | The text of each charge after redaction, to pick a spending category. Never a deposit (`C13`, ADR-032). |
| `NL_EMAIL_CHECKS` includes `dns` (Docker sets it) | The DNS resolver the server uses | At sign-up, only the domain of your email (the part after `@`), to check that it exists and receives mail. Never the address or anything else. The disposable-inbox check runs offline. |
| `NL_PII_DETECTOR=azure` | Microsoft (Azure AI Language) | The raw text of every imported statement line, before redaction, to find more personal data. Detection is synchronous and `loggingOptOut` is sent as true. |
| `NL_INVESTMENTS=fintual` | Fintual (Chile), only when you link your account there | When you link: the email and password you type, once, to get an access token. On each sync: that email and token, to read your goals. Nothing else of yours is sent; Fintual is the source of these figures. The default, `fixture`, links a synthetic account and sends nothing. The public demo refuses `fintual` (ADR-044). |

Every provider above except Fintual is outside Chile, so turning any of them on is an international transfer of data (Ley 21.719 art. 27). The safeguards for these transfers are not documented yet. Which agreements a deployer needs with each provider before turning them on is to confirm with counsel. API keys and the signing secret are never sent to the language model (`C09`).

## Security

[SECURITY.md](SECURITY.md) describes the controls and the tests behind them: redaction at import (S15), permission tiers, signed, single-use authorizations that only the user can confirm (the agent has no confirm tool), the hash-chained audit trail, closed CORS (`G08`), `nosniff` and `no-store` headers (`G09`), and a live mode that refuses the development signing secret (`G10`). Known gaps:

- **Demo mode has no authentication (`G01`).** In demo mode (local runs) identity is the `X-User-Id` header and anyone who can reach the API can read any user's statements and transactions. Docker and the public demo run in accounts mode: sign-up, sign-in and a session cookie.
- **Sign-up is open on the public demo.** The sandbox notice asks you not to upload real data, but nothing can stop it; whatever you upload is encrypted at rest and you can delete it.
- **The demo personas are shared.** A statement uploaded while exploring as Camila or Diego is visible to every other visitor of that persona until someone resets it.
- **Redaction is rule-based and written for Chilean cartolas.** A name outside a transfer line (`PAGO A <name>`) stays unless a detector is on. Statements stored before `st-0.2` keep their raw text until the database is deleted.

## Your rights

Ley 21.719 gives you rights over your data (arts. 5–9). The software supports them only in part, as the table shows. Until it does, write to `[contact email]`. How fast a request must be answered is to confirm with counsel.

| Right | Article | In the software today | Meanwhile |
|---|---|---|---|
| A copy of all your data (access, portability) | arts. 5, 9 | Partly: `GET /v1/statements`, `/v1/transactions` and `/v1/audit` show your statements, transactions and audit events. No full export (`G02`). | The team exports it by hand. |
| Correction | art. 6 | Partly: you can change the category of any transaction, and the change is recorded (`G04`). Correcting a statement line's amount, date or description is not built yet (ADR-021). | The team corrects a line by hand. |
| Deletion | art. 7 | Yes (`G03`): **Profile → Delete account**, with your password and the word DELETE (or your email). It deletes your account, profile, questionnaire answers, statements, transactions, proposals, authorizations, savings rules, a linked investment account with its synced goals, the investment documents you imported, and every session at once. To remove only the investment account, unlink it; to remove only the documents, delete them in Investments. Your audit events are erased: the chain keeps only their place and one deletion event with counts, without your id. | If you lost your password, the team deletes the account by hand. |
| Opposition and blocking | arts. 8, 8 ter | No (`G05`) | Stop uploading statements and ask the team. |

**Consent.** Statements are processed when you upload them, without a recorded, purpose-specific consent (`G06`, art. 12). Linking an investment account is the exception: it asks for your consent, and the version of the text you accepted (`inv-consent-1`) is recorded on the audit event of the link.

## What is not built yet

Authentication in demo mode (`G01`), export, opposition and blocking (`G02`, `G05`), recorded consent (`G06`), the documented safeguards for transfers abroad (art. 27), the impact assessment (art. 15 ter) and an age check (art. 16 quáter; users are assumed to be adults).

## Breaches

If personal data is exposed, the team follows [runbooks/INCIDENT_RESPONSE.md](runbooks/INCIDENT_RESPONSE.md).

## Changes to this policy

This policy changes in this file, through the repository's normal review, and the date at the top changes with it. A deployer should tell its users about changes before they apply; how is to be decided by the team that runs the instance.
