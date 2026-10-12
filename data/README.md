# Data (synthetic only)

## `personas/` · calibrated fixtures
`camila.json` and `diego.json` are the **stage-1 targets** from the Financial Core design (§6): balances, income model, commitments, spend quantiles, seasonal factors, goals. The app runs on them today (`NL_MODEL_SOURCE=fixture`), and golden tests E01–E14 compute from them.

Notes:
- Seasonal factors are exact fractions (`"49/30"`), not decimals; `1.633` would shift December by 300 CLP and break E01/E03.
- The P50 split per category is a placeholder (0.8 × P80) until Roles A and E confirm it.
- One merchant label carries a prompt-injection string on purpose (test S01).

## `ledgers/` · generated sandbox ledgers (stage 1)
`camila.json` and `diego.json` are 12 complete pay cycles (2025-11 .. 2026-10) ending on **as_of 2026-10-29**, the day before October's salary. The stage-1 estimators (`backend/src/neural_ledger/domain/finance/estimation.py`) turn each one into exactly the matching persona file; `tests/golden/test_estimation.py` checks it field by field, and E01–E14 run on both sources.

- Generator: `backend/tests/fixtures/ledger_generator.py` (seeded, deterministic). Regenerate with `make ledgers`; a test fails if the committed files differ from a fresh run. Do not edit them by hand.
- Run the app on them with `NL_MODEL_SOURCE=ledger` (`make demo-ledger`). The default stays `fixture`.
- Accounts: `checking` (920,000), `credit_card`, `savings` with buckets `reserve` 1,500,000 and `goal:trip` 900,000. Each account carries `opening_balance`, and opening + Σ transactions = closing (`tests/golden/test_reconciliation.py`).
- Contract: `contracts/ledger/ledger.schema.json`. Malformed input (non-integer or absurd amounts, other currencies, dates after as_of, unknown kinds or accounts, non-positive income) returns `INVALID_INPUT` with the offending field.
- The generator takes a `GeneratorConfig`; the personas are two configs, and `tests/property` builds random valid configs for the invariants.
- Every transaction has a `kind`. Cuotas are card lines with structured `installment` metadata and the text `CUOTA nn/NN`; a cuota labelled month M is billed on day 1 of M. The card is paid from checking on day 10 as `transfer_own`; own-account sweeps (savings, an external mutual fund) are `transfer_own` too, so no money is counted twice.
- Variable spend is built so the quantiles are exact: over the 11 non-seasonal cycles the 6th sorted value is the P50 and the 9th is the P80. December 2025 is P50 × 49/30 in every category (total 1,176,000). The 300,000 unexpected expense is a health purchase in a non-December cycle.
- Diego: freelance income with P50 1,800,000, P20 1,300,000, no zero month and a sample (ddof=1) CV of exactly 3/10.
- Seeded conditions: the injection merchant (Camila's travel cuotas, S01), an exact duplicate `txn_id` and a near-duplicate (S12), a refund, a December bonus (never income) and a finished cuota plan (not a commitment).
- Pay cycles use the last weekday of the month as payday; Chilean holidays are ignored (a documented simplification, `docs/SCOPE.md` F11).

## `generator/`
Superseded by `backend/tests/fixtures/ledger_generator.py` (kept next to the tests that consume it).
