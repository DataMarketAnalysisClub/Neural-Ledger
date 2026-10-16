# Contributing

## Workflow
- Branch from `staging`: `<role>/<topic>`, e.g. `a/estimators`, `b/jev-adapter`, `d/dashboard`.
- Small PRs into `staging`, one reviewer from another role, CI green. Never push to `staging` or `main` directly: CI only checks what arrives through a PR or a push to those branches, and a direct push skips review.
- `staging` is the integration branch. The integration owner merges PRs into it and promotes `staging` to `main` once it is green; merge with a merge commit, not a squash, so authorship and stacked PRs survive.
- Daily 15-minute sync: what merged, what is blocked, what changes a contract.
- After the **Oct 17 feature freeze**, only fixes merge.

## Protected branches
`staging` is protected by a GitHub ruleset: changes reach it only through a pull request.
- At least **1 approving review**, from a role other than the author's. New pushes dismiss earlier approvals, and the last push must be approved by someone else.
- All review conversations resolved.
- Required CI checks green: `backend`, `compose` and `web`.
- No direct pushes, force pushes or branch deletion.

The ruleset is versioned in `.github/rulesets/staging.json`. A repository admin applies or updates it with:
`gh api -X POST repos/DataMarketAnalysisClub/Neural-Ledger/rulesets --input .github/rulesets/staging.json`

Every PR fills in `.github/pull_request_template.md`, which mirrors the definition of done below and the rules in `CLAUDE.md`.

## Definition of done (every PR)
- [ ] `make test-all` passes (the full suite, property tests and architecture tests included). `make test` is only the fast iteration lane and is not enough for a PR or CI.
- [ ] If an interface changed: the contract in `contracts/` changed in the same PR and the contract tests pass.
- [ ] No new import in `domain/` or `application/` beyond the Python standard library, and no clock, randomness or I/O there either (time and ids come through ports; `tests/architecture` checks both).
- [ ] Every path that can move money is audited and covered by a security test.
- [ ] Golden numbers unchanged, or the change is a recorded team decision with a new `params_version`.
- [ ] Docs updated if behaviour changed (`docs/SCOPE.md`, `docs/DECISIONS.md`).

## Commits
Conventional style: `feat(finance): …`, `fix(gate): …`, `test(security): …`, `docs: …`, `chore(ci): …`.

## This repository is public
Never commit API keys, `.env`, personal data or real documents. Use `.env.example` for settings and synthetic data only.

## Local setup
```bash
python3 -m venv .venv && source .venv/bin/activate
make install && make test && make demo
```

`make test` deselects the hypothesis property tests (`backend/tests/property`, marker `property`) so iteration stays fast. Use `make test-property` (`pytest -m property`) for the property lane alone and `make test-all` (`pytest -m ""`) for everything; `make evidence` always records the full suite. Running `pytest tests/property` without `-m property` selects nothing, because the default deselects that marker.
