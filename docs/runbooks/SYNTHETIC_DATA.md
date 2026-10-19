# Synthetic data: random cartolas and a seeded database

Two ways to get realistic, fake bank data into Neural Ledger without touching a real statement:

| | `cartola`: a file to upload | `seed`: data already in the database |
|---|---|---|
| What you get | `.xlsx` cartolas on disk | statements and transactions stored for a user |
| How it reaches the app | you upload it (Statements page, API or CLI) | the app opens with it |
| Touches the database | no | yes (SQLite only) |
| Use it to | demo or test the import itself | demo the statements and transactions views, test with history |

Both write the same files. `seed` simply imports them for you through the **real import path** (read → redact → reconcile → store → post to the ledger → audit), the same use case as `POST /v1/statements`. Nothing is written to the database directly, so every seeded statement is reconciled, categorized and audited like an upload, and the audit chain stays valid.

## What the files contain

- **Santander checking account, `Cartola de cuenta Corriente` (.xlsx)**, one per month. A salary on the last weekday, rent on the 5th, utilities and subscriptions on fixed days, 25 to 45 card purchases at supermarkets, cafés, transport, pharmacies and shops, an occasional ATM withdrawal, and a transfer to savings on payday. Totals, the closing balance and every daily balance are computed from the movements, so the statement **reconciles and is posted** to the transaction ledger. Consecutive months chain: each one opens at the previous closing balance. A charge that would overdraw the account is left out.
- **BICE credit card, `Movimientos Nacionales de Tarjeta de Crédito` (.xlsx)**: this month's unbilled movements, a few purchases in cuotas (`1 de 3`, `1 de 6`), the payment of the previous bill and sometimes a refund. Like the real export, it is **provisional**: stored and shown, never posted to the ledger.

Merchants come from the classifier's training vocabulary, so most charges get a spending category. With `NL_CLASSIFIER=jev,naive_bayes` the categories come from Jev instead (ADR-032): seeding then calls Jev once per distinct merchant, about 30 calls for seven months of history, and falls back to naive Bayes without a key. This is live mode, so it needs `NL_HMAC_SECRET` set. Rent and ATM withdrawals stay `uncategorized`, because the classifier was not trained on them; that is the classifier's real behavior, not a generator bug. The savings transfer is a `movement` by the Santander layout's own-money rule (ADR-024), so it is not spending. The holder (`CLIENTE SINTETICO`, RUT `11.111.111-1`, an `example.com` email) and the account numbers are fictional, and redaction masks them at import anyway.

**Seeds.** Every run prints its seed. The same seed gives the same bytes, so `--seed 42` reproduces a file or a database exactly. Seeding twice with the same seed adds nothing (the statements are duplicates). A different seed adds a second, independent account history.

## 1. A random cartola to upload (`cartola`)

```bash
make cartola                         # last month's checking cartola + this month's card export, into var/samples/
make cartola MONTHS=3 SEED=42        # three chained months, reproducible
```

Or the command itself, with every option:

```bash
cd backend
PYTHONPATH=src python3 -m neural_ledger.bootstrap.cli cartola --months 3 --seed 42 --out ../var/samples
PYTHONPATH=src python3 -m neural_ledger.bootstrap.cli cartola --kind card --out ../var/samples
#   --kind checking|card   Santander checking (default) or BICE card export
#   --month YYYY-MM        checking: the last month (default: last full month); card: the export's month (default: this month to today)
#   --months N             checking: N consecutive months
#   --opening CLP          checking: opening balance of the first month (default: one salary)
#   --salary CLP           checking: monthly salary (default: random, 1.1M to 1.9M)
#   --seed N               reproducible output (default: random, printed)
#   --out DIR              where to write (default: current folder)
```

`var/` is git-ignored, so the files never reach the repository. Then import them with any of these:

- **Web app:** Statements page → choose the file. The upload screen comes with PR #22; on `main` before that, the page is a placeholder behind `VITE_FEATURE_STATEMENTS`.
- **API:** `curl -X POST -H "X-User-Id: camila" --data-binary @var/samples/<file>.xlsx http://localhost:8000/v1/statements`
- **CLI:** `cd backend && PYTHONPATH=src python3 -m neural_ledger.bootstrap.cli import-statement ../var/samples/<file>.xlsx`

On Windows: `.\scripts\dev.ps1 cartola --months 3 --seed 42`.

## 2. A database that opens with data (`seed`)

The API must read the same SQLite file the seed writes to. With the in-memory store, the data would be gone as soon as the command exits, so `seed` refuses to run with `NL_PERSISTENCE=memory`.

**Docker (the submission path).** The container already uses SQLite on the `ledger-data` volume:

```bash
docker compose up --build -d
docker compose exec api neural-ledger seed --user camila            # 7 months + this month's card export
docker compose exec api neural-ledger seed --user diego --seed 42   # the other persona, reproducible
```

Open http://localhost:3000, pick the persona you seeded, and go to Statements.

**Locally.**

```bash
make seed                                   # camila, 7 months, random seed (printed)
make seed PERSONA=diego MONTHS=12 SEED=42
NL_PERSISTENCE=sqlite make api              # the API on the same database (backend/var/neural_ledger.db)
```

Options of `neural-ledger seed`: `--user` (default `NL_PERSONA`, i.e. `camila`), `--months` (default 7, ending last month: six full pay cycles, the least the forecast accepts, ADR-029), `--seed`, `--opening`, `--salary`, `--no-card`. On Windows: `.\scripts\dev.ps1 seed --user diego --seed 42`, then start the API with `NL_PERSISTENCE=sqlite`.

**For a signed-up account** (accounts mode), seed its own id, as `/v1/me` shows it (`usr_…`): its financial screens then use the seeded statements, so the forecast, purchase check and plan show that account's numbers. Six calendar months are only five full pay cycles, because the first month's salary is paid on the previous month's payday; the screens then say `history (at least 6 months, found 5)`.

**Users.** The web app identifies users by the `X-User-Id` header and offers two personas, `camila` and `diego`. Seed one of them to see the data in the UI. Any other `--user` works through the API and CLI only.

**Start over.** `make reset` (or `neural-ledger reset`; `--yes`, or `make reset YES=1`, skips the prompt) empties every table of the database in place: the file and schema stay, so a running API keeps working, and the audit chain restarts from genesis. In Docker: `docker compose exec api neural-ledger reset --yes`. Restart the API afterwards, because chat history, profiles and snapshots live in its memory; then `make seed`. `docker compose down --volumes` also works and wipes the whole volume. This is a developer command, not the user-facing deletion of personal data (gap G03).

**Check it worked.**

```bash
NL_PERSISTENCE=sqlite PYTHONPATH=src python3 -m neural_ledger.bootstrap.cli statements --user camila     # from backend/
NL_PERSISTENCE=sqlite PYTHONPATH=src python3 -m neural_ledger.bootstrap.cli transactions --user camila
curl -H "X-User-Id: camila" http://localhost:8000/v1/transactions
```

## What it does not change

- **The overview, forecast, simulator and plan** still compute from the persona model (`NL_MODEL_SOURCE=fixture` or `ledger`), not from imported statements. Feeding imported data into the forecast is ADR-029 (plan, not built). Seeded data shows on the Statements and Transactions views and in `/v1/statements` and `/v1/transactions`.
- **Golden answers E01–E14** do not read imported statements, so seeding cannot move them.
- **The recorded demo** (`make demo`) uses the in-memory store and never sees seeded data.

## Where the code is

| What | Where |
|---|---|
| Generator (layouts, merchants, chaining, seeds) | `backend/src/neural_ledger/adapters/outbound/statements/synthetic.py` |
| `cartola` and `seed` commands | `backend/src/neural_ledger/adapters/inbound/cli/commands.py` (wired in `bootstrap/cli.py`) |
| Tests: reconciles, chains, never overdraws, reproducible, idempotent seed, no holder data stored | `backend/tests/adapters/test_synthetic_statements.py` |

If a bank layout changes in `banks/santander_xlsx.py` or `banks/bice_xlsx.py`, change `synthetic.py` with it; the tests read every generated file back through the real readers and fail if they drift apart.
