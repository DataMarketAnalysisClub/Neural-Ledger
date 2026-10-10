# Data (synthetic only)

## `personas/` · calibrated fixtures
`camila.json` and `diego.json` are the **stage-1 targets** from the Financial Core design (§6): balances, income model, commitments, spend quantiles, seasonal factors, goals. The app runs on them today (`NL_MODEL_SOURCE=fixture`), and golden tests E01–E14 compute from them.

Notes:
- Seasonal factors are exact fractions (`"49/30"`), not decimals; `1.633` would shift December by 300 CLP and break E01/E03.
- The P50 split per category is a placeholder (0.8 × P80) until Roles A and E confirm it.
- One merchant label carries a prompt-injection string on purpose (test S01).

## `generator/` · Role E
The generator must write `ledgers/<user>.json`: 12 months of accounts and transactions that end exactly at the persona's opening state (as of 2026-10-29), such that Role A's estimators reproduce the persona file. Rules to respect:
- Card payments from checking are `transfer_own`; the card account carries the purchases and `CUOTA nn/NN` lines with structured installment metadata.
- A cuota labelled month M leaves checking in pay cycle M.
- Salary is credited on the last business day.
- Last December's P50-basis spend must be exactly 1,176,000 (seasonal factor 49/30).
- Seed the conditions: normal month, December crunch, goal deadline, the proposed purchase, one unexpected expense (300,000), and the injection merchant.

Acceptance: `backend/tests/golden/test_estimation.py` passes and its `xfail` is removed.
