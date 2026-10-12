<!--
Title: conventional style, e.g. `feat(finance): …`, `fix(gate): …`, `test(security): …`, `docs: …`, `chore(ci): …` (CONTRIBUTING.md).
Branch: `<role>/<topic>` cut from `main` (a = finance, b = agent, c = platform, d = frontend, e = quality).
Keep it small. After the Oct 17 feature freeze, only fixes merge.
-->

## What and why

<!-- One or two sentences. Link the scene (1-6), golden answer (E01-E14) or security test (S01-S12) it touches, if any. -->

## Role and review

- Role of the author: <!-- A / B / C / D / E -->
- [ ] A reviewer **from another role** is requested (CONTRIBUTING.md). The integration owner merges.

## Definition of done (CONTRIBUTING.md, docs/SCOPE.md §12)

- [ ] `make test` passes, architecture tests included (CI `backend` job green).
- [ ] If an interface changed: the contract in `contracts/` changed **in this same PR** and the contract tests pass. Tool tiers in `application/catalog.py` still match `x-tier`.
- [ ] No new import in `domain/` or `application/` beyond the Python standard library (frameworks and SDKs stay in `adapters/`, wired only in `bootstrap/`).
- [ ] Every path that can move money is audited and covered by a security test (`tests/security`, model assumed hostile).
- [ ] Golden numbers E01-E14 unchanged, or the change is a recorded team decision with a new `params_version`.
- [ ] Docs updated if behaviour changed (`docs/SCOPE.md`, `docs/DECISIONS.md`; a contract change that breaks compatibility has an entry in `docs/DECISIONS.md`).

## Rules that must never break (CLAUDE.md)

- [ ] Money is computed and actions are authorized only by domain code; model output never sets an amount, a verdict or a permission.
- [ ] Execution terms come from the stored authorization; there is no confirm tool, only the user confirms through the UI endpoint.
- [ ] Every number the agent states is a fact in a tool envelope, and every warning is mentioned.
- [ ] Money stays an integer in minor units; ratios stay exact until the final rounding; money is never called "safe".
- [ ] Merchant, ledger and statement text is treated as untrusted data, never as instructions (and rendered as plain text in the UI).
- [ ] Any new port has an offline adapter, so `docker compose up` still runs with no keys.

## Frontend (only if `web/` changed)

- [ ] The UI renders API `data`/`facts` and never computes money; every amount shows its ISO currency code.
- [ ] Contract types regenerated (`npm run contracts`) and `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` pass (CI `web` job).
- [ ] No emojis; new strings live in `web/src/i18n/en.ts`.

## Public repository

- [ ] No API keys, `.env`, personal data or real documents (synthetic data only; settings go in `.env.example`).

## How it was tested

<!-- Commands run, screenshots for UI changes, `make demo` output if the demo arc is affected. -->
