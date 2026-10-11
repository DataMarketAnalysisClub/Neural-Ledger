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
make install                       # pip install -e "backend[api,dev,pdf]" (use a virtualenv)
make test                          # architecture, golden answers, security suite, contracts, HTTP
make demo                          # the six-scene demo arc in the terminal
make api                           # dev server on :8000
make evidence                      # audit log + test results into evidence/
```

Bank statements (cartolas): `neural-ledger import-statement <file.pdf>` or `POST /v1/statements` with the file as the body. Text-layer PDFs work out of the box; scanned PDFs and photos need `pip install -e "backend[ocr]"` (EasyOCR; install the CPU torch wheel first) and the weights once: `python -c "from neural_ledger.adapters.outbound.statements.ocr_tabular import prepare_models; prepare_models()"`. Real statements go in `cartolas/`, which is git-ignored: never commit one.

On Windows without `make`, `.\scripts\dev.ps1 <task>` runs the same tasks (`install` creates `.venv` with Python 3.12).

To use a real LLM or Jev, copy `.env.example` to `.env` and set `NL_LLM`, `NL_DECISION_CHAIN` and the keys. Without them the app runs in **offline mode** (scripted model + rules decision model), which is also the fallback when a provider is down.

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
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, permission tiers, S01–S12 and known risks |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision log |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow and definition of done |

## Status (Oct 10, 2026)

- ✅ Offline end-to-end demo arc (six scenes), verified replies, hash-chained audit
- ✅ Financial core stage 2 (forecast, simulator, surplus, capacity, plan): all 14 golden answers E01–E14
- ✅ Security suite S01–S12 · contracts · architecture tests · SQLite adapter · CI workflow (first run on push)
- ⏳ Stage 1 estimators (Role A) and ledger generator (Role E) · real LLM provider choice (Role B) · Jev adapter (Role B) · frontend (Role D)

## Team

| Role | Owner |
|---|---|
| A · Finance core | Bruno Caro |
| B · Agent / AI | Luis-Felipe |
| C · Platform | Baptiste |
| D · Frontend | Vicente Ramírez |
| E · Quality and submission | Joaquín Parraud |

The data is synthetic. This is a sandbox: no real money, accounts or personal data.
