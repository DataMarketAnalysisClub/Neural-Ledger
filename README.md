# Neural Ledger

**An AI cash-flow copilot that knows how much of your money is already committed to the future, and tells you what you can actually spend or save.**

FinTechathon 2026 · International Track (*Agent Wallet*) · Topic A: Personal Finance Assistant

> Balance ≠ available ≠ protected surplus. Camila's bank shows 920,000 CLP; her protected surplus is 20,000 CLP, because three cuotas overlap in December.

The agent answers three questions: *Can I afford this?* · *How much is really available?* · *What should I do with the surplus, and can you do it for me?* It can act on the sandbox wallet only inside limits the user confirmed. Models interpret language; **deterministic code computes every number and authorizes every action.**

## Quickstart

```bash
# Run everything offline (no API keys needed)
docker compose up --build          # API on http://localhost:8000  (GET /health)

# Or locally
make install                       # pip install -e "backend[api,dev,pdf,ml]" (use a virtualenv)
make test                          # fast lane: architecture, golden, security, contracts, HTTP (no property tests)
make test-all                      # full suite incl. hypothesis property tests: required for CI and PRs
make test-property                 # only the property tests (pytest -m property)
make demo                          # the six-scene demo arc in the terminal
make api                           # dev server on :8000
make evidence                      # audit log + full-suite test results into evidence/
```

Bank statements (cartolas): `neural-ledger import-statement <file.pdf>` or `POST /v1/statements` with the file as the body. Text-layer PDFs work out of the box; scanned PDFs and photos need `pip install -e "backend[ocr]"` (EasyOCR; install the CPU torch wheel first) and the weights once: `python -c "from neural_ledger.adapters.outbound.statements.ocr_tabular import prepare_models; prepare_models()"`. Real statements go in `cartolas/`, which is git-ignored: never commit one. A verified statement is also posted to the transaction ledger with a spending category per charge (naive Bayes, the `ml` extra): `neural-ledger transactions` or `GET /v1/transactions`. Use `NL_PERSISTENCE=sqlite` to keep them between CLI runs.

Personal data is removed from every cartola at import, before anything is stored (ADR-028). Names, RUTs, account and card numbers, emails and phones become placeholders such as `[PERSON]`, and the account keeps only its last 4 digits (`****3456`); merchants, amounts and dates stay. **A database created before this change still holds raw statements:** delete `var/neural_ledger.db` (Docker: `docker compose down --volumes`) and import again. Importing the same cartola into the old database would count as a duplicate and keep the old, unredacted copy.

**Who the user is (`NL_AUTH`).** Locally (`make api`, tests, the recorded demo) the default is `demo`: the `X-User-Id` header picks a persona (`camila` or `diego`), profiles are read-only and there are no auth routes. `docker compose up` runs `accounts`: sign up or sign in (`POST /v1/auth/signup`, `/v1/auth/signin`) or open a shared demo persona (`POST /v1/auth/demo-session`), and the API sets an HttpOnly `nl_session` cookie that expires 12 hours later. In this mode `X-User-Id` is rejected, POST/PUT requests must come from an origin in `NL_APP_ORIGINS` (or send JSON without an Origin), and account users can edit their name, language and risk questionnaire; each edit is saved together with its audit event or not at all. For example: `curl -c jar.txt -H 'Content-Type: application/json' -d '{"persona":"camila"}' localhost:8000/v1/auth/demo-session && curl -b jar.txt localhost:8000/v1/forecast`. The web UI must speak the same mode as the API it calls.

On Windows without `make`, `.\scripts\dev.ps1 <task>` runs the same tasks (`install` creates `.venv` with Python 3.12).

To use a real LLM or Jev, copy `.env.example` to `.env` and set `NL_LLM`, `NL_DECISION_CHAIN` and the keys. Without them the app runs in **offline mode** (scripted model + rules decision model), which is also the fallback when a provider is down. `NL_PII_DETECTOR=azure` adds Azure AI Language as a second redaction layer; it is off by default because it sends statement text to Microsoft (see `docs/SECURITY.md`).

## How it is built

Clean architecture: `adapters → application → domain`. The domain and the use cases import only the Python standard library; FastAPI, LLM providers, Jev, SQLite and the sandbox bank are adapters wired in one place (`backend/src/neural_ledger/bootstrap`). The rule is enforced by tests.

```
contracts/   JSON Schemas: the source of truth for tools, outputs, actions, audit, chat
backend/     domain · application · adapters · bootstrap · tests
data/        persona fixtures (Camila, Diego) and the ledger generator
web/         frontend (Role D)
docs/        SCOPE · ARCHITECTURE · SECURITY · DECISIONS
evidence/    exported audit logs and test results for the submission
```

| Read this | For |
|---|---|
| [docs/SCOPE.md](docs/SCOPE.md) | What we are building, the review findings, open decisions, the plan |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Where code goes and how to add tools, providers and adapters |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, permission tiers, S01–S15 and known risks |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision log |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow and definition of done |

## Status (Oct 10, 2026)

- ✅ Offline end-to-end demo arc (six scenes), verified replies, hash-chained audit
- ✅ Financial core stage 2 (forecast, simulator, surplus, capacity, plan): all 14 golden answers E01–E14
- ✅ Security suite S01–S12 · contracts · architecture tests · SQLite adapter · CI workflow (first run on push)
- ✅ Stage 1: deterministic ledger generator + estimators reproduce both personas exactly; E01–E14 also pass on the estimated models (`NL_MODEL_SOURCE=ledger`, `make demo-ledger`)
- ⏳ Real LLM provider choice (Role B) · Jev adapter (Role B) · frontend (Role D)

## Team

| Role | Owner |
|---|---|
| A · Finance core | Bruno Caro |
| B · Agent / AI | Luis-Felipe |
| C · Platform | Baptiste |
| D · Frontend | Vicente Ramírez |
| E · Quality and submission | Joaquín Parraud |

The data is synthetic. This is a sandbox: no real money, accounts or personal data.
