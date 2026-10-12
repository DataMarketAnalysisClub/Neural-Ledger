# Contributing

## Workflow
- Branch from `main`: `<role>/<topic>`, e.g. `a/estimators`, `b/jev-adapter`, `d/dashboard`.
- Small PRs into `main`, one reviewer from another role, CI green. The integration owner merges.
- Daily 15-minute sync: what merged, what is blocked, what changes a contract.
- After the **Oct 17 feature freeze**, only fixes merge.

## Protected branches
`staging` is protected by a GitHub ruleset: changes reach it only through a pull request.
- At least **1 approving review**, from a role other than the author's. New pushes dismiss earlier approvals, and the last push must be approved by someone else.
- All review conversations resolved.
- Required CI checks green: `backend` and `compose` (`web` joins once the frontend is on `staging`).
- No direct pushes, force pushes or branch deletion.

The ruleset is versioned in `.github/rulesets/staging.json`. A repository admin applies or updates it with:
`gh api -X POST repos/DataMarketAnalysisClub/Neural-Ledger/rulesets --input .github/rulesets/staging.json`

Every PR fills in `.github/pull_request_template.md`, which mirrors the definition of done below and the rules in `CLAUDE.md`.

## Definition of done (every PR)
- [ ] `make test` passes, architecture tests included.
- [ ] If an interface changed: the contract in `contracts/` changed in the same PR and the contract tests pass.
- [ ] No new import in `domain/` or `application/` beyond the Python standard library.
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
