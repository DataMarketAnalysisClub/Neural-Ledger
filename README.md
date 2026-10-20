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
make cartola                       # random synthetic cartolas (.xlsx) in var/samples/, to upload in the app
make seed                          # random statements imported into SQLite (then: NL_PERSISTENCE=sqlite make api)
make reset                         # developer only: empty the local SQLite database in place, then make seed
```

Synthetic data for demos and testing: `make cartola` writes random cartolas that reconcile, to upload like a real export; `make seed` (or `docker compose exec api neural-ledger seed --user camila`) imports months of them so the app opens with statements and transactions. Both go through the real import path. See [docs/runbooks/SYNTHETIC_DATA.md](docs/runbooks/SYNTHETIC_DATA.md).

Bank statements (cartolas): `neural-ledger import-statement <file>` or `POST /v1/statements` with the file as the body. Excel exports (`.xlsx`) need nothing extra and never go through PDF or OCR; text-layer PDFs need the `pdf` extra (in the Docker image). Credit card statements (Excel or PDF) are detected as such and carry their obligations: amount due, minimum, due date and the cuotas left. Scanned PDFs and photos need `pip install -e "backend[ocr]"` (EasyOCR; install the CPU torch wheel first) and the weights once: `python -c "from neural_ledger.adapters.outbound.statements.ocr_tabular import prepare_models; prepare_models()"`. Real statements go in `cartolas/`, which is git-ignored: never commit one. A verified statement is also posted to the transaction ledger with a spending category per charge (naive Bayes, the `ml` extra): `neural-ledger transactions` or `GET /v1/transactions`. Use `NL_PERSISTENCE=sqlite` to keep them between CLI runs.

Personal data is removed from every cartola at import, before anything is stored (ADR-028). Names, RUTs, account and card numbers, emails and phones become placeholders such as `[PERSON]`, and the account keeps only its last 4 digits (`****3456`); merchants, amounts and dates stay. **A database created before this change still holds raw statements:** delete `backend/var/neural_ledger.db` and its `.key` file (Docker: `docker compose down --volumes`) and import again. Importing the same cartola into the old database would count as a duplicate and keep the old, unredacted copy.

**Who the user is (`NL_AUTH`).** Locally (`make api`, tests, the recorded demo) the default is `demo`: the `X-User-Id` header picks a persona (`camila` or `diego`), profiles are read-only and there are no auth routes. `docker compose up` runs `accounts`: sign up or sign in (`POST /v1/auth/signup`, `/v1/auth/signin`) or open a shared demo persona (`POST /v1/auth/demo-session`), and the API sets an HttpOnly `nl_session` cookie that expires 12 hours later. In this mode `X-User-Id` is rejected, POST/PUT requests must come from an origin in `NL_APP_ORIGINS` (or send JSON without an Origin), and account users can edit their name, language and risk questionnaire; each edit is saved together with its audit event or not at all. For example: `curl -c jar.txt -H 'Content-Type: application/json' -d '{"persona":"camila"}' localhost:8000/v1/auth/demo-session && curl -b jar.txt localhost:8000/v1/forecast`. The web UI must speak the same mode as the API it calls.

**Explaining financial terms (ADR-039).** When you ask what a term means, the copilot answers from concept cards the team wrote (Spanish and English, in `backend/src/neural_ledger/adapters/outbound/knowledge/corpus/`), never from the model's memory. By default a lexical search over the cards runs offline and needs nothing extra. For semantic, multilingual search, install the `rag` extra, `pip install -e "backend[rag]"`, and set `NL_KNOWLEDGE_BASE=chroma,lexical` in `.env` (Chroma first, the lexical search as the fallback). The index is kept under `NL_KB_DIR` (default `./var/chroma`) and rebuilt when a card changes. The first run downloads the embedding model (`paraphrase-multilingual-MiniLM-L12-v2`), so it needs the network once; `NL_KB_EMBEDDING_MODEL` picks another. With Docker, the index runs in its own container: set `NL_API_EXTRAS=api,pdf,ml,rag` and `NL_KNOWLEDGE_BASE=chroma,lexical` in `.env`, then `docker compose --profile rag up --build`; the API reaches it at `NL_KB_URL` (`http://chroma:8000`). Without the profile, Docker runs on the lexical search. Each answer records the `knowledge_base` that served it.

On Windows without `make`, `.\scripts\dev.ps1 <task>` runs the same tasks (`install` creates `.venv` with Python 3.12).

To use a real LLM or Jev, copy `.env.example` to `.env` and set `NL_LLM`, `NL_DECISION_CHAIN` and the keys. Without them the app runs in **offline mode** (scripted model + rules decision model), which is also the fallback when a provider is down. Live mode also needs `NL_HMAC_SECRET` set: it refuses to start with the development default. `NL_CLASSIFIER=jev,naive_bayes` categorizes statement lines with Jev and falls back to the offline naive Bayes; it sends each charge's redacted text to Jev (ADR-032). `NL_PII_DETECTOR=azure` adds Azure AI Language as a second redaction layer; it is off by default because it sends statement text to Microsoft (see `docs/SECURITY.md`).

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
| [docs/PRIVACY.md](docs/PRIVACY.md) | Privacy policy: what data is processed, where, for how long, who receives it, and what is not built yet |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision log |
| [docs/runbooks/SYNTHETIC_DATA.md](docs/runbooks/SYNTHETIC_DATA.md) | Random cartolas to upload, and seeding the database with them |
| [docs/runbooks/INCIDENT_RESPONSE.md](docs/runbooks/INCIDENT_RESPONSE.md) | Breach response: detect, contain, assess, notify, recover, learn |
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
