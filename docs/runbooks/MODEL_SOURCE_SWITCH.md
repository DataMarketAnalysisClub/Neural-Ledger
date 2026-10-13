# Model-source switch: preparation only (FC-4)

**PENDING: coordinate with Role B at the Oct 12 first integration.** Today `Settings.model_source` and `.env.example` remain `fixture`; `NL_MODEL_SOURCE=ledger` is an explicit opt-in. No switch is authorized by this runbook.

Before approval: B signs off on explanation semantics and decides whether to forward estimator facts/warnings from `LedgerModelSource.load` (currently discarded; see `docs/EXPLANATION_HANDOFF.md`). Compare `make demo` and `make demo-ledger` audit behavior, including all 22 events, plus golden tests on both model sources and full security suite. Inspect sparse/provisional warnings and invalid/missing field rendering with B. Record the chosen behavior in contracts and tests **in the same change** as any interface change.

When approved, change the default in `backend/src/neural_ledger/bootstrap/config.py`, `.env.example`, relevant Makefile demo targets and user documentation together. Test explicit fixture override as rollback. Run `make test-all`, `make test-golden`, `make test-security`, `make demo`, `make demo-ledger` with absolute `PY`, verify the audit chain and compare outputs. If B does not approve or behavior differs, retain/revert to `fixture` and preserve the current opt-in ledger path. Do not merge or push without human review.
