# Contributing

## Workflow
- Branch from `main`: `<role>/<topic>`, e.g. `a/estimators`, `b/jev-adapter`, `d/dashboard`.
- Small PRs into `main`, one reviewer from another role, CI green. The integration owner merges.
- Daily 15-minute sync: what merged, what is blocked, what changes a contract.
- After the **Oct 17 feature freeze**, only fixes merge.

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
