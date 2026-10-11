# Financial-core freeze dry-run (requested Oct 10)

**Execution:** Oct 11, 2026, America/Santiago. The filename follows the requested Oct 10 dry-run label; it is not the execution date. This is **not a freeze**. No tag, push, merge or final-evidence commit was made. A+E parameter sign-off and the Oct 17 calendar gate remain pending.

The checks ran in a clean detached worktree at `70e2240ba32360f7d055e9e2b9f10e412080610e` (`a/fc-6-submission-docs` WP4), with its own `/tmp/opencode/neural-ledger-freeze-20261010/.venv/bin/python` as absolute `PY`. The worktree had no tracked changes after regeneration and evidence export. Its virtual environment installed Hypothesis 6.169.0 from the current unpinned dev extra; the main checkout had 6.168.5. Both full suites passed.

| Check | Command (all `make` targets use the worktree's absolute `PY`) | Result and evidence |
|---|---|---|
| Clean install | `make install` | **PASS:** editable package with API/dev extras installed into the new worktree venv. |
| Fast tests | `make test` | **PASS:** 381 passed, 18 property tests deselected; one pre-existing Starlette/TestClient deprecation warning. |
| Full tests | `make test-all` | **PASS:** 395 passed, 2 strict xfailed, 2 non-strict xpassed; same deprecation warning. |
| Property lane | `make test-property` | **PASS:** 14 passed, 2 xfailed, 2 xpassed; 381 deselected. ADR-014 remains unresolved on this branch. |
| Golden answers | `make test-golden` | **PASS:** 55 passed, including fixture/ledger E01-E14 and reconciliation; no golden changes. |
| Security | `make test-security` | **PASS:** 14 passed; this branch does not include WP2's proposed forwarding tests. |
| Fixture demo | `make demo` | **PASS:** six scenes, verified replies and `Audit chain: OK (22 events)`. |
| Ledger demo | `make demo-ledger` | **PASS:** six scenes, verified replies and `Audit chain: OK (22 events)`; fixture remains the default. |
| Persona regeneration | `make ledgers && git diff --exit-code -- data/ledgers` | **PASS:** Camila and Diego regenerated without a tracked diff. |
| Synthetic backtest | `make backtest` twice; SHA-256 and `git diff --exit-code -- evidence/backtest/synthetic_backtest.json` | **PASS:** both runs had identical hash `ee5a6dc0d3304984faf62d863ddcd4a03537c06229ea0e3bd74f964c7632e1b1`, identical to the committed WP4 artifact. Expected coverage remains a synthetic reference, not predictive accuracy; see `docs/BACKTEST.md`. |
| Evidence export | `make evidence` | **PASS:** exported a fixed-clock audit and JUnit from the **full** suite: 395 passed, 2 xfailed, 2 xpassed. The generated JUnit and audit files stayed ignored and were **not** committed as final evidence. |
| Audit verification | Deserialize the 22 exported JSONL records with `AuditEvent.from_record` and call `verify_chain` | **PASS:** `ChainCheck(ok=True, checked=22, broken_at=None, reason=None)`. Events: 6 DECISION, 11 TOOL_CALL, one each PROPOSAL_CREATED, ACTION_CONFIRMED, ACTION_BLOCKED, EXECUTION_STARTED and ACTION_EXECUTED. |
| Ruff and working-tree hygiene | `.venv/bin/python -m ruff check backend`, `git diff --check`, detached worktree `git status --short` | **PASS:** Ruff clean; no tracked diff or stray evidence staged. |
| Compose syntax | `docker compose config --quiet` | **PASS:** configuration parses without an `.env` or API keys. This does not build an image. |
| Clean-checkout container | `docker compose up --build` | **BLOCKED:** `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`. No image was built and no container started. No sudo, daemon install, socket/group changes or alternate host was used. |
| Container health | `curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/health` | **BLOCKED:** `curl: (7) Failed to connect to 127.0.0.1:8000 ... Could not connect to server`. This cannot establish app health without a running container. |

Evidence SHA-256 from this clean worktree (dry-run copies only):

```text
0f9cd19d3cfa2ce3fef4ae6a8f0bf05ad6d77b43553bf7fad67e4a3ae2901365  evidence/test-results/junit.xml
36e2bf2818bd61e57196ce2126253d3d5fb405937ad1af320801635788b0f9bc  evidence/sandbox-logs/audit.jsonl
ee5a6dc0d3304984faf62d863ddcd4a03537c06229ea0e3bd74f964c7632e1b1  evidence/backtest/synthetic_backtest.json
```

**Required before the real freeze:** have a human with Docker daemon access run `docker compose up --build` in a clean checkout and observe `/health`; then rerun the full checklist and capture final evidence. The Dockerfile currently copies `backend/pyproject.toml` but not `backend/README.md`, while `pyproject.toml` names `README.md` relative to `backend/`; the prior editable-install fix has not been exercised inside Docker and may make the image build fail once daemon access is granted. Review the Dockerfile as a separate scoped fix with a real build check, not as a claimed dry-run pass. A+E must approve the parameters and the reviewed commit before any Oct 17 freeze/tag decision.
